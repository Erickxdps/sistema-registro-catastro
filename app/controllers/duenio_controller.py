# controllers/duenio_controller.py
# Controlador de propietarios — refactorizado para:
#   1. Eliminar los if/else de autorización duplicados.
#   2. Usar db.session.get() en vez del depreciado Query.get().
#   3. Añadir manejo de errores explícito con try/except.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from models.duenio_model import Duenio
from views import duenio_view
from utils.decorators import role_required
from utils.pagination import obtener_paginacion
from utils.validators import validar_texto, validar_ci
from database import db

duenio_bp = Blueprint("duenio", __name__)


# ─────────────────────────── LISTADO ─────────────────────────────────────────

@duenio_bp.route("/duenios")
@login_required
def list_duenios():
    """Lista paginada de propietarios con búsqueda por nombre, apellidos o CI."""
    page, per_page, search = obtener_paginacion(default_per_page=10)

    query = Duenio.query
    if search:
        filtro = f"%{search}%"
        query = query.filter(
            or_(
                Duenio.nombre.ilike(filtro),
                Duenio.paterno.ilike(filtro),
                Duenio.materno.ilike(filtro),
                Duenio.ci.ilike(filtro),
            )
        )

    duenios_paginated = query.order_by(Duenio.id).paginate(page=page, per_page=per_page, error_out=False)
    return duenio_view.list_duenios(duenios_paginated, search)


# ─────────────────────────── CREAR ───────────────────────────────────────────

@duenio_bp.route("/duenios/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_duenio():
    """Crea un nuevo propietario."""
    if request.method == "POST":
        ok_nom, nombre, err_nom = validar_texto(request.form.get("nombre"), "Nombre", min_len=2, max_len=50)
        ok_pat, paterno, _ = validar_texto(request.form.get("paterno"), "Apellido paterno", min_len=0, max_len=50, requerido=False)
        ok_mat, materno, _ = validar_texto(request.form.get("materno"), "Apellido materno", min_len=0, max_len=50, requerido=False)
        ok_ci, ci, err_ci = validar_ci(request.form.get("ci"))

        if not ok_nom:
            flash(err_nom, "error")
            return duenio_view.create_duenio()

        if not ok_ci:
            flash(err_ci, "error")
            return duenio_view.create_duenio()

        try:
            duenio = Duenio(nombre=nombre, paterno=paterno or "", materno=materno or "", ci=ci)
            duenio.save()
            flash("Propietario creado exitosamente.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("El CI ingresado ya está registrado para otro propietario.", "error")

        return redirect(url_for("duenio.list_duenios"))

    return duenio_view.create_duenio()


# ─────────────────────────── ACTUALIZAR ──────────────────────────────────────

@duenio_bp.route("/duenios/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_duenio(id):
    """Actualiza los datos de un propietario."""
    duenio = db.session.get(Duenio, id)
    if not duenio:
        flash("Propietario no encontrado.", "error")
        return redirect(url_for("duenio.list_duenios"))

    if request.method == "POST":
        ok_nom, nombre, err_nom = validar_texto(request.form.get("nombre"), "Nombre", min_len=2, max_len=50)
        ok_pat, paterno, _ = validar_texto(request.form.get("paterno"), "Apellido paterno", min_len=0, max_len=50, requerido=False)
        ok_mat, materno, _ = validar_texto(request.form.get("materno"), "Apellido materno", min_len=0, max_len=50, requerido=False)
        ok_ci, ci, err_ci = validar_ci(request.form.get("ci"))

        if not ok_nom:
            flash(err_nom, "error")
            return duenio_view.update_duenio(duenio)

        if not ok_ci:
            flash(err_ci, "error")
            return duenio_view.update_duenio(duenio)

        try:
            duenio.update(nombre=nombre, paterno=paterno or "", materno=materno or "", ci=ci)
            flash("Propietario actualizado exitosamente.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("El CI ingresado ya está en uso por otro propietario.", "error")

        return redirect(url_for("duenio.list_duenios"))

    return duenio_view.update_duenio(duenio)


# ─────────────────────────── ELIMINAR ────────────────────────────────────────

@duenio_bp.route("/duenios/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_duenio(id):
    """Elimina un propietario y todos sus registros dependientes."""
    duenio = db.session.get(Duenio, id)
    if not duenio:
        flash("Propietario no encontrado.", "error")
        return redirect(url_for("duenio.list_duenios"))

    try:
        duenio.delete()
        flash("Propietario eliminado exitosamente.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error al eliminar el propietario.", "error")

    return redirect(url_for("duenio.list_duenios"))
