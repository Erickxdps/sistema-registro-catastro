# Cifras del inicio: reales, sin montos para el público.
from conftest import ADMIN_PASS  # noqa: F401
from database import db
from models.cuota_model import Cuota


def test_inicio_publico_muestra_cifras_sin_montos(client, datos):
    html = client.get("/").data.decode()
    assert "cifras-inicio" in html
    assert "Propietarios al día" in html and "Recaudado" not in html and "Pendiente de cobro" not in html


def test_inicio_admin_muestra_montos_reales(app, admin_client, datos):
    with app.app_context():
        Cuota.emitir_para_todos("Canal", 100.0)
        db.session.commit()
        cid = Cuota.query.join(Cuota.terreno).filter_by(duenio_id=datos["d1"]).first().cuota_id
        Cuota.get_by_id(cid).marcar_pago(True)
        db.session.commit()
    html = admin_client.get("/").data.decode()
    assert "Recaudado" in html and "Bs 100,00" in html   # 1 de 3 cuotas pagadas (3 terrenos en la fixture)
    assert "Cuotas pagadas" in html and "33 %" in html
