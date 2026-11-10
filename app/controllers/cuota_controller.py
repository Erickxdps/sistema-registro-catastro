# controllers/cuota_controller.py
# Cuotas: emisiones agregadas + detalle paginado, y todas las operaciones.
#
# Regla (decisión del negocio): la cuota pendiente ES la deuda; su multa de
# tipo 'cuota' es un reflejo sincronizado que no se suma otra vez.
# Todas las rutas que cambian el estado de pago pasan por Cuota.marcar_pago(),
# así ninguna puede dejar el reflejo desincronizado.
#
# Rutas y contratos JSON conservados (los usa la interfaz o pueden usarlos otros):
#   POST /api/cuotas/create                 → {success, message, total_cuotas}
#   POST /cuotas/<id>/toggle-payment        → {success, message, pagado}
#   POST /cuotas/<id>/toggle-status  (JSON) → {success, message, nuevo_estado}
#   DELETE /cuotas/<id>                     → {success, message}
#   POST /api/cuotas/delete-by-title        → {success, message, total_eliminadas, propietarios_afectados}

from flask import Blueprint, flash, jsonify, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import func

from database import db
from models.cuota_model import Cuota
from models.duenio_model import Duenio
from models.terreno_model import Terreno
from utils.busqueda import filtro_por_palabras
from utils.decorators import role_required
from utils.pagination import obtener_orden, obtener_paginacion, paginar
from utils.validators import validar_monto, validar_texto
from views import cuota_view

cuota_bp = Blueprint("cuota", __name__)

ORDEN_CUOTAS = {
    "terreno": [Terreno.manzano.asc(), Terreno.lugar.asc(), Cuota.cuota_id.asc()],
    "-terreno": [Terreno.manzano.desc(), Terreno.lugar.desc(), Cuota.cuota_id.asc()],
    "propietario": [Duenio.nombre.asc(), Duenio.paterno.asc(), Cuota.cuota_id.asc()],
    "-propietario": [Duenio.nombre.desc(), Duenio.paterno.desc(), Cuota.cuota_id.asc()],
    "monto": [Cuota.monto.asc(), Cuota.cuota_id.asc()],
    "-monto": [Cuota.monto.desc(), Cuota.cuota_id.asc()],
    "estado": [Cuota.pagado.asc(), Cuota.cuota_id.asc()],
    "-estado": [Cuota.pagado.desc(), Cuota.cuota_id.asc()],
    "-fecha": [Cuota.fecha_creacion.desc(), Cuota.cuota_id.desc()],
}


def _validar_emision(titulo_raw, monto_raw, descripcion_raw):
    ok_tit, titulo, err_tit = validar_texto(titulo_raw, "El título de la cuota", min_len=3, max_len=150)
    if not ok_tit:
        return None, err_tit
    ok_desc, descripcion, err_desc = validar_texto(descripcion_raw, "La descripción", min_len=0, max_len=500, requerido=False)
    if not ok_desc:
        return None, err_desc
    ok_monto, monto, err_monto = validar_monto(monto_raw, "El monto por terreno", min_val=0.5)
    if not ok_monto:
        return None, err_monto
    if Cuota.query.filter_by(titulo=titulo).first():
        return None, f"Ya existe una emisión llamada '{titulo}'. Usa otro título para no mezclarlas."
    return {"titulo": titulo, "monto": monto, "descripcion": descripcion or ""}, None


# ─────────────────────────── LISTADO ─────────────────────────────────────────

@cuota_bp.route("/cuotas")
@login_required
def list_cuotas():
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_CUOTAS, "terreno")
    titulo = (request.args.get("titulo", "", type=str) or "").strip()[:255]
    estado = request.args.get("estado", "", type=str)

    query = (db.session.query(Cuota)
             .join(Terreno, Terreno.id == Cuota.terreno_id)
             .join(Duenio, Duenio.id == Terreno.duenio_id))
    if titulo:
        query = query.filter(Cuota.titulo == titulo)
    if estado == "pagada":
        query = query.filter(Cuota.pagado.is_(True))
    elif estado == "pendiente":
        query = query.filter(Cuota.pagado.is_(False))
    else:
        estado = ""
    filtro = filtro_por_palabras(search, [Duenio.nombre, Duenio.paterno, Duenio.materno,
                                          Duenio.ci, Terreno.lugar, Terreno.manzano])
    if filtro is not None:
        query = query.filter(filtro)

    pag = paginar(query.order_by(*clausulas), page, per_page)
    return cuota_view.list_cuotas(Cuota.resumen_emisiones(), pag, search, titulo, estado, orden)


