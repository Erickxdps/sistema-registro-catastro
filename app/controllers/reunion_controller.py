# controllers/reunion_controller.py
# Reuniones: listado público paginado y operaciones de administración.
#
# Reglas (definidas en Reunion): al crear una reunión se crea una asistencia
# por propietario y la multa inicial de inasistencia; al eliminarla se borran
# sus asistencias y multas. Todo en UNA transacción: si algo falla, no queda
# ninguna reunión a medio crear.
#
# Contratos JSON conservados:
#   POST /api/reuniones/create  → {success, message, reunion_id, total_procesados}
#   POST /api/reuniones/delete  → {success, message, multas_eliminadas,
#                                  asistencias_eliminadas, reunion_descripcion}

from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import case, func

from database import db
from models.asistencia_model import Asistencia
from models.reunion_model import Reunion
from utils.busqueda import filtro_por_palabras
from utils.decorators import role_required
from utils.fechas import hoy
from utils.pagination import obtener_orden, obtener_paginacion, paginar
from views import reunion_view

reunion_bp = Blueprint("reunion", __name__)

ORDEN_REUNIONES = {
    "-fecha": [Reunion.fecha.desc(), Reunion.hora.desc(), Reunion.id.desc()],
    "fecha": [Reunion.fecha.asc(), Reunion.hora.asc(), Reunion.id.asc()],
    "descripcion": [Reunion.descripcion.asc(), Reunion.id.asc()],
    "-descripcion": [Reunion.descripcion.desc(), Reunion.id.desc()],
    "multa": [Reunion.monto_multa.asc(), Reunion.id.asc()],
    "-multa": [Reunion.monto_multa.desc(), Reunion.id.desc()],
}

MONTO_MULTA_MAXIMO = 100_000


def _validar(fecha_str, hora_str, descripcion, monto_raw, parcial=False):
    """Valida los datos de una reunión. Devuelve (datos, error).
    Con parcial=True, los campos vacíos se omiten (actualización)."""
    datos = {}
    try:
        if fecha_str or not parcial:
            datos["fecha"] = datetime.strptime((fecha_str or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None, "La fecha no es válida. Usa el selector de fecha."
    try:
        if hora_str or not parcial:
            hora = (hora_str or "").strip()[:5]  # acepta HH:MM y HH:MM:SS
            datos["hora"] = datetime.strptime(hora, "%H:%M").time()
    except ValueError:
        return None, "La hora no es válida. Usa el formato HH:MM."

    if descripcion is not None:
        descripcion = descripcion.strip()
        if len(descripcion) > 255:
            return None, "El tema no puede pasar de 255 caracteres."
        datos["descripcion"] = descripcion

    if monto_raw not in (None, "") or not parcial:
        try:
            monto = float(monto_raw if monto_raw not in (None, "") else 100.0)
        except (TypeError, ValueError):
            return None, "La multa por inasistencia debe ser un número."
        if monto < 0 or monto > MONTO_MULTA_MAXIMO:
            return None, "La multa por inasistencia debe estar entre 0 y 100.000 Bs."
        datos["monto_multa"] = round(monto, 2)
    return datos, None


def _conteos_asistencia(ids):
    """{reunion_id: (presentes, total)} en una sola consulta."""
    if not ids:
        return {}
    filas = (db.session.query(Asistencia.id_reunion,
                              func.sum(case((Asistencia.asistio.is_(True), 1), else_=0)),
                              func.count(Asistencia.id))
             .filter(Asistencia.id_reunion.in_(ids))
             .group_by(Asistencia.id_reunion).all())
    return {rid: (int(p or 0), int(t or 0)) for rid, p, t in filas}


# ─────────────────────────── LISTADO (público) ───────────────────────────────

@reunion_bp.route("/reuniones")
def list_reuniones():
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_REUNIONES, "-fecha")
    query = Reunion.query
    filtro = filtro_por_palabras(search, [Reunion.descripcion, Reunion.fecha])
    if filtro is not None:
        query = query.filter(filtro)
    pag = paginar(query.order_by(*clausulas), page, per_page)
    return reunion_view.list_reuniones(pag, search, orden,
                                       conteos=_conteos_asistencia([r.id for r in pag.items]),
                                       hoy=hoy())


# ─────────────────────────── CREAR ───────────────────────────────────────────

def _crear(datos):
    reunion, total = Reunion.crear_con_asistencias(
        datos["fecha"], datos["hora"], datos.get("descripcion") or None, datos["monto_multa"])
    db.session.commit()
    return reunion, total


@reunion_bp.route("/reuniones/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_reunion():
    """Formulario clásico (sin JavaScript). La interfaz usa /api/reuniones/create."""
    if request.method == "POST":
        datos, error = _validar(request.form.get("fecha"), request.form.get("hora"),
                                request.form.get("descripcion", ""), request.form.get("monto_multa"))
        if error:
            flash(error, "error")
            return reunion_view.create_reunion()
        try:
            _, total = _crear(datos)
        except Exception:
            db.session.rollback()
            flash("No se pudo crear la reunión. No se guardó nada.", "error")
            return reunion_view.create_reunion()
        flash(f"Reunión creada. Se registró la lista de {total} propietarios.", "success")
        return redirect(url_for("reunion.list_reuniones"))

    return reunion_view.create_reunion()


@reunion_bp.route("/api/reuniones/create", methods=["POST"])
@login_required
@role_required("admin")
def create_reunion_ajax():
    data = request.get_json(silent=True) or {}
    datos, error = _validar(data.get("fecha"), data.get("hora"), data.get("descripcion", ""),
                            data.get("monto_multa", 100.0))
    if error:
        return jsonify({"success": False, "error": error}), 400
    try:
        reunion, total = _crear(datos)
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "No se pudo crear la reunión. No se guardó nada."}), 500
    return jsonify({
        "success": True,
        "message": f"Reunión creada. Se procesaron {total} propietarios.",
        "reunion_id": reunion.id,
        "total_procesados": total,
    })


