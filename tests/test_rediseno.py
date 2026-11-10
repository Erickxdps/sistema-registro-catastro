# Rediseño del front-end: paginación server-side, buscadores, permisos de
# búsqueda, formularios, reglas de cobro y consistencia del modo oscuro.
# Todo sobre BD temporales con datos ficticios.

import re
import time
from datetime import date, time as hora

import pytest

from conftest import login
from database import db
from models.asistencia_model import Asistencia
from models.cuota_model import Cuota
from models.duenio_model import Duenio
from models.multa_model import Multa
from models.reunion_model import Reunion
from models.terreno_model import Terreno
from models.user_model import User

import run


def filas(html):
    """Cantidad de filas de datos de la tabla principal (tbody > tr)."""
    cuerpos = re.findall(r"<tbody>(.*?)</tbody>", html, re.S)
    return sum(len(re.findall(r"<tr\b", c)) for c in cuerpos)


def poblar(app, n_duenios=60, terrenos_por=2):
    """Datos ficticios masivos con inserciones en bloque (rápido)."""
    with app.app_context():
        db.session.bulk_insert_mappings(Duenio, [
            {"nombre": f"Nombre{i:05d}", "paterno": "Masivo" if i % 2 else "Prueba", "materno": "X", "ci": f"M-{i:06d}"}
            for i in range(n_duenios)])
        db.session.commit()
        ids = [d.id for d in Duenio.query.filter(Duenio.ci.like("M-%")).all()]
        db.session.bulk_insert_mappings(Terreno, [
            {"duenio_id": did, "lugar": f"L{k}", "manzano": (did % 40) + 1, "metros_cuadrados": 200.5}
            for did in ids for k in range(terrenos_por)])
        db.session.commit()
        return ids


# ─────────────────────── 1-3. Paginación server-side ─────────────────────────

@pytest.fixture
def con_datos(app, admin_client):
    poblar(app, 60)
    with app.app_context():
        for i in range(15):
            Reunion.crear_con_asistencias(date(2026, 1, 1 + i), hora(19, 0), f"Reunión {i}", 10.0)
        Cuota.emitir_para_todos("Aporte de prueba", 20.0, "")
        for i in range(15):
            db.session.add(User(f"usuario{i:02d}", "clave-larga-123", role="doctor"))
        db.session.commit()
    return admin_client


LISTADOS = ["/", "/duenios", "/terrenos", "/reuniones", "/asistencias", "/cuotas", "/multas", "/users"]


@pytest.mark.parametrize("ruta", LISTADOS)
def test_cada_listado_muestra_10_por_defecto(con_datos, ruta):
    resp = con_datos.get(ruta)
    assert resp.status_code == 200
    html = resp.data.decode()
    n = filas(html)
    if ruta == "/cuotas":
        n = filas(html.split("Detalle de cuotas", 1)[1])
    assert n == 10, f"{ruta} mostró {n} filas"
    assert "Mostrando <strong>1–10</strong>" in html


@pytest.mark.parametrize("per_page", [25, 50])
def test_opciones_de_tamano(con_datos, per_page):
    html = con_datos.get(f"/duenios?per_page={per_page}").data.decode()
    assert filas(html) == per_page


def test_paginacion_conserva_filtros_y_orden(con_datos):
    html = con_datos.get("/duenios?search=masivo&orden=-nombre&per_page=10").data.decode()
    enlaces = re.findall(r'href="(/duenios\?[^"]*page=2[^"]*)"', html)
    assert enlaces, "no hay enlace a la página 2"
    enlace = enlaces[0].replace("&amp;", "&")
    assert "search=masivo" in enlace and "orden=-nombre" in enlace and "per_page=10" in enlace
    # Y el orden se respeta en la página siguiente
    html2 = con_datos.get(enlace).data.decode()
    nombres = re.findall(r'class="celda-principal"[^>]*>(Nombre\d{5})', html2)
    assert nombres == sorted(nombres, reverse=True)


def test_ir_a_pagina_conserva_filtros(con_datos):
    html = con_datos.get("/terrenos?search=masivo&orden=-superficie").data.decode()
    form = html.split('<label for="ir-pagina">', 1)[0].rsplit("<form", 1)[1]
    assert 'name="search" value="masivo"' in form
    assert 'name="orden" value="-superficie"' in form


