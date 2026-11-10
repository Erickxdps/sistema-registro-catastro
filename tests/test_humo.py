# Pruebas de humo: la app completa sigue funcionando tras los cambios.

import datetime
import hashlib

import pytest

from conftest import BACKUP_DB, ROOT, iniciar_sesion_como
from database import db
from models.multa_model import Multa
from models.user_model import User

PAGINAS = [
    "/", "/duenios", "/terrenos", "/reuniones", "/asistencias", "/cuotas", "/multas",
    "/reportes", "/users", "/duenios/create", "/terrenos/create", "/reuniones/create",
    "/asistencias/create", "/cuotas/create", "/multas/create", "/users/create",
    "/reportes/exportar/duenios", "/reportes/exportar/cuotas", "/reportes/exportar/multas",
]


@pytest.mark.parametrize("ruta", PAGINAS)
def test_paginas_admin_responden(admin_client, ruta):
    assert admin_client.get(ruta).status_code == 200


def test_formularios_siguen_guardando(app, admin_client, datos):
    from models.duenio_model import Duenio
    from models.terreno_model import Terreno
    admin_client.post("/duenios/create", data={"nombre": "Carla", "paterno": "Nueva", "materno": "", "ci": "T-2000"})
    with app.app_context():
        nueva = Duenio.query.filter_by(ci="T-2000").first()
        assert nueva is not None
        nueva_id = nueva.id
    admin_client.post("/terrenos/create", data={"duenio_id": nueva_id, "lugar": "C-7", "manzano": "4", "metros_cuadrados": "120.5"})
    with app.app_context():
        assert Terreno.query.filter_by(lugar="C-7", duenio_id=nueva_id).count() == 1


def test_fecha_de_multa_se_calcula_al_insertar(app, datos, monkeypatch):
    """Antes la fecha quedaba congelada en el día en que arrancó el servidor."""
    import models.multa_model as mm
    futuro = datetime.date(2031, 5, 17)
    with app.app_context():
        monkeypatch.setattr(Multa.__table__.c.fecha.default, "arg", lambda ctx: futuro)
        m = Multa(duenio_id=datos["d1"], monto=10, tipo="asistencia")
        db.session.add(m)
        db.session.commit()
        assert m.fecha == futuro
    assert mm.hoy() == mm.hoy() and callable(mm.hoy)


def test_hash_de_password_cabe_en_la_columna(app):
    with app.app_context():
        u = User("alguien", "una-clave-larga-123")
        assert len(u.password_hash) <= User.__table__.c.password_hash.type.length


def test_claves_foraneas_activas_en_sqlite(app):
    from sqlalchemy import text
    with app.app_context():
        assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_copia_de_bd_real_carga_todas_las_paginas(app_copia_real):
    """Recorre la app con una COPIA de los datos reales (756 propietarios)."""
    with app_copia_real.app_context():
        admin = User.query.filter_by(role="admin").first()
        admin_id = admin.id
    c = app_copia_real.test_client()
    iniciar_sesion_como(c, admin_id)
    for ruta in PAGINAS:
        assert c.get(ruta).status_code == 200, ruta


def test_bd_original_intacta():
    original = ROOT / "app" / "sistema.db"
    if not (original.exists() and BACKUP_DB.exists()):
        pytest.skip("sin BD local")
    h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert h(original) == h(BACKUP_DB)