# ─────────────────────────── ACTUALIZAR ──────────────────────────────────────

@reunion_bp.route("/reuniones/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_reunion(id):
    reunion = Reunion.get_by_id(id)
    if not reunion:
        flash("Esa reunión ya no existe.", "error")
        return redirect(url_for("reunion.list_reuniones"))

    if request.method == "POST":
        datos, error = _validar(request.form.get("fecha"), request.form.get("hora"),
                                request.form.get("descripcion"), request.form.get("monto_multa"),
                                parcial=True)
        if error:
            flash(error, "error")
            return reunion_view.update_reunion(reunion)
        reunion.update(**datos)
        flash("Cambios guardados. Las multas ya emitidas conservan su monto original.", "success")
        return redirect(url_for("reunion.list_reuniones"))

    return reunion_view.update_reunion(reunion)


# ─────────────────────────── ELIMINAR ────────────────────────────────────────

@reunion_bp.route("/api/reuniones/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_reunion_ajax():
    data = request.get_json(silent=True) or {}
    reunion_id = data.get("reunion_id")
    if not isinstance(reunion_id, int):
        return jsonify({"success": False, "error": "ID de reunión es requerido."}), 400

    reunion = Reunion.get_by_id(reunion_id)
    if not reunion:
        return jsonify({"success": False, "error": f"Reunión {reunion_id} no encontrada."}), 404

    descripcion = reunion.descripcion or f"Reunión {reunion_id}"
    try:
        multas, asistencias = reunion.eliminar()
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "No se pudo eliminar la reunión. No se borró nada."}), 500

    return jsonify({
        "success": True,
        "message": f"Reunión '{descripcion}' eliminada.",
        "multas_eliminadas": multas,
        "asistencias_eliminadas": asistencias,
        "reunion_descripcion": descripcion,
    })


@reunion_bp.route("/reuniones/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_reunion(id):
    reunion = Reunion.get_by_id(id)
    if not reunion:
        flash("Esa reunión ya no existe.", "error")
        return redirect(url_for("reunion.list_reuniones"))
    try:
        multas, asistencias = reunion.eliminar()
        db.session.commit()
        flash(f"Reunión eliminada con {asistencias} asistencias y {multas} multas.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar la reunión. No se borró nada.", "error")
    return redirect(url_for("reunion.list_reuniones"))