def test_pagina_fuera_de_rango_muestra_la_ultima(con_datos):
    html = con_datos.get("/duenios?page=9999").data.decode()
    assert filas(html) > 0


def test_orden_invalido_no_rompe(con_datos):
    assert con_datos.get("/duenios?orden=;DROP TABLE Duenio").status_code == 200


def test_filtros_de_modulo(con_datos):
    html = con_datos.get("/cuotas?estado=pagada").data.decode()
    assert "Ninguna cuota coincide" in html
    html = con_datos.get("/terrenos?manzano=5").data.decode()
    assert "Manzano 5" in html and filas(html) >= 1
    html = con_datos.get("/asistencias?estado=presente").data.decode()
    assert "Ningún registro coincide" in html


# ─────────────────────── 4-7. Buscadores ─────────────────────────────────────

def test_buscador_coincidencias_parciales_y_palabras(app, admin_client, datos):
    r = admin_client.get("/api/buscar/propietarios?q=an").get_json()
    assert any(x["texto"] == "Ana Pruebas Uno" for x in r["resultados"])
    r = admin_client.get("/api/buscar/propietarios?q=pru ana").get_json()   # nombre completo, cualquier orden
    assert [x["texto"] for x in r["resultados"]] == ["Ana Pruebas Uno"]
    r = admin_client.get("/api/buscar/propietarios?q=xyz-no-existe").get_json()
    assert r == {"resultados": [], "total": 0}


def test_buscador_limita_resultados(app, admin_client):
    poblar(app, 300, terrenos_por=1)
    r = admin_client.get("/api/buscar/propietarios?q=nombre").get_json()
    assert len(r["resultados"]) == 8 and r["total"] == 300
    r = admin_client.get("/api/buscar/propietarios?q=nombre&limit=999").get_json()
    assert len(r["resultados"]) == 20


def test_buscador_prioriza_inicio_del_nombre(app, admin_client):
    with app.app_context():
        db.session.add_all([Duenio("Mariana", "Z", "", "R-1"), Duenio("Ana", "Z", "", "R-2")])
        db.session.commit()
    r = admin_client.get("/api/buscar/propietarios?q=ana z").get_json()
    assert r["resultados"][0]["texto"].startswith("Ana")


def test_buscador_terrenos_por_lote_manzano_y_propietario(admin_client, datos):
    por_lote = admin_client.get("/api/buscar/terrenos?q=A-1").get_json()["resultados"]
    assert por_lote and por_lote[0]["id"] == datos["t1"]
    por_dueno = admin_client.get("/api/buscar/terrenos?q=beto").get_json()["resultados"]
    assert [x["id"] for x in por_dueno] == [datos["t2"]]
    por_manzano = admin_client.get("/api/buscar/terrenos?q=9").get_json()["resultados"]
    assert datos["t3"] in [x["id"] for x in por_manzano]


def test_busquedas_respetan_permisos(app, client, doctor_client, datos):
    # Sin sesión: terrenos, emisiones y usuarios exigen login
    for url in ("/api/buscar/terrenos?q=a", "/api/buscar/emisiones?q=a", "/api/buscar/usuarios?q=a"):
        assert client.get(url).status_code == 302
    # Consulta (doctor) no puede buscar usuarios
    assert doctor_client.get("/api/buscar/usuarios?q=a").status_code == 403
    # Público: propietarios, sin CI completo y sin buscar por CI
    r = client.get("/api/buscar/propietarios?q=ana").get_json()
    assert r["resultados"] and "T-1001" not in str(r)
    assert client.get("/api/buscar/propietarios?q=T-1001").get_json()["total"] == 0


def test_buscador_escapa_comodines(admin_client, datos):
    assert admin_client.get("/api/buscar/propietarios?q=%25").get_json()["total"] == 0
    assert admin_client.get("/api/buscar/propietarios?q=_").get_json()["total"] == 0


# ─────────────────────── 8-9. Formularios y acciones ─────────────────────────

def test_cambiar_propietario_de_terreno_mueve_su_cuota(app, admin_client, datos):
    with app.app_context():
        Cuota.emitir_para_todos("Canal", 100.0)
        db.session.commit()
    resp = admin_client.post(f"/terrenos/{datos['t1']}/update",
                             data={"duenio_id": datos["d2"], "lugar": "A-1", "manzano": "1", "metros_cuadrados": "300.5"})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Terreno, datos["t1"]).duenio_id == datos["d2"]
        reflejo = Multa.query.join(Cuota, Cuota.cuota_id == Multa.cuota_id).filter(Cuota.terreno_id == datos["t1"]).one()
        assert reflejo.duenio_id == datos["d2"]


