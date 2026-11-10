# controllers/user_controller.py
# Controlador de usuarios — refactorizado para eliminar autorización duplicada,
# proteger el registro de usuarios y mejorar el manejo de errores.

from flask import Blueprint, request, redirect, url_for, flash, render_template, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from sqlalchemy.exc import IntegrityError

from utils.decorators import role_required
from views import user_view
from models.user_model import User
from models.asistencia_model import Asistencia
from models.terreno_model import Terreno
from models.duenio_model import Duenio
from models.reunion_model import Reunion
from models.cuota_model import Cuota
from models.multa_model import Multa
from database import db

user_bp = Blueprint("user", __name__)


# ─────────────────────────── PÁGINA PRINCIPAL ────────────────────────────────

@user_bp.route('/')
def index():
    """Página de inicio con estadísticas y directorio paginado de propietarios."""
    # Conteos para las tarjetas de estadísticas (queries ligeras)
    duenos_count = Duenio.query.count()
    terrenos_count = Terreno.query.count()
    reuniones_count = Reunion.query.count()

    # Contamos tipos únicos de cuota, no instancias individuales
    cuotas_count = db.session.query(Cuota.titulo).distinct().count()

    # Paginación y búsqueda del directorio de propietarios
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search = request.args.get('search', '', type=str)

    query = Duenio.query
    if search:
        filtro = f"%{search}%"
        query = query.filter(
            (Duenio.nombre.ilike(filtro)) |
            (Duenio.paterno.ilike(filtro)) |
            (Duenio.materno.ilike(filtro)) |
            (Duenio.ci.ilike(filtro))
        )

    duenos_paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    # Función auxiliar para sumar multas de una lista
    def total_multas(lista_multas):
        return sum(m.monto for m in lista_multas)

    return render_template(
        'index.html',
        duenos_count=duenos_count,
        terrenos_count=terrenos_count,
        reuniones_count=reuniones_count,
        cuotas_count=cuotas_count,
        duenos_paginated=duenos_paginated,
        search=search,
        multas=total_multas,
    )


# ─────────────────────────── GESTIÓN DE USUARIOS ─────────────────────────────

@user_bp.route("/users")
@login_required
def list_users():
    """Lista todos los usuarios del sistema. Solo accesible con sesión activa."""
    users = User.get_all()
    return user_view.usuarios(users)


@user_bp.route("/login", methods=["GET", "POST"])
def login():
    """Autentica a un usuario por nombre de usuario y contraseña."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Validación básica antes de consultar la BD
        if not username or not password:
            flash("Por favor, completa todos los campos.", "error")
            return user_view.login()

        user = User.get_user_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Inicio de sesión exitoso.", "success")
            # Redirigir según el rol
            if user.has_role("admin"):
                return redirect(url_for("user.list_users"))
            return redirect(url_for("user.profile", id=user.id))

        flash("Nombre de usuario o contraseña incorrectos.", "error")

    return user_view.login()


@user_bp.route("/logout")
@login_required
def logout():
    """Cierra la sesión del usuario actual."""
    logout_user()
    flash("Sesión cerrada exitosamente.", "success")
    return redirect(url_for("user.login"))


@user_bp.route("/users/create", methods=["GET", "POST"])
@login_required          # CORRECCIÓN CRÍTICA: ruta antes completamente pública
@role_required("admin")  # Solo administradores pueden crear nuevos usuarios
def create_user():
    """Crea un nuevo usuario en el sistema."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "doctor")

        # Validación de campos requeridos
        if not username or not password:
            flash("El nombre de usuario y la contraseña son obligatorios.", "error")
            return user_view.registro()

        # Validar que el rol sea uno de los permitidos
        if role not in ("admin", "doctor"):
            flash("El rol seleccionado no es válido.", "error")
            return user_view.registro()

        try:
            user = User(username=username, password=password, role=role)
            user.save()
            flash(f"Usuario '{username}' registrado exitosamente.", "success")
            return redirect(url_for("user.list_users"))
        except IntegrityError:
            db.session.rollback()
            flash("El nombre de usuario ya está en uso. Elige otro.", "error")

    return user_view.registro()


@user_bp.route("/users/<int:id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_user(id):
    """Actualiza los datos de un usuario. Solo administradores."""
    user = User.get_by_id(id)
    if not user:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("user.list_users"))

    if request.method == "POST":
        nuevo_password = request.form.get("password", "").strip()
        nuevo_role = request.form.get("role", "").strip()

        # Solo actualizar la contraseña si se proporcionó una nueva
        if nuevo_password:
            user.set_password(nuevo_password)
        if nuevo_role and nuevo_role in ("admin", "doctor"):
            user.role = nuevo_role

        try:
            user.update()  # Hace commit de los cambios acumulados
            flash("Usuario actualizado exitosamente.", "success")
        except Exception:
            db.session.rollback()
            flash("Error al actualizar el usuario.", "error")

        return redirect(url_for("user.list_users"))

    return user_view.actualizar(user)


