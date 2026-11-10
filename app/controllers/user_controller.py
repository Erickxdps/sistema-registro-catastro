# controllers/user_controller.py
# Controlador de usuarios — refactorizado para eliminar autorización duplicada,
# proteger el registro de usuarios y mejorar el manejo de errores.

from flask import Blueprint, request, redirect, url_for, flash, render_template, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.exc import IntegrityError

from utils.decorators import role_required
from utils.http import es_url_interna
from utils.pagination import obtener_paginacion
from utils.validators import validar_texto, validar_rol
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

MIN_PASSWORD_LEN = 8

ORDEN_DIRECTORIO = {
    "nombre": [Duenio.nombre.asc(), Duenio.paterno.asc(), Duenio.id.asc()],
    "-nombre": [Duenio.nombre.desc(), Duenio.paterno.desc(), Duenio.id.desc()],
    "paterno": [Duenio.paterno.asc(), Duenio.nombre.asc(), Duenio.id.asc()],
    "-paterno": [Duenio.paterno.desc(), Duenio.nombre.desc(), Duenio.id.desc()],
    "registro": [Duenio.id.asc()],
    "-registro": [Duenio.id.desc()],
}


@user_bp.route('/')
def index():
    """Inicio PÚBLICO: plano de manzanos, recaudación y directorio paginado.

    Sin sesión se muestra lo que la junta publica: nombres, CI enmascarado,
    cantidad de terrenos y si el propietario está al día. Los montos de deuda,
    el CI completo y las acciones solo aparecen con sesión iniciada."""
    from sqlalchemy import func
    from utils.busqueda import filtro_por_palabras
    from utils.fechas import hoy
    from utils.pagination import obtener_orden, paginar

    autenticado = current_user.is_authenticated
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden(ORDEN_DIRECTORIO, "nombre")

    query = Duenio.query
    filtro = filtro_por_palabras(search, [Duenio.nombre, Duenio.paterno, Duenio.materno]
                                 + ([Duenio.ci] if autenticado else []))
    if filtro is not None:
        query = query.filter(filtro)
    duenos_paginated = paginar(query.order_by(*clausulas), page, per_page)
    ids = [d.id for d in duenos_paginated.items]

    emisiones = Cuota.resumen_emisiones()
    hoy_ = hoy()
    proxima = (Reunion.query.filter(Reunion.fecha >= hoy_)
               .order_by(Reunion.fecha.asc(), Reunion.hora.asc()).first())
    ultimas = (Reunion.query.filter(Reunion.fecha < hoy_)
               .order_by(Reunion.fecha.desc(), Reunion.id.desc()).limit(3).all())
    presentes = dict(db.session.query(Asistencia.id_reunion, func.count(Asistencia.id))
                     .filter(Asistencia.asistio.is_(True),
                             Asistencia.id_reunion.in_([r.id for r in ultimas] or [0]))
                     .group_by(Asistencia.id_reunion).all())

    alertas = None
    if autenticado and current_user.has_role("admin"):
        alertas = {
            "roles_invalidos": User.query.filter(User.role.notin_(("admin", "doctor"))).count(),
            "sin_terreno": Duenio.query.filter(~Duenio.terrenos.any()).count(),
        }

    return render_template(
        'index.html',
        duenos_count=Duenio.query.count(),
        terrenos_count=Terreno.query.count(),
        reuniones_count=Reunion.query.count(),
        cuotas_count=len(emisiones),
        emisiones=emisiones,
        plano=Terreno.plano_manzanos(),
        proxima=proxima,
        ultimas=ultimas,
        presentes=presentes,
        alertas=alertas,
        duenos_paginated=duenos_paginated,
        deudas=Duenio.deudas_por_propietario(ids),
        lotes=Duenio.terrenos_por_propietario(ids),
        search=search,
        orden=orden,
    )


# ─────────────────────────── GESTIÓN DE USUARIOS ─────────────────────────────

@user_bp.route("/users")
@login_required
@role_required("admin")
def list_users():
    """Lista paginada de usuarios con búsqueda. Solo administradores."""
    from utils.busqueda import filtro_por_palabras
    from utils.pagination import obtener_orden, paginar
    page, per_page, search = obtener_paginacion()
    orden, clausulas = obtener_orden({
        "usuario": [User.username.asc()], "-usuario": [User.username.desc()],
        "rol": [User.role.asc(), User.username.asc()], "-rol": [User.role.desc(), User.username.asc()],
    }, "usuario")
    query = User.query
    filtro = filtro_por_palabras(search, [User.username, User.role])
    if filtro is not None:
        query = query.filter(filtro)
    users = paginar(query.order_by(*clausulas), page, per_page)
    return user_view.usuarios(users, search=search, orden=orden)


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
        if user and user.check_password(password):
            login_user(user)
            flash("Inicio de sesión exitoso.", "success")
            # Volver a la página solicitada solo si es una ruta interna (evita open redirect)
            destino = request.args.get("next")
            if es_url_interna(destino):
                return redirect(destino)
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
        ok_user, username, err_user = validar_texto(request.form.get("username"), "Nombre de usuario", min_len=3, max_len=100)
        password = request.form.get("password", "")
        ok_rol, role, err_rol = validar_rol(request.form.get("role", "doctor"))

        if not ok_user:
            flash(err_user, "error")
            return user_view.registro()
        if len(password) < MIN_PASSWORD_LEN:
            flash(f"La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres.", "error")
            return user_view.registro()
        if not ok_rol:
            flash(err_rol, "error")
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
        nuevo_password = request.form.get("password", "")
        nuevo_role = request.form.get("role", "").strip().lower()

        # Solo actualizar la contraseña si se proporcionó una nueva
        if nuevo_password.strip():
            if len(nuevo_password) < MIN_PASSWORD_LEN:
                flash(f"La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres.", "error")
                return user_view.actualizar(user)
            user.set_password(nuevo_password)

        if nuevo_role:
            if nuevo_role not in ("admin", "doctor"):
                flash("El rol seleccionado no es válido.", "error")
                return user_view.actualizar(user)
            # No dejar el sistema sin administradores
            if user.has_role("admin") and nuevo_role != "admin" and _contar_admins() <= 1:
                db.session.rollback()
                flash("No puedes quitar el rol al último administrador.", "error")
                return user_view.actualizar(user)
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
    """Muestra el perfil de un usuario: el propio, o cualquiera si es administrador."""
    if id != current_user.id and not current_user.has_role("admin"):
        flash("Solo puedes ver tu propio perfil.", "error")
        return redirect(url_for("user.profile", id=current_user.id))
    user = User.get_by_id(id)
    if not user:
        flash("Usuario no encontrado.", "error")
        return redirect(url_for("user.index"))
    return user_view.perfil(user)


def _contar_admins():
    return User.query.filter_by(role="admin").count()


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