def test_formulario_sin_propietario_elegido_no_guarda(app, admin_client):
    resp = admin_client.post("/terrenos/create", data={"duenio_id": "", "lugar": "Z", "manzano": "1", "metros_cuadrados": "10"})
    assert resp.status_code == 200 and "Elige un propietario" in resp.data.decode()
    with app.app_context():
        assert Terreno.query.filter_by(lugar="Z").count() == 0


def test_crear_multa_y_editarla(app, admin_client, datos):
    admin_client.post("/multas/create", data={"duenio_id": datos["d1"], "tipo": "asistencia", "monto": "25", "descripcion": "Prueba"})
    with app.app_context():
        m = Multa.query.filter_by(duenio_id=datos["d1"]).one()
        mid = m.multa_id
    assert admin_client.get(f"/multas/{mid}/update").status_code == 200   # antes: error 500
    admin_client.post(f"/multas/{mid}/update", data={"duenio_id": datos["d1"], "tipo": "asistencia", "monto": "30", "descripcion": "x"})
    with app.app_context():
        assert db.session.get(Multa, mid).monto == 30


def test_inmune_no_recibe_multa_manual(app, admin_client, datos):
    resp = admin_client.post("/multas/create", data={"duenio_id": datos["junta"], "tipo": "asistencia", "monto": "25"})
    assert "exento" in resp.data.decode()


def test_reunion_por_api_contrato_y_asistencia(app, admin_client, datos):
    r = admin_client.post("/api/reuniones/create", json={"fecha": "2026-05-04", "hora": "19:00", "descripcion": "Asamblea", "monto_multa": 50})
    datos_json = r.get_json()
    assert datos_json["success"] and datos_json["total_procesados"] == 3 and "reunion_id" in datos_json
    rid = datos_json["reunion_id"]
    with app.app_context():
        assert Asistencia.query.filter_by(id_reunion=rid).count() == 3
        assert Multa.query.filter_by(reunion_id=rid).count() == 2          # la junta es inmune
        a = Asistencia.query.filter_by(id_reunion=rid, duenio_id=datos["d1"]).one()
    admin_client.post("/asistencias/marcar", data={"duenio_id": datos["d1"], "id_reunion": rid, "asistio": "true", "volver": "/asistencias?x=1"})
    with app.app_context():
        assert db.session.get(Asistencia, a.id).asistio is True
        assert Multa.query.filter_by(reunion_id=rid, duenio_id=datos["d1"]).count() == 0
    r = admin_client.post("/api/reuniones/delete", json={"reunion_id": rid}).get_json()
    assert r["success"] and r["asistencias_eliminadas"] == 3 and r["multas_eliminadas"] == 1


def test_reunion_invalida_responde_400_sin_crear_nada(app, admin_client, datos):
    r = admin_client.post("/api/reuniones/create", json={"fecha": "mal", "hora": "19:00"})
    assert r.status_code == 400 and not r.get_json()["success"]
    r = admin_client.post("/reuniones/1/update", data={"fecha": "mal"})
    assert r.status_code in (200, 302)                                       # antes: error 500
    with app.app_context():
        assert Reunion.query.count() == 0


