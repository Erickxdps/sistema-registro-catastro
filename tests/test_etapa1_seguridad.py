# Etapa 1 — Seguridad: autenticación, autorización, paginación, CSRF, secretos.

import logging
import re

import pytest

import run
from conftest import ADMIN_PASS, login
from database import db
from models.duenio_model import Duenio
from models.user_model import User

RUTAS_PRIVADAS = [
    "/", "/duenios", "/terrenos", "/asistencias", "/cuotas", "/multas", "/reportes",
    "/users", "/reportes/exportar/duenios", "/reportes/exportar/cuotas",
    "/reportes/exportar/multas", "/api/dueno/1/cuotas", "/api/dueno/1/terrenos",
    "/api/dueno/1/asistencias", "/cuotas/pendientes",
]


@pytest.mark.parametrize("ruta", RUTAS_PRIVADAS)
def test_rutas_con_datos_personales_requieren_login(client, datos, ruta):
    resp = client.get(ruta)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_inicio_anonimo_no_muestra_ci(client, datos):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert b"T-1001" not in resp.data


def test_reuniones_publica_no_falla_para_anonimo(client, datos):
    resp = client.get("/reuniones")
    assert resp.status_code == 200
    assert b"Nueva reuni" not in resp.data  # el botón de admin no aparece


