# controllers/terreno_controller.py
# Terrenos: listado paginado (búsqueda, filtro por manzano y orden) y CRUD.
# El propietario se elige con el buscador (campo oculto `duenio_id`).

from flask import Blueprint, flash, redirect, request, url_for
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from database import db
from models.duenio_model import Duenio
from models.terreno_model import Terreno
from utils.busqueda import filtro_por_palabras
from utils.decorators import role_required
from utils.pagination import obtener_orden, obtener_paginacion, paginar
from views import terreno_view

terreno_bp = Blueprint("terreno", __name__)

ORDEN_TERRENOS = {
    "manzano": [Terreno.manzano.asc(), Terreno.lugar.asc(), Terreno.id.asc()],
    "-manzano": [Terreno.manzano.desc(), Terreno.lugar.asc(), Terreno.id.asc()],
    "lote": [Terreno.lugar.asc(), Terreno.manzano.asc(), Terreno.id.asc()],
    "-lote": [Terreno.lugar.desc(), Terreno.manzano.asc(), Terreno.id.asc()],
    "superficie": [Terreno.metros_cuadrados.asc(), Terreno.id.asc()],
    "-superficie": [Terreno.metros_cuadrados.desc(), Terreno.id.asc()],
    "propietario": [Duenio.nombre.asc(), Duenio.paterno.asc(), Terreno.id.asc()],
    "-propietario": [Duenio.nombre.desc(), Duenio.paterno.desc(), Terreno.id.asc()],
}


def _leer_formulario():
    """Valida el formulario. Devuelve (datos, error)."""
    duenio_id = request.form.get("duenio_id", type=int)
    lugar = (request.form.get("lugar") or "").strip()
    manzano = request.form.get("manzano", type=int)
    metros = request.form.get("metros_cuadrados", type=float)

    if not duenio_id or not db.session.get(Duenio, duenio_id):
        return None, "Elige un propietario de la lista de sugerencias."
    if not lugar or len(lugar) > 100:
        return None, "Escribe el número o nombre del lote (máximo 100 caracteres)."
    if manzano is None or manzano < 0:
        return None, "El manzano debe ser un número entero positivo."
    if metros is None or metros <= 0 or metros > 10_000_000:
        return None, "La superficie debe ser un número mayor que cero."
    return {"duenio_id": duenio_id, "lugar": lugar, "manzano": manzano,
            "metros_cuadrados": round(metros, 2)}, None


@terreno_bp.route("/terrenos")
@login_required
def list_terrenos():
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_TERRENOS, "manzano")
    manzano = request.args.get("manzano", type=int)

    query = db.session.query(Terreno).join(Duenio, Duenio.id == Terreno.duenio_id)
    if manzano is not None:
        query = query.filter(Terreno.manzano == manzano)
    filtro = filtro_por_palabras(search, [Terreno.lugar, Terreno.manzano, Duenio.nombre,
                                          Duenio.paterno, Duenio.materno, Duenio.ci])
    if filtro is not None:
        query = query.filter(filtro)

    pag = paginar(query.order_by(*clausulas), page, per_page)
    return terreno_view.list_terrenos(pag, search, orden, manzano)


@terreno_bp.route("/terrenos/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_terreno():
    if request.method == "POST":
        datos, error = _leer_formulario()
        if error:
            flash(error, "error")
            duenio = db.session.get(Duenio, request.form.get("duenio_id", type=int) or 0)
            return terreno_view.create_terreno(form=request.form, duenio=duenio)
        try:
            Terreno(**datos).save()
            flash(f"Lote {datos['lugar']} del manzano {datos['manzano']} registrado.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("No se pudo guardar el terreno. Revisa los datos.", "error")
            return terreno_view.create_terreno(form=request.form)
        return redirect(url_for("terreno.list_terrenos"))

    duenio = db.session.get(Duenio, request.args.get("duenio_id", type=int) or 0)
    return terreno_view.create_terreno(duenio=duenio)


@terreno_bp.route("/terrenos/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_terreno(id):
    terreno = db.session.get(Terreno, id)
    if not terreno:
        flash("Ese terreno ya no existe.", "error")
        return redirect(url_for("terreno.list_terrenos"))

    if request.method == "POST":
        datos, error = _leer_formulario()
        if error:
            flash(error, "error")
            return terreno_view.update_terreno(terreno)
        try:
            terreno.update(**datos)
            flash("Cambios guardados.", "success")
        except Exception:
            db.session.rollback()
            flash("No se pudieron guardar los cambios. No se modificó nada.", "error")
        return redirect(url_for("terreno.list_terrenos"))

    return terreno_view.update_terreno(terreno)


@terreno_bp.route("/terrenos/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_terreno(id):
    terreno = db.session.get(Terreno, id)
    if not terreno:
        flash("Ese terreno ya no existe.", "error")
        return redirect(url_for("terreno.list_terrenos"))
    try:
        terreno.delete()
        flash("Terreno eliminado junto con sus cuotas.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar el terreno. No se borró nada.", "error")
    return redirect(url_for("terreno.list_terrenos"))
