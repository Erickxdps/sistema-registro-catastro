# controllers/busqueda_controller.py
# Endpoints de autocompletado (NUEVOS). Todos:
#   - devuelven como máximo `limit` resultados (por defecto 8, tope 20);
#   - buscan por palabras parciales en cualquier orden ("ana pru");
#   - validan permisos en el servidor;
#   - responden {"resultados": [{"id", "texto", "detalle"}], "total": n}.
#
#   GET /api/buscar/propietarios?q=   público (el directorio del inicio es público).
#                                      Nunca expone el CI completo: solo •••123.
#   GET /api/buscar/reuniones?q=      público (el listado de reuniones es público).
#   GET /api/buscar/terrenos?q=       requiere sesión.
#   GET /api/buscar/emisiones?q=      requiere sesión (títulos de cuota).
#   GET /api/buscar/usuarios?q=       solo administradores.

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import case, func

from database import db
from models.cuota_model import Cuota
from models.duenio_model import Duenio
from models.reunion_model import Reunion
from models.terreno_model import Terreno
from models.user_model import User
from utils.busqueda import filtro_por_palabras, palabras
from utils.decorators import role_required

busqueda_bp = Blueprint("busqueda", __name__)

LIMITE_DEFECTO = 8
LIMITE_MAXIMO = 20


def _parametros():
    q = (request.args.get("q", "", type=str) or "").strip()[:100]
    limite = request.args.get("limit", LIMITE_DEFECTO, type=int) or LIMITE_DEFECTO
    return q, min(max(limite, 1), LIMITE_MAXIMO)


def _respuesta(resultados, total):
    resp = jsonify({"resultados": resultados, "total": total})
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _primero_los_que_empiezan(columna, q):
    """Ordena primero las coincidencias al inicio de `columna` ("Ana" antes que "Mariana")."""
    primera = (palabras(q) or [""])[0]
    return case((columna.ilike(f"{primera}%"), 0), else_=1)


@busqueda_bp.route("/api/buscar/propietarios")
def buscar_propietarios():
    q, limite = _parametros()
    if not q:
        return _respuesta([], 0)
    columnas = [Duenio.nombre, Duenio.paterno, Duenio.materno]
    if current_user.is_authenticated:
        columnas.append(Duenio.ci)  # sin sesión no se busca por CI (evita averiguar de quién es un documento)
    query = Duenio.query.filter(filtro_por_palabras(q, columnas))
    total = query.count()
    duenios = (query.order_by(_primero_los_que_empiezan(Duenio.nombre, q), Duenio.nombre, Duenio.paterno, Duenio.id)
               .limit(limite).all())
    lotes = Duenio.terrenos_por_propietario(d.id for d in duenios)
    resultados = []
    for d in duenios:
        n = lotes.get(d.id, 0)
        resultados.append({
            "id": d.id,
            "texto": d.nombre_completo,
            "detalle": f"CI {d.ci_enmascarado}, {n} terreno{'s' if n != 1 else ''}",
        })
    return _respuesta(resultados, total)


@busqueda_bp.route("/api/buscar/terrenos")
@login_required
def buscar_terrenos():
    q, limite = _parametros()
    if not q:
        return _respuesta([], 0)
    filtro = filtro_por_palabras(q, [Terreno.lugar, Terreno.manzano, Duenio.nombre, Duenio.paterno, Duenio.materno])
    query = db.session.query(Terreno, Duenio).join(Duenio, Duenio.id == Terreno.duenio_id).filter(filtro)
    total = query.count()
    filas = query.order_by(Terreno.manzano, Terreno.lugar, Terreno.id).limit(limite).all()
    resultados = [{
        "id": t.id,
        "texto": f"Lote {t.lugar}, manzano {t.manzano}",
        "detalle": f"{d.nombre_completo}, {t.metros_cuadrados:g} m²",
    } for t, d in filas]
    return _respuesta(resultados, total)


@busqueda_bp.route("/api/buscar/reuniones")
def buscar_reuniones():
    q, limite = _parametros()
    if not q:
        return _respuesta([], 0)
    filtro = filtro_por_palabras(q, [Reunion.descripcion, Reunion.fecha])
    query = Reunion.query.filter(filtro)
    total = query.count()
    reuniones = query.order_by(Reunion.fecha.desc(), Reunion.id.desc()).limit(limite).all()
    resultados = [{
        "id": r.id,
        "texto": r.descripcion or f"Reunión del {r.fecha.strftime('%d/%m/%Y')}",
        "detalle": f"{r.fecha.strftime('%d/%m/%Y')} a las {r.hora.strftime('%H:%M')}",
    } for r in reuniones]
    return _respuesta(resultados, total)


@busqueda_bp.route("/api/buscar/emisiones")
@login_required
def buscar_emisiones():
    q, limite = _parametros()
    query = db.session.query(Cuota.titulo, func.count(Cuota.cuota_id)).group_by(Cuota.titulo)
    if q:
        query = query.filter(filtro_por_palabras(q, [Cuota.titulo]))
    filas = query.order_by(Cuota.titulo).limit(limite).all()
    resultados = [{"id": titulo, "texto": titulo, "detalle": f"{n} cuotas"} for titulo, n in filas]
    return _respuesta(resultados, len(resultados))


@busqueda_bp.route("/api/buscar/usuarios")
@login_required
@role_required("admin")
def buscar_usuarios():
    q, limite = _parametros()
    if not q:
        return _respuesta([], 0)
    query = User.query.filter(filtro_por_palabras(q, [User.username]))
    total = query.count()
    usuarios = query.order_by(User.username).limit(limite).all()
    resultados = [{"id": u.id, "texto": u.username, "detalle": f"Rol: {u.role}"} for u in usuarios]
    return _respuesta(resultados, total)
