# controllers/asistencia_controller.py
# Controlador de asistencias — refactorizado para:
#   1. Reemplazar es_dueno_inmune() por duenio.es_immune (propiedad del modelo).
#   2. Eliminar if/else de autorización duplicados (ya cubiertos por decoradores).
#   3. Eliminar sentencias print() de depuración del código de producción.
#   4. Mejorar manejo de errores con try/except.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import or_

from models.asistencia_model import Asistencia
from models.duenio_model     import Duenio
from models.reunion_model    import Reunion
from models.multa_model      import Multa
from views import asistencia_view
from utils.decorators import role_required
from utils.pagination import obtener_paginacion
from database import db

asistencia_bp = Blueprint("asistencia", __name__)


# ─────────────────────────── LISTADO ─────────────────────────────────────────

@asistencia_bp.route("/asistencias")
@login_required
def list_asistencias():
    """Lista paginada de asistencias con búsqueda y estadísticas globales."""
    page, per_page, search = obtener_paginacion(default_per_page=20)

    # Query base con JOINs necesarios para búsqueda y ordenamiento
    query = db.session.query(Asistencia).join(Duenio).join(Reunion)

    if search:
        filtro = f"%{search}%"
        query = query.filter(
            or_(
                Duenio.nombre.ilike(filtro),
                Duenio.paterno.ilike(filtro),
                Duenio.materno.ilike(filtro),
                Duenio.ci.ilike(filtro),
                Reunion.descripcion.ilike(filtro),
            )
        )

    # Mostrar primero las asistencias de reuniones más recientes
    asistencias_paginated = query.order_by(Reunion.fecha.desc(), Asistencia.id).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Estadísticas globales (siempre sobre el conjunto filtrado si hay búsqueda)
    total_asistencias = query.count()
    total_presentes   = query.filter(Asistencia.asistio == True).count()
    total_ausentes    = query.filter(Asistencia.asistio == False).count()
    reuniones_unicas  = query.with_entities(Asistencia.id_reunion).distinct().count()

    return asistencia_view.list_asistencias(asistencias_paginated, search, {
        'total_asistencias': total_asistencias,
        'total_presentes':   total_presentes,
        'total_ausentes':    total_ausentes,
        'reuniones_unicas':  reuniones_unicas,
    })


# ─────────────────────────── CREAR ───────────────────────────────────────────

