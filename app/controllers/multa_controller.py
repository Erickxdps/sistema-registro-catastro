# controllers/multa_controller.py
# Controlador de multas — refactorizado para:
#   1. Eliminar la función es_dueno_inmune() con ID hardcodeado.
#      La lógica ahora vive en Duenio.es_immune (propiedad del modelo).
#   2. Eliminar los if/else de autorización redundantes (ya cubiertos por decoradores).
#   3. Estandarizar manejo de errores.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, request, redirect, url_for, flash, jsonify, render_template
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from models.multa_model  import Multa
from models.duenio_model import Duenio
from views import multa_view
from utils.decorators import role_required
from utils.validators import validar_monto, validar_tipo_multa, validar_texto
from database import db

multa_bp = Blueprint("multa", __name__)


# ─────────────────────────── LISTADO ─────────────────────────────────────────

@multa_bp.route("/multas")
@login_required
def list_multas():
    """Lista todas las multas registradas."""
    multas = Multa.get_all()
    return multa_view.list_multas(multas)


# ─────────────────────────── CREAR ───────────────────────────────────────────

@multa_bp.route("/multas/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_multa():
    """Crea una nueva multa manualmente."""
    if request.method == "POST":
        duenio_id = request.form.get("duenio_id", type=int)
        ok_monto, monto, err_monto = validar_monto(request.form.get("monto"), "Monto de la multa", min_val=1.0)
        ok_tipo, tipo, err_tipo = validar_tipo_multa(request.form.get("tipo"))
        ok_desc, descripcion, _ = validar_texto(request.form.get("descripcion"), "Descripción", min_len=0, max_len=500, requerido=False)

        if not duenio_id:
            flash("Debes seleccionar un propietario.", "error")
            duenios = Duenio.query.all()
            return render_template('create_multa.html', duenios=duenios)

        if not ok_monto:
            flash(err_monto, "error")
            duenios = Duenio.query.all()
            return render_template('create_multa.html', duenios=duenios)

        if not ok_tipo:
            flash(err_tipo, "error")
            duenios = Duenio.query.all()
            return render_template('create_multa.html', duenios=duenios)

        # Verificar inmunidad a través de la propiedad del modelo
        duenio = db.session.get(Duenio, duenio_id)
        if not duenio:
            flash("Propietario no encontrado.", "error")
            return redirect(url_for("multa.list_multas"))

        if duenio.es_immune:
            flash(f"No se puede multar a '{duenio.nombre_completo}'. Entidad con inmunidad.", "error")
            duenios = Duenio.query.all()
            return render_template('create_multa.html', duenios=duenios)

        try:
            multa = Multa(
                duenio_id=duenio_id,
                monto=monto,
                tipo=tipo,
                descripcion=descripcion or "",
            )
            multa.save()
            flash("Multa creada exitosamente.", "success")
            return redirect(url_for("multa.list_multas"))
        except (ValueError, IntegrityError) as e:
            db.session.rollback()
            flash(f"Error al crear la multa: {e}", "error")

    duenios = Duenio.query.all()
    return render_template('create_multa.html', duenios=duenios)


# ─────────────────────────── ACTUALIZAR ──────────────────────────────────────

@multa_bp.route("/multas/<int:multa_id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_multa(multa_id):
    """Actualiza una multa existente."""
    multa = Multa.get_by_id(multa_id)
    if not multa:
        flash("Multa no encontrada.", "error")
        return redirect(url_for("multa.list_multas"))

    if request.method == "POST":
        duenio_id   = request.form.get("duenio_id",  type=int)    or multa.duenio_id
        monto       = request.form.get("monto",      type=float)  or multa.monto
        tipo        = request.form.get("tipo",        multa.tipo)
        descripcion = request.form.get("descripcion", multa.descripcion)

        try:
            multa.update(
                duenio_id=duenio_id,
                monto=monto,
                tipo=tipo,
                descripcion=descripcion,
            )
            flash("Multa actualizada exitosamente.", "success")
            return redirect(url_for("multa.list_multas"))
        except (ValueError, IntegrityError) as e:
            db.session.rollback()
            flash(f"Error al actualizar la multa: {e}", "error")

    duenios = Duenio.query.all()
    return render_template('update_multa.html', multa=multa, duenios=duenios)


# ─────────────────────────── ELIMINAR ────────────────────────────────────────

@multa_bp.route("/multas/<int:multa_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_multa(multa_id):
    """Elimina una multa por ID."""
    multa = Multa.get_by_id(multa_id)
    if not multa:
        flash("Multa no encontrada.", "error")
        return redirect(url_for("multa.list_multas"))

    try:
        multa.delete()
        flash("Multa eliminada exitosamente.", "success")
    except Exception:
        db.session.rollback()
        flash("Error al eliminar la multa.", "error")

    return redirect(url_for("multa.list_multas"))


# ─────────────────────────── FILTROS ─────────────────────────────────────────

@multa_bp.route("/multas/duenio/<int:duenio_id>")
@login_required
def multas_por_duenio(duenio_id):
    """Muestra las multas de un propietario específico."""
    multas  = Multa.get_by_duenio(duenio_id)
    duenio  = db.session.get(Duenio, duenio_id)
    return multa_view.multas_por_duenio(multas, duenio)


@multa_bp.route("/multas/tipo/<tipo>")
@login_required
def multas_por_tipo(tipo):
    """Muestra las multas filtradas por tipo."""
    if tipo not in ('cuota', 'asistencia'):
        return "Tipo de multa inválido.", 400
    multas = Multa.get_by_tipo(tipo)
    return multa_view.multas_por_tipo(multas, tipo)


@multa_bp.route("/multas/duenio/<int:duenio_id>/eliminar_todas", methods=["POST"])
@login_required
@role_required("admin")
def eliminar_multas_duenio(duenio_id):
    """Elimina todas las multas de un propietario (cuando regulariza su situación)."""
    multas = Multa.get_by_duenio(duenio_id)
    try:
        for multa in multas:
            db.session.delete(multa)
        db.session.commit()
        flash("Todas las multas del propietario han sido eliminadas.", "success")
    except Exception:
        db.session.rollback()
        flash("Error al eliminar las multas.", "error")

    return redirect(url_for("multa.list_multas"))
