# controllers/reunion_controller.py
# Controlador de reuniones — refactorizado para:
#   1. Usar duenio.es_immune en vez del import de es_dueno_inmune (eliminado).
#   2. Eliminar if/else de autorización duplicados.
#   3. Proteger el endpoint AJAX de eliminación con @login_required.
#   4. Llamar _gestionar_multa_asistencia desde asistencia_controller
#      o replicar la lógica necesaria localmente para no crear acoplamiento inverso.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from datetime import datetime
from sqlalchemy import text

from models.reunion_model    import Reunion
from models.duenio_model     import Duenio
from models.asistencia_model import Asistencia
from models.multa_model      import Multa
from views import reunion_view
from utils.decorators import role_required
from database import db

reunion_bp = Blueprint("reunion", __name__)


# ─────────────────────────── LISTADO ─────────────────────────────────────────

@reunion_bp.route("/reuniones")
def list_reuniones():
    """Lista todas las reuniones. Acceso público (solo lectura)."""
    reuniones = Reunion.get_all()
    return reunion_view.list_reuniones(reuniones)


# ─────────────────────────── CREAR ───────────────────────────────────────────

@reunion_bp.route("/reuniones/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_reunion():
    """Crea una reunión y genera asistencias + multas para todos los propietarios."""
    if request.method == "POST":
        fecha_str   = request.form.get("fecha", "")
        hora_str    = request.form.get("hora",  "")
        descripcion = request.form.get("descripcion")
        monto_multa = request.form.get("monto_multa", 100.0, type=float)

        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            hora  = datetime.strptime(hora_str,  "%H:%M").time()
        except ValueError:
            flash("Formato de fecha u hora inválido.", "error")
            return reunion_view.create_reunion()

        reunion = Reunion(fecha=fecha, hora=hora, descripcion=descripcion, monto_multa=monto_multa)
        reunion.save()

        # Crear asistencias y multas para todos los propietarios
        duenios = Duenio.query.all()
        for duenio in duenios:
            asistencia = Asistencia(duenio_id=duenio.id, id_reunion=reunion.id)
            asistencia.save()

            # Aplicar multa inicial por inasistencia (se elimina si luego asiste)
            if monto_multa > 0 and not duenio.es_immune:
                multa = Multa(
                    duenio_id=duenio.id,
                    reunion_id=reunion.id,
                    monto=monto_multa,
                    tipo='asistencia',
                    descripcion=f'Multa por no asistir a reunión {reunion.id}',
                )
                multa.save()

        flash("Reunión creada exitosamente.", "success")
        return redirect(url_for("reunion.list_reuniones"))

    return reunion_view.create_reunion()


# ─────────────────── CREAR (ENDPOINT AJAX con procesamiento por lotes) ───────

@reunion_bp.route("/api/reuniones/create", methods=["POST"])
@login_required
@role_required("admin")
def create_reunion_ajax():
    """
    Crea una reunión procesando propietarios en lotes de 50
    para evitar timeouts con grandes volúmenes de datos.
    """
    try:
        data        = request.get_json()
        fecha_str   = data["fecha"]
        hora_str    = data["hora"]
        descripcion = data.get("descripcion", "")
        monto_multa = float(data.get("monto_multa", 100.0))

        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        hora  = datetime.strptime(hora_str,  "%H:%M").time()

        reunion = Reunion(fecha=fecha, hora=hora, descripcion=descripcion, monto_multa=monto_multa)
        reunion.save()

        duenios      = Duenio.query.all()
        lote_size    = 50
        procesados   = 0

        for i in range(0, len(duenios), lote_size):
            for duenio in duenios[i:i + lote_size]:
                db.session.add(Asistencia(duenio_id=duenio.id, id_reunion=reunion.id))

                if monto_multa > 0 and not duenio.es_immune:
                    db.session.add(Multa(
                        duenio_id=duenio.id,
                        reunion_id=reunion.id,
                        monto=monto_multa,
                        tipo='asistencia',
                        descripcion=f'Multa por no asistir a reunión {reunion.id}',
                    ))
                procesados += 1

            db.session.commit()  # Commit por lote para liberar memoria

        return jsonify({
            "success": True,
            "message": f"Reunión creada. Se procesaron {procesados} propietarios.",
            "reunion_id": reunion.id,
            "total_procesados": procesados,
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────── ACTUALIZAR ──────────────────────────────────────

@reunion_bp.route("/reuniones/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_reunion(id):
    """Actualiza los datos de una reunión."""
    reunion = Reunion.get_by_id(id)
    if not reunion:
        flash("Reunión no encontrada.", "error")
        return redirect(url_for("reunion.list_reuniones"))

    if request.method == "POST":
        fecha_str   = request.form.get("fecha")
        hora_str    = request.form.get("hora")
        descripcion = request.form.get("descripcion")
        monto_multa = request.form.get("monto_multa", type=float)

        # Construir kwargs solo con los campos presentes para update() parcial
        kwargs = {}
        if fecha_str:
            kwargs['fecha'] = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        if hora_str:
            kwargs['hora'] = datetime.strptime(hora_str, "%H:%M").time()
        if descripcion is not None:
            kwargs['descripcion'] = descripcion
        if monto_multa is not None:
            kwargs['monto_multa'] = monto_multa

        reunion.update(**kwargs)
        flash("Reunión actualizada exitosamente.", "success")
        return redirect(url_for("reunion.list_reuniones"))

    return reunion_view.update_reunion(reunion)


# ─────────────────────────── ELIMINAR (AJAX) ─────────────────────────────────

@reunion_bp.route("/api/reuniones/delete", methods=["POST"])
@login_required          # Protección añadida: este endpoint no tenía @login_required
@role_required("admin")
def delete_reunion_ajax():
    """
    Elimina una reunión y todos sus datos asociados usando SQL masivo
    (más eficiente que eliminar fila por fila con el ORM para grandes datasets).
    """
    try:
        data       = request.get_json()
        reunion_id = data.get("reunion_id")

        if not reunion_id:
            return jsonify({"success": False, "error": "ID de reunión es requerido."}), 400

        reunion = Reunion.get_by_id(reunion_id)
        if not reunion:
            return jsonify({"success": False, "error": f"Reunión {reunion_id} no encontrada."}), 404

        reunion_descripcion = reunion.descripcion or f"Reunión {reunion_id}"

        # Obtener conteos antes de eliminar para informar al cliente
        multas_count      = Multa.query.filter_by(reunion_id=reunion_id).count()
        asistencias_count = Asistencia.query.filter_by(id_reunion=reunion_id).count()

        # Eliminación masiva con SQL directo (respeta los nombres exactos de tablas y columnas)
        db.session.execute(text("DELETE FROM Multa     WHERE reunion_id  = :rid"), {"rid": reunion_id})
        db.session.execute(text("DELETE FROM Asistencia WHERE id_reunion = :rid"), {"rid": reunion_id})
        db.session.execute(text("DELETE FROM Reunion   WHERE id          = :rid"), {"rid": reunion_id})
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Reunión '{reunion_descripcion}' eliminada exitosamente.",
            "multas_eliminadas":      multas_count,
            "asistencias_eliminadas": asistencias_count,
            "reunion_descripcion":    reunion_descripcion,
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────── ELIMINAR (FORMULARIO) ───────────────────────────

@reunion_bp.route("/reuniones/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_reunion(id):
    """Elimina una reunión vía formulario HTML estándar."""
    reunion = Reunion.get_by_id(id)
    if not reunion:
        flash("Reunión no encontrada.", "error")
        return redirect(url_for("reunion.list_reuniones"))

    try:
        # Eliminar dependientes antes de la reunión (cascade manual)
        Multa.query.filter_by(reunion_id=id).delete()
        Asistencia.query.filter_by(id_reunion=id).delete()
        db.session.delete(reunion)
        db.session.commit()
        flash("Reunión eliminada exitosamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar la reunión: {e}", "error")

    return redirect(url_for("reunion.list_reuniones"))