@asistencia_bp.route("/asistencias/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_asistencia():
    """Crea o actualiza una asistencia manualmente."""
    if request.method == "POST":
        duenio_id  = request.form.get("duenio_id",  type=int)
        id_reunion = request.form.get("id_reunion",  type=int)
        asistio    = 'asistio' in request.form

        if not duenio_id or not id_reunion:
            flash("Propietario y reunión son obligatorios.", "error")
        else:
            reunion = db.session.get(Reunion, id_reunion)
            asistencia_existente = Asistencia.query.filter_by(
                duenio_id=duenio_id, id_reunion=id_reunion
            ).first()

            if asistencia_existente:
                asistencia_existente.update(asistio=asistio)
                _gestionar_multa_asistencia(asistencia_existente, asistio, reunion)
                msg = "Asistencia actualizada: Presente." if asistio else "Asistencia actualizada: Ausente. Multa aplicada."
                flash(msg, "success" if asistio else "warning")
            else:
                asistencia = Asistencia(duenio_id=duenio_id, id_reunion=id_reunion, asistio=asistio)
                asistencia.save()
                _gestionar_multa_asistencia(asistencia, asistio, reunion)
                msg = "Asistencia registrada: Presente." if asistio else "Asistencia registrada: Ausente. Multa aplicada."
                flash(msg, "success" if asistio else "warning")

        return redirect(url_for("asistencia.list_asistencias"))

    duenios   = Duenio.query.all()
    reuniones = Reunion.query.all()
    return asistencia_view.create_asistencia(duenios, reuniones)


# ─────────────────────────── ACTUALIZAR ──────────────────────────────────────

@asistencia_bp.route("/asistencias/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_asistencia(id):
    """Actualiza el estado de asistencia y gestiona la multa correspondiente."""
    asistencia = db.session.get(Asistencia, id)
    if not asistencia:
        flash("Asistencia no encontrada.", "error")
        return redirect(url_for("asistencia.list_asistencias"))

    if request.method == "POST":
        asistio_valor = request.form.get("asistio", "")
        asistio = asistio_valor in ('true', 'on') or 'asistio' in request.form

        asistencia.update(asistio=asistio)
        reunion = db.session.get(Reunion, asistencia.id_reunion)
        _gestionar_multa_asistencia(asistencia, asistio, reunion)

        flash("Asistencia actualizada exitosamente.", "success")
        return redirect(url_for("asistencia.list_asistencias"))

    return asistencia_view.update_asistencia(asistencia)


# ─────────────────────────── ELIMINAR ────────────────────────────────────────

@asistencia_bp.route("/asistencias/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_asistencia(id):
    """Elimina una asistencia y su multa asociada si existe."""
    asistencia = Asistencia.get_by_id(id)
    if not asistencia:
        flash("Asistencia no encontrada.", "error")
        return redirect(url_for("asistencia.list_asistencias"))

    try:
        _eliminar_multa_asistencia(asistencia)
        asistencia.delete()
        flash("Asistencia eliminada exitosamente.", "success")
    except Exception:
        db.session.rollback()
        flash("Error al eliminar la asistencia.", "error")

    return redirect(url_for("asistencia.list_asistencias"))


# ─────────────────────────── MARCAR ASISTENCIA ───────────────────────────────

@asistencia_bp.route("/asistencias/marcar", methods=["POST"])
@login_required
@role_required("admin")
def marcar_asistencia():
    """Marca la asistencia de un propietario a una reunión (desde listado rápido)."""
    duenio_id  = request.form.get("duenio_id",  type=int)
    id_reunion = request.form.get("id_reunion",  type=int)
    asistio    = request.form.get("asistio") == "true"

    asistencia = Asistencia.query.filter_by(
        duenio_id=duenio_id, id_reunion=id_reunion
    ).first()

    if asistencia:
        asistencia.update(asistio=asistio)
        reunion = db.session.get(Reunion, asistencia.id_reunion)
        _gestionar_multa_asistencia(asistencia, asistio, reunion)
        flash("Asistencia marcada exitosamente.", "success")
    else:
        flash("Asistencia no encontrada.", "error")

    return redirect(url_for("asistencia.list_asistencias"))


# ─────────────────────── FUNCIONES AUXILIARES PRIVADAS ───────────────────────
# Prefijo _ para indicar que son de uso interno (no se importan desde otros módulos).

def _crear_multa_asistencia(asistencia, monto_multa):
    """Crea una multa por inasistencia si no existe una previa para esa reunión."""
    # Consultar el propietario una sola vez y usar su propiedad de inmunidad
    duenio = db.session.get(Duenio, asistencia.duenio_id)
    if duenio and duenio.es_immune:
        return  # Entidad con inmunidad — no se aplica multa

    multa_existente = Multa.query.filter_by(
        duenio_id=asistencia.duenio_id,
        reunion_id=asistencia.id_reunion,
        tipo='asistencia',
    ).first()

    if not multa_existente:
        try:
            multa = Multa(
                duenio_id=asistencia.duenio_id,
                reunion_id=asistencia.id_reunion,
                monto=monto_multa,
                tipo='asistencia',
                descripcion=f'Multa por no asistir a reunión {asistencia.id_reunion}',
            )
            multa.save()
        except Exception as e:
            db.session.rollback()
            raise e


def _gestionar_multa_asistencia(asistencia, asistio, reunion):
    """
    Sincroniza la multa según el estado de asistencia:
    - Asistió  → elimina multa existente si la hay.
    - No asistió → crea multa si no existe y la reunión tiene monto > 0.
    """
    multa = Multa.query.filter_by(
        duenio_id=asistencia.duenio_id,
        reunion_id=asistencia.id_reunion,
        tipo='asistencia',
    ).first()

    if asistio and multa:
        multa.delete()
    elif not asistio and not multa and reunion and reunion.monto_multa > 0:
        _crear_multa_asistencia(asistencia, reunion.monto_multa)


def _eliminar_multa_asistencia(asistencia):
    """Elimina la multa de asistencia asociada si existe."""
    multa = Multa.query.filter_by(
        duenio_id=asistencia.duenio_id,
        reunion_id=asistencia.id_reunion,
        tipo='asistencia',
    ).first()
    if multa:
        multa.delete()
