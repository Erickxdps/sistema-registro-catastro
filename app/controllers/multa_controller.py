# controllers/multa_controller.py
# Multas: listado paginado con filtros, resumen de deuda y operaciones.
#
# Reglas (ver models/multa_model.py):
#   - Las multas "reflejo" de una cuota pendiente no suman a la deuda y no se
#     editan ni borran a mano: se gestionan pagando o editando la cuota.
#   - "Regularizar" a un propietario elimina sus multas reales (inasistencia y
#     manuales). Sus cuotas pendientes siguen pendientes hasta que se paguen.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import func

from database import db
from models.duenio_model import Duenio
from models.multa_model import Multa
from utils.busqueda import filtro_por_palabras
from utils.decorators import role_required
from utils.pagination import obtener_orden, obtener_paginacion, paginar
from utils.validators import validar_monto, validar_texto, validar_tipo_multa
from views import multa_view

multa_bp = Blueprint("multa", __name__)

ORDEN_MULTAS = {
    "-fecha": [Multa.fecha.desc(), Multa.multa_id.desc()],
    "fecha": [Multa.fecha.asc(), Multa.multa_id.asc()],
    "propietario": [Duenio.nombre.asc(), Duenio.paterno.asc(), Multa.multa_id.asc()],
    "-propietario": [Duenio.nombre.desc(), Duenio.paterno.desc(), Multa.multa_id.asc()],
    "monto": [Multa.monto.asc(), Multa.multa_id.asc()],
    "-monto": [Multa.monto.desc(), Multa.multa_id.asc()],
}

TIPOS_FILTRO = {
    "asistencia": lambda q: q.filter(Multa.tipo == "asistencia"),
    "cuota": lambda q: q.filter(Multa.tipo == "cuota", Multa.cuota_id.isnot(None)),
    "manual": lambda q: q.filter(Multa.cuota_id.is_(None), Multa.reunion_id.is_(None)),
}


def _resumen():
    """Totales globales en una consulta: lo que suma a la deuda y los reflejos aparte."""
    suma = Multa.filtro_suma_a_deuda()
    reales_n, reales_m = db.session.query(func.count(Multa.multa_id), func.coalesce(func.sum(Multa.monto), 0)) \
        .filter(suma).one()
    reflejos_n, reflejos_m = db.session.query(func.count(Multa.multa_id), func.coalesce(func.sum(Multa.monto), 0)) \
        .filter(~suma).one()
    sancionados = db.session.query(func.count(func.distinct(Multa.duenio_id))).filter(suma).scalar() or 0
    return {"reales": int(reales_n), "monto_reales": float(reales_m), "reflejos": int(reflejos_n),
            "monto_reflejos": float(reflejos_m), "sancionados": int(sancionados)}


@multa_bp.route("/multas")
@login_required
def list_multas():
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_MULTAS, "-fecha")
    tipo = request.args.get("tipo", "", type=str)

    query = db.session.query(Multa).join(Duenio, Duenio.id == Multa.duenio_id)
    if tipo in TIPOS_FILTRO:
        query = TIPOS_FILTRO[tipo](query)
    else:
        tipo = ""
    filtro = filtro_por_palabras(search, [Duenio.nombre, Duenio.paterno, Duenio.materno,
                                          Duenio.ci, Multa.descripcion])
    if filtro is not None:
        query = query.filter(filtro)

    pag = paginar(query.order_by(*clausulas), page, per_page)
    return multa_view.list_multas(pag, _resumen(), search, tipo, orden)


def _leer_formulario(multa=None):
    """Valida el formulario de multa. Devuelve (datos, error)."""
    duenio = db.session.get(Duenio, request.form.get("duenio_id", type=int) or 0)
    if not duenio:
        return None, "Elige un propietario de la lista de sugerencias."
    if duenio.es_immune:
        return None, f"{duenio.nombre_completo} está exento de multas."
    ok_monto, monto, err_monto = validar_monto(request.form.get("monto"), "El monto de la multa", min_val=1.0)
    if not ok_monto:
        return None, err_monto
    ok_tipo, tipo, err_tipo = validar_tipo_multa(request.form.get("tipo"))
    if not ok_tipo:
        return None, err_tipo
    ok_desc, descripcion, err_desc = validar_texto(request.form.get("descripcion"), "La descripción",
                                                   min_len=0, max_len=500, requerido=False)
    if not ok_desc:
        return None, err_desc
    return {"duenio_id": duenio.id, "monto": monto, "tipo": tipo, "descripcion": descripcion or ""}, None