def test_health_publico_y_liviano(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


@pytest.mark.parametrize("per_page", ["100000", "-5", "0", "abc"])
def test_paginacion_acotada(app, admin_client, per_page):
    with app.app_context():
        db.session.add_all([Duenio(f"N{i}", "P", "M", f"CI-{i:04d}") for i in range(130)])
        db.session.commit()
    for ruta in ("/duenios", "/"):
        resp = admin_client.get(f"{ruta}?per_page={per_page}")
        assert resp.status_code == 200
        filas = len(re.findall(rb"CI-\d{4}", resp.data))
        assert filas <= 100


def test_doctor_no_ve_gestion_de_usuarios(doctor_client):
    resp = doctor_client.get("/users")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_doctor_no_puede_crear_ni_borrar(app, doctor_client, datos):
    resp = doctor_client.post("/duenios/create", data={"nombre": "X", "ci": "T-9999"})
    assert resp.status_code == 302
    resp = doctor_client.post(f"/duenios/{datos['d1']}/delete")
    assert resp.status_code == 302
    with app.app_context():
        assert Duenio.query.filter_by(ci="T-9999").first() is None
        assert db.session.get(Duenio, datos["d1"]) is not None


def test_doctor_api_admin_responde_403_json(doctor_client):
    resp = doctor_client.post("/api/cuotas/create", json={"titulo": "X", "monto": 10})
    assert resp.status_code == 403
    assert resp.get_json()["success"] is False


def test_perfil_ajeno_solo_para_admin(doctor_client, admin_client, datos):
    assert doctor_client.get(f"/profile/{datos['doctor']}").status_code == 200
    resp = doctor_client.get(f"/profile/{datos['admin']}")
    assert resp.status_code == 302 and f"/profile/{datos['doctor']}" in resp.headers["Location"]
    assert admin_client.get(f"/profile/{datos['doctor']}").status_code == 200


def test_login_no_permite_redireccion_abierta(client, datos):
    resp = client.post("/login?next=https://sitio-malicioso.example/x",
                       data={"username": "admin_test", "password": ADMIN_PASS})
    assert resp.status_code == 302
    assert "sitio-malicioso" not in resp.headers["Location"]


def test_login_respeta_next_interno(client, datos):
    resp = client.post("/login?next=/terrenos", data={"username": "admin_test", "password": ADMIN_PASS})
    assert resp.headers["Location"] == "/terrenos"


def test_login_incorrecto(client, datos):
    resp = login(client, "admin_test", "mala")
    assert resp.status_code == 200
    assert client.get("/duenios").status_code == 302


def test_no_se_puede_degradar_al_ultimo_admin(app, admin_client, datos):
    resp = admin_client.post(f"/users/{datos['admin']}/update", data={"role": "doctor", "password": ""})
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(User, datos["admin"]).role == "admin"


def test_crear_usuario_exige_password_minima(app, admin_client):
    admin_client.post("/users/create", data={"username": "nuevo", "password": "corta", "role": "doctor"})
    with app.app_context():
        assert User.get_user_by_username("nuevo") is None
    admin_client.post("/users/create", data={"username": "nuevo", "password": "suficiente-123", "role": "doctor"})
    with app.app_context():
        assert User.get_user_by_username("nuevo").role == "doctor"


# ─────────────────────────── CSRF ────────────────────────────────────────────

def _token(client, ruta="/login"):
    html = client.get(ruta).data.decode()
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_csrf_bloquea_post_sin_token(app_csrf):
    with app_csrf.app_context():
        User("admin_csrf", ADMIN_PASS, role="admin").save()
    c = app_csrf.test_client()
    c.post("/login", data={"username": "admin_csrf", "password": ADMIN_PASS})
    # Sin token la sesión NO se inicia:
    resp = c.get("/duenios")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_csrf_permite_post_con_token_y_bloquea_ajax_sin_cabecera(app_csrf):
    with app_csrf.app_context():
        User("admin_csrf", ADMIN_PASS, role="admin").save()
        db.session.add(Duenio("Z", "Z", "Z", "T-5555"))
        db.session.commit()
        duenio_id = Duenio.query.filter_by(ci="T-5555").first().id
    c = app_csrf.test_client()
    token = _token(c)
    resp = c.post("/login", data={"username": "admin_csrf", "password": ADMIN_PASS, "csrf_token": token})
    assert resp.status_code == 302
    assert c.get("/duenios").status_code == 200

    # AJAX sin cabecera X-CSRFToken → 400 JSON
    resp = c.post("/api/reuniones/delete", json={"reunion_id": 1})
    assert resp.status_code == 400 and resp.get_json()["success"] is False

    # Borrado por formulario sin token → no se borra
    c.post(f"/duenios/{duenio_id}/delete")
    with app_csrf.app_context():
        assert db.session.get(Duenio, duenio_id) is not None

    # Con token (cabecera, como hace el fetch de base.html) → sí funciona
    token = _token(c, "/duenios")
    resp = c.post(f"/duenios/{duenio_id}/delete", headers={"X-CSRFToken": token})
    with app_csrf.app_context():
        assert db.session.get(Duenio, duenio_id) is None


def test_todas_las_plantillas_post_tienen_token():
    import pathlib
    for p in (pathlib.Path(run.BASE_DIR) / "templates").glob("*.html"):
        html = p.read_text(encoding="utf-8")
        for m in re.finditer(r"<form\b[^>]*>", html, re.S | re.I):
            if not re.search(r'method\s*=\s*["\']post["\']', m.group(0), re.I):
                continue
            linea = html[html.rfind("\n", 0, m.start()) + 1:m.start()]
            if "'" in linea:
                continue  # formulario generado en JS: lo cubre el script de base.html
            assert "csrf_token" in html[m.end():m.end() + 300], f"{p.name}: formulario POST sin csrf_token"


# ─────────────────────────── SECRETOS Y CONFIGURACIÓN ────────────────────────

def test_produccion_sin_secret_key_usa_clave_aleatoria(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert run.es_produccion()
    a = run.construir_config(True)["SECRET_KEY"]
    b = run.construir_config(True)["SECRET_KEY"]
    assert a != b and len(a) >= 32


def test_produccion_sin_database_url_usa_sqlite_local(monkeypatch):
    """Fase de pruebas: sin DATABASE_URL se sigue usando app/sistema.db."""
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    uri = run.construir_config(True)["SQLALCHEMY_DATABASE_URI"]
    assert uri.startswith("sqlite:///") and uri.endswith("sistema.db")


def test_produccion_cookies_seguras(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    cfg = run.construir_config(True)
    assert cfg["SESSION_COOKIE_SECURE"] and cfg["SESSION_COOKIE_HTTPONLY"]
    assert cfg["SQLALCHEMY_DATABASE_URI"].startswith("postgresql://")


def test_desarrollo_sin_secret_key_no_usa_clave_conocida(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    a = run.construir_config(False)["SECRET_KEY"]
    b = run.construir_config(False)["SECRET_KEY"]
    assert a != b and len(a) >= 32
    assert a not in ("clave-secreta", "fallback-key-change-this")


def test_sin_admin_password_no_se_crean_usuarios_por_defecto(app):
    with app.app_context():
        assert User.query.count() == 0


def test_admin_inicial_desde_entorno_sin_exponer_password(monkeypatch, tmp_path, caplog):
    secreto = "Secreto-Del-Entorno-42"
    monkeypatch.setenv("ADMIN_USERNAME", "jefe")
    monkeypatch.setenv("ADMIN_PASSWORD", secreto)
    with caplog.at_level(logging.INFO):
        application = run.create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path/'a.db'}", "TESTING": True})
    with application.app_context():
        jefe = User.get_user_by_username("jefe")
        assert jefe is not None and jefe.role == "admin" and jefe.check_password(secreto)
        db.engine.dispose()
    assert secreto not in caplog.text


def test_codigo_sin_credenciales_fijas():
    import pathlib
    for p in pathlib.Path(run.BASE_DIR).rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert not re.search(r'password\s*=\s*"[^"]{4,}"', src), f"Credencial fija en {p.name}"
        assert "clave-secreta" not in src and "fallback-key-change-this" not in src