@cuota_bp.route("/cuotas/pendientes")
@login_required
def cuotas_pendientes():
    """Atajo conservado: lleva al listado filtrado por cuotas pendientes."""
    return redirect(url_for("cuota.list_cuotas", estado="pendiente"))


# ─────────────────────────── EMITIR ──────────────────────────────────────────

@cuota_bp.route("/cuotas/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_cuota():
    """Formulario clásico (sin JavaScript). La interfaz usa /api/cuotas/create."""
    if request.method == "POST":
        datos, error = _validar_emision(request.form.get("titulo"), request.form.get("monto"),
                                        request.form.get("descripcion"))
        if error:
            flash(error, "error")
            return cuota_view.create_cuota(Terreno.query.count())
        try:
            creadas = Cuota.emitir_para_todos(**datos)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("No se pudo emitir la cuota. No se guardó nada.", "error")
            return cuota_view.create_cuota(Terreno.query.count())
        flash(f"Cuota emitida a {creadas} terrenos.", "success")
        return redirect(url_for("cuota.list_cuotas", titulo=datos["titulo"]))

    return cuota_view.create_cuota(Terreno.query.count())


@cuota_bp.route("/api/cuotas/create", methods=["POST"])
@login_required
@role_required("admin")
def create_cuota_ajax():
    data = request.get_json(silent=True) or {}
    datos, error = _validar_emision(data.get("titulo"), data.get("monto"), data.get("descripcion"))
    if error:
        return jsonify({"success": False, "error": error}), 400
    try:
        creadas = Cuota.emitir_para_todos(**datos)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "No se pudo emitir la cuota. No se guardó nada."}), 500
    return jsonify({
        "success": True,
        "message": f"Cuota emitida a {creadas} terrenos.",
        "total_cuotas": creadas,
    })


# ─────────────────────────── EDITAR / PAGOS ──────────────────────────────────

@cuota_bp.route("/cuotas/<int:cuota_id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_cuota(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        flash("Esa cuota ya no existe.", "error")
        return redirect(url_for("cuota.list_cuotas"))

    if request.method == "POST":
        ok_tit, titulo, err_tit = validar_texto(request.form.get("titulo"), "El título", min_len=3, max_len=150)
        ok_desc, descripcion, err_desc = validar_texto(request.form.get("descripcion"), "La descripción",
                                                       min_len=0, max_len=500, requerido=False)
        ok_monto, monto, err_monto = validar_monto(request.form.get("monto"), "El monto", min_val=0.5)
        terreno = db.session.get(Terreno, request.form.get("terreno_id", type=int) or 0)
        error = (err_tit if not ok_tit else err_desc if not ok_desc else err_monto if not ok_monto
                 else None if terreno else "Elige un terreno de las sugerencias.")
        if error:
            flash(error, "error")
            return cuota_view.update_cuota(cuota)
        try:
            cuota.update(titulo=titulo, descripcion=descripcion or "", terreno_id=terreno.id, monto=monto,
                         pagado=_leer_bool(request.form.get("pagado")))
        except Exception:
            db.session.rollback()
            flash("No se pudieron guardar los cambios. No se modificó nada.", "error")
            return cuota_view.update_cuota(cuota)
        flash("Cambios guardados.", "success")
        return redirect(url_for("cuota.list_cuotas", titulo=cuota.titulo))

    return cuota_view.update_cuota(cuota)


def _leer_bool(valor):
    if isinstance(valor, bool):
        return valor
    return str(valor or "").strip().lower() in ("on", "true", "1", "si", "sí")


def _cambiar_pago(cuota, pagado):
    cuota.marcar_pago(pagado)
    db.session.commit()


@cuota_bp.route("/cuotas/<int:cuota_id>/toggle-payment", methods=["POST"])
@login_required
@role_required("admin")
def toggle_payment(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        return jsonify({"success": False, "message": "Cuota no encontrada"}), 404
    try:
        _cambiar_pago(cuota, not cuota.pagado)
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "No se pudo cambiar el estado de pago."}), 500
    return jsonify({
        "success": True,
        "message": f"Cuota marcada como {'pagada' if cuota.pagado else 'pendiente'}",
        "pagado": cuota.pagado,
    })