@multa_bp.route("/multas/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_multa():
    if request.method == "POST":
        datos, error = _leer_formulario()
        if error:
            flash(error, "error")
            return multa_view.create_multa(form=request.form,
                                           duenio=db.session.get(Duenio, request.form.get("duenio_id", type=int) or 0))
        try:
            Multa(**datos).save()
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return multa_view.create_multa(form=request.form)
        flash("Multa registrada.", "success")
        return redirect(url_for("multa.list_multas"))

    return multa_view.create_multa(duenio=db.session.get(Duenio, request.args.get("duenio_id", type=int) or 0))


def _bloquear_reflejo(multa):
    if multa.es_reflejo_cuota:
        flash("Esta multa refleja una cuota pendiente. Para cambiarla, paga o edita la cuota.", "error")
        return redirect(url_for("cuota.update_cuota", cuota_id=multa.cuota_id))
    return None


@multa_bp.route("/multas/<int:multa_id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_multa(multa_id):
    multa = Multa.get_by_id(multa_id)
    if not multa:
        flash("Esa multa ya no existe.", "error")
        return redirect(url_for("multa.list_multas"))
    bloqueo = _bloquear_reflejo(multa)
    if bloqueo:
        return bloqueo

    if request.method == "POST":
        datos, error = _leer_formulario(multa)
        if error:
            flash(error, "error")
            return multa_view.update_multa(multa)
        try:
            multa.update(**datos)
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
            return multa_view.update_multa(multa)
        flash("Cambios guardados.", "success")
        return redirect(url_for("multa.list_multas"))

    return multa_view.update_multa(multa)


@multa_bp.route("/multas/<int:multa_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_multa(multa_id):
    multa = Multa.get_by_id(multa_id)
    if not multa:
        flash("Esa multa ya no existe.", "error")
        return redirect(url_for("multa.list_multas"))
    bloqueo = _bloquear_reflejo(multa)
    if bloqueo:
        return bloqueo
    try:
        multa.delete()
        flash("Multa eliminada.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar la multa.", "error")
    return redirect(url_for("multa.list_multas"))


@multa_bp.route("/multas/duenio/<int:duenio_id>")
@login_required
def multas_por_duenio(duenio_id):
    duenio = db.session.get(Duenio, duenio_id)
    if not duenio:
        flash("Ese propietario ya no existe.", "error")
        return redirect(url_for("multa.list_multas"))
    multas = Multa.get_by_duenio(duenio_id)
    deuda = Duenio.deudas_por_propietario([duenio_id])[duenio_id]
    return multa_view.multas_por_duenio(duenio, multas, deuda)


@multa_bp.route("/multas/tipo/<tipo>")
@login_required
def multas_por_tipo(tipo):
    """Atajo conservado: lleva al listado filtrado por tipo."""
    if tipo not in ("cuota", "asistencia"):
        return "Tipo de multa inválido.", 400
    return redirect(url_for("multa.list_multas", tipo=tipo))


@multa_bp.route("/multas/duenio/<int:duenio_id>/eliminar_todas", methods=["POST"])
@login_required
@role_required("admin")
def eliminar_multas_duenio(duenio_id):
    """Regulariza al propietario: elimina sus multas reales (no los reflejos)."""
    try:
        eliminadas = (Multa.query.filter(Multa.duenio_id == duenio_id, Multa.filtro_suma_a_deuda())
                      .delete(synchronize_session=False))
        db.session.commit()
        flash(f"Se regularizaron {eliminadas} multas. Las cuotas pendientes se pagan desde Cuotas.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudieron eliminar las multas. No se borró nada.", "error")
    return redirect(url_for("multa.multas_por_duenio", duenio_id=duenio_id))
