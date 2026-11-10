# controllers/asistencia_controller.py
# Asistencias: listado paginado con filtros (reunión, estado, búsqueda) y
# operaciones que mantienen sincronizada la multa de inasistencia.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import login_required
from sqlalchemy import case, func

from database import db
from models.asistencia_model import Asistencia
from models.duenio_model import Duenio
from models.reunion_model import Reunion
from utils.busqueda import filtro_por_palabras
from utils.decorators import role_required
from utils.http import es_url_interna
from utils.pagination import obtener_orden, obtener_paginacion, paginar
from views import asistencia_view

asistencia_bp = Blueprint("asistencia", __name__)

ORDEN_ASISTENCIAS = {
    "-fecha": [Reunion.fecha.desc(), Duenio.nombre.asc(), Asistencia.id.asc()],
    "fecha": [Reunion.fecha.asc(), Duenio.nombre.asc(), Asistencia.id.asc()],
    "propietario": [Duenio.nombre.asc(), Duenio.paterno.asc(), Asistencia.id.asc()],
    "-propietario": [Duenio.nombre.desc(), Duenio.paterno.desc(), Asistencia.id.asc()],
    "estado": [Asistencia.asistio.asc(), Duenio.nombre.asc(), Asistencia.id.asc()],
    "-estado": [Asistencia.asistio.desc(), Duenio.nombre.asc(), Asistencia.id.asc()],
}


def _leer_asistio(valor):
    return (valor or "").strip().lower() in ("true", "on", "1", "si", "sí")


def _mensaje(asistio, con_multa):
    if asistio:
        return "Asistencia registrada: presente.", "success"
    if con_multa:
        return "Asistencia registrada: ausente. Se aplicó la multa de la reunión.", "warning"
    return "Asistencia registrada: ausente. No corresponde multa.", "success"


def _destino(valor):
    """Vuelve a la página del listado de la que vino el usuario (con sus filtros)."""
    return valor if es_url_interna(valor) and valor.startswith("/asistencias") \
        else url_for("asistencia.list_asistencias")


@asistencia_bp.route("/asistencias")
@login_required
def list_asistencias():
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_ASISTENCIAS, "-fecha")
    reunion_id = request.args.get("reunion_id", type=int)
    estado = request.args.get("estado", "", type=str)

    query = (db.session.query(Asistencia)
             .join(Duenio, Duenio.id == Asistencia.duenio_id)
             .join(Reunion, Reunion.id == Asistencia.id_reunion))
    reunion = db.session.get(Reunion, reunion_id) if reunion_id else None
    if reunion:
        query = query.filter(Asistencia.id_reunion == reunion.id)
    filtro = filtro_por_palabras(search, [Duenio.nombre, Duenio.paterno, Duenio.materno,
                                          Duenio.ci, Reunion.descripcion])
    if filtro is not None:
        query = query.filter(filtro)

    # Estadísticas del conjunto filtrado (sin el filtro de estado), en una consulta.
    presentes, total, reuniones = query.with_entities(
        func.sum(case((Asistencia.asistio.is_(True), 1), else_=0)),
        func.count(Asistencia.id),
        func.count(func.distinct(Asistencia.id_reunion)),
    ).one()
    presentes, total = int(presentes or 0), int(total or 0)

    if estado == "presente":
        query = query.filter(Asistencia.asistio.is_(True))
    elif estado == "ausente":
        query = query.filter(Asistencia.asistio.is_(False))
    else:
        estado = ""

    pag = paginar(query.order_by(*clausulas), page, per_page)
    return asistencia_view.list_asistencias(pag, search, {
        "total_asistencias": total,
        "total_presentes": presentes,
        "total_ausentes": total - presentes,
        "reuniones_unicas": int(reuniones or 0),
    }, reunion=reunion, estado=estado, orden=orden)


@asistencia_bp.route("/asistencias/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_asistencia():
    """Registra (o corrige) la asistencia de un propietario a una reunión."""
    if request.method == "POST":
        duenio = db.session.get(Duenio, request.form.get("duenio_id", type=int) or 0)
        reunion = db.session.get(Reunion, request.form.get("id_reunion", type=int) or 0)
        asistio = _leer_asistio(request.form.get("asistio"))
        if not duenio or not reunion:
            flash("Elige un propietario y una reunión de las sugerencias.", "error")
            return asistencia_view.create_asistencia(reunion=reunion)

        try:
            asistencia = Asistencia.query.filter_by(duenio_id=duenio.id, id_reunion=reunion.id).first()
            if asistencia is None:
                asistencia = Asistencia(duenio_id=duenio.id, id_reunion=reunion.id)
                db.session.add(asistencia)
            con_multa = asistencia.marcar(asistio)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("No se pudo guardar la asistencia. No se modificó nada.", "error")
            return asistencia_view.create_asistencia(reunion=reunion)

        flash(*_mensaje(asistio, con_multa))
        return redirect(url_for("asistencia.list_asistencias", reunion_id=reunion.id))

    reunion = db.session.get(Reunion, request.args.get("reunion_id", type=int) or 0)
    return asistencia_view.create_asistencia(reunion=reunion)


@asistencia_bp.route("/asistencias/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_asistencia(id):
    asistencia = db.session.get(Asistencia, id)
    if not asistencia:
        flash("Ese registro de asistencia ya no existe.", "error")
        return redirect(url_for("asistencia.list_asistencias"))

    if request.method == "POST":
        asistio = _leer_asistio(request.form.get("asistio"))
        try:
            con_multa = asistencia.marcar(asistio)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("No se pudo guardar la asistencia. No se modificó nada.", "error")
            return asistencia_view.update_asistencia(asistencia)
        flash(*_mensaje(asistio, con_multa))
        return redirect(_destino(request.form.get("volver")))

    return asistencia_view.update_asistencia(asistencia)


@asistencia_bp.route("/asistencias/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_asistencia(id):
    asistencia = Asistencia.get_by_id(id)
    if not asistencia:
        flash("Ese registro de asistencia ya no existe.", "error")
        return redirect(url_for("asistencia.list_asistencias"))
    try:
        asistencia.eliminar()
        db.session.commit()
        flash("Registro de asistencia eliminado junto con su multa.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar la asistencia. No se borró nada.", "error")
    return redirect(_destino(request.form.get("volver")))


@asistencia_bp.route("/asistencias/marcar", methods=["POST"])
@login_required
@role_required("admin")
def marcar_asistencia():
    """Marca presente/ausente desde el listado (botón rápido de cada fila)."""
    asistencia = Asistencia.query.filter_by(
        duenio_id=request.form.get("duenio_id", type=int),
        id_reunion=request.form.get("id_reunion", type=int),
    ).first()
    destino = _destino(request.form.get("volver"))
    if not asistencia:
        flash("Ese registro de asistencia ya no existe.", "error")
        return redirect(destino)

    asistio = _leer_asistio(request.form.get("asistio"))
    try:
        con_multa = asistencia.marcar(asistio)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash("No se pudo guardar la asistencia. No se modificó nada.", "error")
        return redirect(destino)
    flash(*_mensaje(asistio, con_multa))
    return redirect(destino)
