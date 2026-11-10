# tests/conftest.py
# Infraestructura de pruebas.
#
# GARANTÍA: ninguna prueba toca app/sistema.db. Antes de importar la app se fija
# DATABASE_URL a un archivo temporal, y cada prueba crea su propia BD aislada.
# Los datos de prueba son ficticios y solo viven en esas BD temporales.

import os
import pathlib
import shutil
import sys
import tempfile
from datetime import date, time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
BACKUP_DB = ROOT / "backups" / "sistema.db.bak-20261110"

_TMP_IMPORT = tempfile.mkdtemp(prefix="circuata-import-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_IMPORT, "import.db")
os.environ["SECRET_KEY"] = "clave-de-pruebas-" + "x" * 40
for _var in ("RAILWAY_ENVIRONMENT", "HEROKU", "APP_ENV", "ADMIN_PASSWORD", "ADMIN_USERNAME"):
    os.environ.pop(_var, None)
sys.path.insert(0, str(APP_DIR))

import run  # noqa: E402
from database import db  # noqa: E402
from models.asistencia_model import Asistencia  # noqa: E402,F401
from models.cuota_model import Cuota  # noqa: E402,F401
from models.duenio_model import Duenio  # noqa: E402
from models.multa_model import Multa  # noqa: E402,F401
from models.reunion_model import Reunion  # noqa: E402,F401
from models.terreno_model import Terreno  # noqa: E402
from models.user_model import User  # noqa: E402

ADMIN_PASS = "admin-pruebas-123"
DOCTOR_PASS = "doctor-pruebas-123"


def _crear_app(db_path, **extra):
    config = {
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
    }
    config.update(extra)
    return run.create_app(config)


@pytest.fixture
def app(tmp_path):
    application = _crear_app(tmp_path / "test.db")
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def app_csrf(tmp_path):
    """App con CSRF ACTIVADO (como en producción)."""
    application = _crear_app(tmp_path / "csrf.db", WTF_CSRF_ENABLED=True)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def datos(app):
    """Datos ficticios mínimos: 2 usuarios, 3 propietarios (uno inmune) y sus terrenos."""
    with app.app_context():
        admin = User("admin_test", ADMIN_PASS, role="admin")
        doctor = User("doctor_test", DOCTOR_PASS, role="doctor")
        d1 = Duenio("Ana", "Pruebas", "Uno", "T-1001")
        d2 = Duenio("Beto", "Pruebas", "Dos", "T-1002")
        junta = Duenio("JUNTA DE", "VECINOS", "", "555")
        db.session.add_all([admin, doctor, d1, d2, junta])
        db.session.flush()
        t1 = Terreno(d1.id, "A-1", 1, 300.5)
        t2 = Terreno(d2.id, "B-1", 2, 250)
        t3 = Terreno(junta.id, "J-1", 9, 1000)
        db.session.add_all([t1, t2, t3])
        db.session.commit()
        return {
            "admin": admin.id, "doctor": doctor.id,
            "d1": d1.id, "d2": d2.id, "junta": junta.id,
            "t1": t1.id, "t2": t2.id, "t3": t3.id,
        }


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


@pytest.fixture
def admin_client(client, datos):
    resp = login(client, "admin_test", ADMIN_PASS)
    assert resp.status_code == 302
    return client


@pytest.fixture
def doctor_client(app, datos):
    c = app.test_client()
    resp = login(c, "doctor_test", DOCTOR_PASS)
    assert resp.status_code == 302
    return c


@pytest.fixture
def reunion_hoy():
    return {"fecha": date.today().strftime("%Y-%m-%d"), "hora": time(19, 0).strftime("%H:%M")}


@pytest.fixture
def app_copia_real(tmp_path):
    """App sobre una COPIA del respaldo de la BD real (la original nunca se abre).
    Se omite si el respaldo no existe (p. ej. en otra máquina o en CI)."""
    if not BACKUP_DB.exists():
        pytest.skip("No hay respaldo local de la BD real")
    copia = tmp_path / "copia_real.db"
    shutil.copyfile(BACKUP_DB, copia)
    application = _crear_app(copia)
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


def iniciar_sesion_como(client, user_id):
    """Inicia sesión sin conocer la contraseña (solo para la copia de la BD real)."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
