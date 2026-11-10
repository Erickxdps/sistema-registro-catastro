# controllers/duenio_controller.py
# Propietarios: listado paginado con búsqueda por palabras y orden, y CRUD.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from database import db
from models.duenio_model import Duenio
from utils.busqueda import filtro_por_palabras
from utils.decorators import role_required
from utils.pagination import obtener_orden, obtener_paginacion, paginar
from utils.validators import validar_ci, validar_texto
from views import duenio_view

duenio_bp = Blueprint("duenio", __name__)

ORDEN_DUENIOS = {
    "nombre": [Duenio.nombre.asc(), Duenio.paterno.asc(), Duenio.id.asc()],
    "-nombre": [Duenio.nombre.desc(), Duenio.paterno.desc(), Duenio.id.desc()],
    "paterno": [Duenio.paterno.asc(), Duenio.nombre.asc(), Duenio.id.asc()],
    "-paterno": [Duenio.paterno.desc(), Duenio.nombre.desc(), Duenio.id.desc()],
    "ci": [Duenio.ci.asc()],
    "-ci": [Duenio.ci.desc()],
    "registro": [Duenio.id.asc()],
    "-registro": [Duenio.id.desc()],
}


def _leer_formulario():
    """Valida el formulario. Devuelve (datos, error)."""
    ok_nom, nombre, err_nom = validar_texto(request.form.get("nombre"), "El nombre", min_len=2, max_len=50)
    ok_pat, paterno, err_pat = validar_texto(request.form.get("paterno"), "El apellido paterno", min_len=0, max_len=50, requerido=False)
    ok_mat, materno, err_mat = validar_texto(request.form.get("materno"), "El apellido materno", min_len=0, max_len=50, requerido=False)
    ok_ci, ci, err_ci = validar_ci(request.form.get("ci"))
    for ok, err in ((ok_nom, err_nom), (ok_pat, err_pat), (ok_mat, err_mat), (ok_ci, err_ci)):
        if not ok:
            return None, err
    return {"nombre": nombre, "paterno": paterno or "", "materno": materno or "", "ci": ci}, None


@duenio_bp.route("/duenios")
@login_required
def list_duenios():
    """Lista paginada de propietarios con búsqueda por palabras (nombre, apellidos o CI)."""
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_DUENIOS, "nombre")

    query = Duenio.query
    filtro = filtro_por_palabras(search, [Duenio.nombre, Duenio.paterno, Duenio.materno, Duenio.ci])
    if filtro is not None:
        query = query.filter(filtro)

    pag = paginar(query.order_by(*clausulas), page, per_page)
    ids = [d.id for d in pag.items]
    return duenio_view.list_duenios(pag, search, orden,
                                    deudas=Duenio.deudas_por_propietario(ids),
                                    lotes=Duenio.terrenos_por_propietario(ids))


@duenio_bp.route("/duenios/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_duenio():
    if request.method == "POST":
        datos, error = _leer_formulario()
        if error:
            flash(error, "error")
            return duenio_view.create_duenio(form=request.form)
        try:
            duenio = Duenio(**datos)
            duenio.save()
            flash(f"Propietario {duenio.nombre_completo} registrado.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Ese CI ya está registrado para otro propietario. Revisa el número.", "error")
            return duenio_view.create_duenio(form=request.form)
        return redirect(url_for("duenio.list_duenios"))

    return duenio_view.create_duenio()


@duenio_bp.route("/duenios/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_duenio(id):
    duenio = db.session.get(Duenio, id)
    if not duenio:
        flash("Ese propietario ya no existe.", "error")
        return redirect(url_for("duenio.list_duenios"))

    if request.method == "POST":
        datos, error = _leer_formulario()
        if error:
            flash(error, "error")
            return duenio_view.update_duenio(duenio)
        try:
            duenio.update(**datos)
            flash("Cambios guardados.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Ese CI ya está en uso por otro propietario. Revisa el número.", "error")
            return duenio_view.update_duenio(duenio)
        return redirect(url_for("duenio.list_duenios"))

    return duenio_view.update_duenio(duenio)


@duenio_bp.route("/duenios/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_duenio(id):
    duenio = db.session.get(Duenio, id)
    if not duenio:
        flash("Ese propietario ya no existe.", "error")
        return redirect(url_for("duenio.list_duenios"))
    try:
        duenio.delete()
        flash("Propietario eliminado junto con sus terrenos, cuotas, multas y asistencias.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar el propietario. No se borró nada.", "error")
    return redirect(url_for("duenio.list_duenios"))