@cuota_bp.route("/cuotas/<int:cuota_id>/pagar", methods=["POST"])
@login_required
@role_required("admin")
def pagar_cuota(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        flash("Esa cuota ya no existe.", "error")
        return redirect(url_for("cuota.list_cuotas"))
    try:
        _cambiar_pago(cuota, True)
        flash("Cuota marcada como pagada.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo registrar el pago.", "error")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url)
                    else url_for("cuota.list_cuotas"))


@cuota_bp.route("/cuotas/<int:cuota_id>/toggle-status", methods=["POST"])
@login_required
@role_required("admin")
def toggle_cuota_status(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        return jsonify({"success": False, "message": "Cuota no encontrada"}), 404
    data = request.get_json(silent=True) or {}
    nuevo_estado = _leer_bool(data.get("pagado", False))
    try:
        _cambiar_pago(cuota, nuevo_estado)
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "No se pudo cambiar el estado de pago."}), 500
    mensaje = "pagada" if nuevo_estado else "marcada como pendiente"
    return jsonify({"success": True, "message": f"Cuota {mensaje} exitosamente", "nuevo_estado": nuevo_estado})


# ─────────────────────────── ELIMINAR ────────────────────────────────────────

@cuota_bp.route("/cuotas/<int:cuota_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_cuota(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        flash("Esa cuota ya no existe.", "error")
        return redirect(url_for("cuota.list_cuotas"))
    try:
        cuota.delete()
        flash("Cuota eliminada.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar la cuota. No se borró nada.", "error")
    return redirect(url_for("cuota.list_cuotas"))


@cuota_bp.route("/cuotas/<int:cuota_id>", methods=["DELETE"])
@login_required
@role_required("admin")
def delete_cuota_single(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        return jsonify({"success": False, "message": "Cuota no encontrada"}), 404
    titulo = cuota.titulo
    try:
        cuota.delete()
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "message": "No se pudo eliminar la cuota."}), 500
    return jsonify({"success": True, "message": f"Cuota '{titulo}' eliminada exitosamente"})


@cuota_bp.route("/cuotas/delete-by-owner/<int:dueno_id>", methods=["POST"])
@login_required
@role_required("admin")
def delete_cuotas_by_owner(dueno_id):
    try:
        cuotas = Cuota.query.join(Terreno).filter(Terreno.duenio_id == dueno_id).all()
        for cuota in cuotas:
            cuota.eliminar()
        db.session.commit()
        flash(f"Se eliminaron {len(cuotas)} cuotas del propietario.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudieron eliminar las cuotas. No se borró nada.", "error")
    return redirect(url_for("cuota.list_cuotas"))


def _propietarios_de_emision(titulo):
    return (db.session.query(func.count(func.distinct(Terreno.duenio_id)))
            .join(Cuota, Cuota.terreno_id == Terreno.id).filter(Cuota.titulo == titulo).scalar() or 0)


@cuota_bp.route("/api/cuotas/delete-by-title", methods=["POST"])
@login_required
@role_required("admin")
def delete_cuotas_by_title_ajax():
    data = request.get_json(silent=True) or {}
    titulo = (data.get("titulo") or "").strip()
    if not titulo:
        return jsonify({"success": False, "error": "Título es requerido"}), 400
    if not Cuota.query.filter_by(titulo=titulo).first():
        return jsonify({"success": False, "error": f"No se encontraron cuotas con el título '{titulo}'"}), 404
    afectados = _propietarios_de_emision(titulo)
    try:
        eliminadas = Cuota.eliminar_por_titulo(titulo)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "No se pudo eliminar la emisión. No se borró nada."}), 500
    return jsonify({
        "success": True,
        "message": f"Se eliminaron {eliminadas} cuotas de '{titulo}'.",
        "total_eliminadas": eliminadas,
        "propietarios_afectados": afectados,
    })


@cuota_bp.route("/cuotas/delete-by-title/<string:titulo>", methods=["POST"])
@login_required
@role_required("admin")
def delete_cuotas_by_title(titulo):
    afectados = _propietarios_de_emision(titulo)
    try:
        eliminadas = Cuota.eliminar_por_titulo(titulo)
        db.session.commit()
        flash(f"Se eliminaron {eliminadas} cuotas de '{titulo}' ({afectados} propietarios).", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar la emisión. No se borró nada.", "error")
    return redirect(url_for("cuota.list_cuotas"))