def test_emitir_cuota_es_atomica(app, admin_client, datos, monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("fallo simulado a mitad de la emisión")
    monkeypatch.setattr(Multa, "__init__", falla)
    r = admin_client.post("/api/cuotas/create", json={"titulo": "Aporte X", "monto": 10})
    assert r.status_code == 500
    monkeypatch.undo()
    with app.app_context():
        assert Cuota.query.count() == 0                                      # no quedó nada a medias


def test_titulo_de_emision_repetido_se_rechaza(app, admin_client, datos):
    assert admin_client.post("/api/cuotas/create", json={"titulo": "Canal", "monto": 10}).get_json()["success"]
    r = admin_client.post("/api/cuotas/create", json={"titulo": "Canal", "monto": 10})
    assert r.status_code == 400 and "Ya existe" in r.get_json()["error"]


# ─────────────────────── Sin doble cobro ─────────────────────────────────────

def test_deuda_no_cuenta_dos_veces_la_cuota(app, admin_client, datos):
    with app.app_context():
        Cuota.emitir_para_todos("Canal", 100.0)
        db.session.commit()
        assert Multa.query.filter_by(tipo="cuota").count() == 2                # reflejos de d1 y d2
        deuda = Duenio.deudas_por_propietario([datos["d1"]])[datos["d1"]]
        assert deuda == {"cuotas": 100.0, "multas": 0.0, "total": 100.0}
        cid = Cuota.query.join(Terreno).filter(Terreno.duenio_id == datos["d1"]).one().cuota_id
    html = admin_client.get(f"/reportes/imprimir/estado-cuenta/{datos['d1']}").data.decode()
    assert "Bs 100,00" in html and "Bs 200,00" not in html
    # Pagar elimina el reflejo; anular el pago lo recrea (siempre sincronizado)
    admin_client.post(f"/cuotas/{cid}/toggle-payment")
    with app.app_context():
        assert Multa.query.filter_by(cuota_id=cid).count() == 0
    admin_client.post(f"/cuotas/{cid}/toggle-status", json={"pagado": False})
    with app.app_context():
        assert Multa.query.filter_by(cuota_id=cid).count() == 1


def test_reflejo_no_se_edita_a_mano(app, admin_client, datos):
    with app.app_context():
        Cuota.emitir_para_todos("Canal", 100.0)
        db.session.commit()
        mid = Multa.query.filter_by(tipo="cuota").first().multa_id
    resp = admin_client.post(f"/multas/{mid}/delete")
    assert "/cuotas/" in resp.headers["Location"]
    with app.app_context():
        assert db.session.get(Multa, mid) is not None


# ─────────────────────── Miles de registros ──────────────────────────────────

def test_miles_de_registros_no_se_cargan_de_golpe(app, admin_client):
    poblar(app, 3000, terrenos_por=2)       # 3.000 propietarios y 6.000 terrenos
    with app.app_context():
        Cuota.emitir_para_todos("Masiva", 15.0)
        db.session.commit()
    for ruta in ("/", "/duenios", "/terrenos", "/cuotas", "/multas"):
        inicio = time.perf_counter()
        resp = admin_client.get(ruta)
        dur = time.perf_counter() - inicio
        assert resp.status_code == 200
        assert len(resp.data) < 150_000, f"{ruta} pesa {len(resp.data)} bytes"
        assert dur < 3, f"{ruta} tardó {dur:.2f}s"
    # Los formularios ya no incrustan miles de opciones <option>
    for ruta in ("/terrenos/create", "/multas/create", "/asistencias/create"):
        html = admin_client.get(ruta).data.decode()
        assert html.count("<option") < 10, ruta
    inicio = time.perf_counter()
    r = admin_client.get("/api/buscar/propietarios?q=nombre0 masivo").get_json()
    assert len(r["resultados"]) <= 8 and time.perf_counter() - inicio < 1


# ─────────────────────── Público vs. sesión ──────────────────────────────────

def test_publico_ve_inicio_y_reuniones_sin_acciones(client, datos):
    for ruta in ("/", "/reuniones"):
        html = client.get(ruta).data.decode()
        assert "Iniciar sesión" in html
        assert "/delete" not in html and "/update" not in html


def test_consulta_no_ve_acciones_de_edicion(doctor_client, datos):
    html = doctor_client.get("/duenios").data.decode()
    assert "/duenios/create" not in html and "/delete" not in html


# ─────────────────────── 10. Modo oscuro consistente ─────────────────────────

def test_modo_oscuro_define_todos_los_colores():
    import pathlib
    css = (pathlib.Path(run.BASE_DIR) / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    claro = css.split(":root {", 1)[1].split("}", 1)[0]
    oscuro = css.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0]
    colores = lambda bloque: {m for m in re.findall(r"(--[\w-]+):\s*(?:#|rgba?\()", bloque)}
    faltan = colores(claro) - colores(oscuro)
    assert not faltan, f"Colores sin versión oscura: {sorted(faltan)}"


def test_sin_dependencias_de_interfaz_antiguas():
    import pathlib
    for p in (pathlib.Path(run.BASE_DIR) / "templates").glob("*.html"):
        html = p.read_text(encoding="utf-8")
        for antiguo in ("bootstrap", "fontawesome", "<md-", "fas fa-", "onclick=\"confirm"):
            assert antiguo not in html, f"{p.name} usa {antiguo}"
