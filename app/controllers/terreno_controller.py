# controllers/terreno_controller.py
# Controlador de terrenos — refactorizado para:
#   1. Eliminar los if/else de autorización duplicados.
#   2. Usar db.session.get() en vez del depreciado Query.get().
#   3. Añadir manejo de errores explícito con try/except.
#   4. Corregir el filtro de búsqueda: Terreno.manzano es Integer, no soporta ilike().
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import login_required
from sqlalchemy import or_, cast, String
from sqlalchemy.exc import IntegrityError

from models.terreno_model import Terreno
from models.duenio_model  import Duenio
from views import terreno_view
from utils.decorators import role_required
from database import db

terreno_bp = Blueprint("terreno", __name__)


# ─────────────────────────── LISTADO ─────────────────────────────────────────

@terreno_bp.route("/terrenos")
@login_required
def list_terrenos():
    """Lista paginada de terrenos con búsqueda por lugar, manzano o propietario."""
    page     = request.args.get('page',     1,  type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search   = request.args.get('search',   '', type=str)

    # JOIN con Duenio para permitir búsqueda por atributos del propietario
    query = db.session.query(Terreno).join(Duenio)

    if search:
        filtro = f"%{search}%"
        query = query.filter(
            or_(
                Terreno.lugar.ilike(filtro),
                # manzano es Integer: cast a String para poder usar ilike
                cast(Terreno.manzano, String).ilike(filtro),
                Duenio.nombre.ilike(filtro),
                Duenio.paterno.ilike(filtro),
                Duenio.materno.ilike(filtro),
                Duenio.ci.ilike(filtro),
            )
        )

    terrenos_paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    return terreno_view.list_terrenos(terrenos_paginated, search)


# ─────────────────────────── CREAR ───────────────────────────────────────────

@terreno_bp.route("/terrenos/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_terreno():
    """Crea un nuevo terreno asociado a un propietario."""
    if request.method == "POST":
        duenio_id       = request.form.get("duenio_id",       type=int)
        lugar           = request.form.get("lugar",           "").strip()
        manzano         = request.form.get("manzano",         type=int)
        metros_cuadrados = request.form.get("metros_cuadrados", type=float)

        if not duenio_id or not lugar or manzano is None or metros_cuadrados is None:
            flash("Todos los campos son obligatorios.", "error")
            duenios = Duenio.query.all()
            return render_template('create_terreno.html', duenios=duenios)

        try:
            terreno = Terreno(
                duenio_id=duenio_id,
                lugar=lugar,
                manzano=manzano,
                metros_cuadrados=metros_cuadrados,
            )
            terreno.save()
            flash("Terreno creado exitosamente.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("Error al guardar el terreno. Verifica los datos.", "error")

        return redirect(url_for("terreno.list_terrenos"))

    duenios = Duenio.query.all()
    return render_template('create_terreno.html', duenios=duenios)


# ─────────────────────────── ACTUALIZAR ──────────────────────────────────────

@terreno_bp.route("/terrenos/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_terreno(id):
    """Actualiza los datos de un terreno."""
    terreno = db.session.get(Terreno, id)
    if not terreno:
        flash("Terreno no encontrado.", "error")
        return redirect(url_for("terreno.list_terrenos"))

    if request.method == "POST":
        duenio_id        = request.form.get("duenio_id",       type=int)
        lugar            = request.form.get("lugar",            "").strip()
        manzano          = request.form.get("manzano",          type=int)
        metros_cuadrados = request.form.get("metros_cuadrados", type=float)

        try:
            terreno.update(
                duenio_id=duenio_id,
                lugar=lugar,
                manzano=manzano,
                metros_cuadrados=metros_cuadrados,
            )
            flash("Terreno actualizado exitosamente.", "success")
        except Exception:
            db.session.rollback()
            flash("Error al actualizar el terreno.", "error")

        return redirect(url_for("terreno.list_terrenos"))

    duenios = Duenio.query.all()
    return render_template('update_terreno.html', terreno=terreno, duenios=duenios)


# ─────────────────────────── ELIMINAR ────────────────────────────────────────

@terreno_bp.route("/terrenos/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_terreno(id):
    """Elimina un terreno y sus cuotas y multas dependientes."""
    terreno = db.session.get(Terreno, id)
    if not terreno:
        flash("Terreno no encontrado.", "error")
        return redirect(url_for("terreno.list_terrenos"))

    try:
        terreno.delete()
        flash("Terreno eliminado exitosamente.", "success")
    except Exception:
        db.session.rollback()
        flash("Error al eliminar el terreno.", "error")

    return redirect(url_for("terreno.list_terrenos"))