@user_bp.route("/users/<int:id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_user(id):
    """Elimina un usuario del sistema. Solo administradores."""
    # Prevenir que el admin elimine su propia cuenta
    if id == current_user.id:
        flash("No puedes eliminar tu propia cuenta.", "error")
        return redirect(url_for("user.list_users"))

    user = User.get_by_id(id)
    if not user:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("user.list_users"))

    try:
        user.delete()
        flash("Usuario eliminado exitosamente.", "success")
    except Exception:
        db.session.rollback()
        flash("Error al eliminar el usuario.", "error")

    return redirect(url_for("user.list_users"))


@user_bp.route("/profile/<int:id>")
@login_required
def profile(id):
    """Muestra el perfil de un usuario."""
    user = User.get_by_id(id)
    if not user:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("user.index"))
    return user_view.perfil(user)


# ─────────────────────────── API AJAX (MODALES) ──────────────────────────────

@user_bp.route('/api/dueno/<int:dueno_id>/asistencias')
@login_required  # Los endpoints de API también deben requerir sesión activa
def get_dueno_asistencias(dueno_id):
    """Retorna las asistencias de un propietario en formato JSON para el modal."""
    dueno = db.session.get(Duenio, dueno_id)
    if not dueno:
        return jsonify({'success': False, 'error': f'Propietario {dueno_id} no encontrado'}), 404

    # Obtener asistencias y multas en dos queries planas, no N+1
    asistencias = Asistencia.query.filter_by(duenio_id=dueno_id).all()
    multas_asistencia = Multa.query.filter_by(duenio_id=dueno_id, tipo='asistencia').all()

    # Índice de multas por reunión (dict O(1), evita bucle anidado)
    multas_por_reunion = {m.reunion_id: float(m.monto) for m in multas_asistencia}

    data = []
    for asistencia in asistencias:
        # Omitir registros huérfanos sin reunión asociada
        if not asistencia.reunion:
            continue

        reunion = asistencia.reunion
        multa_monto = 0.0
        if not asistencia.asistio:
            multa_monto = multas_por_reunion.get(asistencia.id_reunion, 0.0)

        data.append({
            'reunion': {
                'tema': reunion.descripcion or 'Sin descripción',
                'fecha': reunion.fecha.strftime('%d/%m/%Y') if reunion.fecha else 'Sin fecha',
                'hora': reunion.hora.strftime('%H:%M') if reunion.hora else 'Sin hora',
            },
            'presente': asistencia.asistio,
            'multa_monto': multa_monto,
            'observaciones': 'Sin observaciones',
        })

    return jsonify({
        'success': True,
        'dueno': {
            'nombre': f"{dueno.nombre} {dueno.paterno or ''} {dueno.materno or ''}".strip(),
            'ci': dueno.ci,
        },
        'asistencias': data,
    })


@user_bp.route('/api/dueno/<int:dueno_id>/terrenos')
@login_required
def get_dueno_terrenos(dueno_id):
    """Retorna los terrenos de un propietario en formato JSON para el modal."""
    dueno = db.session.get(Duenio, dueno_id)
    if not dueno:
        return jsonify({'success': False, 'error': f'Propietario {dueno_id} no encontrado'}), 404

    terrenos = Terreno.query.filter_by(duenio_id=dueno_id).all()

    data = [
        {
            'numero_lote': t.lugar,
            'superficie': t.metros_cuadrados,
            'ubicacion': f"Manzana {t.manzano}",
            'descripcion': 'Sin descripción',
        }
        for t in terrenos
    ]

    return jsonify({
        'success': True,
        'dueno': {
            'nombre': f"{dueno.nombre} {dueno.paterno or ''} {dueno.materno or ''}".strip(),
            'ci': dueno.ci,
        },
        'terrenos': data,
    })


@user_bp.route('/api/dueno/<int:dueno_id>/cuotas')
@login_required
def get_dueno_cuotas(dueno_id):
    """Retorna las cuotas de un propietario (vía sus terrenos) en formato JSON para el modal."""
    dueno = db.session.get(Duenio, dueno_id)
    if not dueno:
        return jsonify({'success': False, 'error': f'Propietario {dueno_id} no encontrado'}), 404

    # JOIN explícito para evitar N+1 queries
    cuotas = Cuota.query.join(Terreno).filter(Terreno.duenio_id == dueno_id).all()

    data = [
        {
            'mes': 'N/A',
            'anio': 'N/A',
            'monto': float(c.monto),
            'estado': 'pagado' if c.pagado else 'pendiente',
            'descripcion': c.titulo,
            'fecha_vencimiento': c.fecha_creacion.strftime('%d/%m/%Y') if c.fecha_creacion else 'Sin fecha',
        }
        for c in cuotas
    ]

    return jsonify({
        'success': True,
        'dueno': {
            'nombre': f"{dueno.nombre} {dueno.paterno or ''} {dueno.materno or ''}".strip(),
            'ci': dueno.ci,
        },
        'cuotas': data,
    })
