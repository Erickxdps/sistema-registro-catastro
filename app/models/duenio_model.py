# models/duenio_model.py
# Modelo Duenio (propietario).
#
# IMPORTANTE: __tablename__, nombres de columnas y ForeignKeys no se modifican.

from database import db


class Duenio(db.Model):
    __tablename__ = "Duenio"

    id      = db.Column(db.Integer, primary_key=True)
    nombre  = db.Column(db.String(50), nullable=False)
    paterno = db.Column(db.String(50), nullable=True)
    materno = db.Column(db.String(50), nullable=True)
    ci      = db.Column(db.String(20), unique=True, nullable=False)

    # Las relaciones con backref desde Terreno y Asistencia agregan
    # duenio.terrenos y duenio.asistencias automáticamente.
    multas = db.relationship('Multa', backref='duenio', lazy='select')

    def __init__(self, nombre, paterno, materno, ci):
        self.nombre  = nombre
        self.paterno = paterno
        self.materno = materno
        self.ci      = ci

    # ── Inmunidad: la propia junta figura como propietaria y no se multa ──────
    @property
    def es_immune(self):
        if self.ci == "555":
            return True
        nombre_upper  = (self.nombre  or "").upper()
        paterno_upper = (self.paterno or "").upper()
        return nombre_upper == "JUNTA DE" and paterno_upper == "VECINOS"

    @property
    def nombre_completo(self):
        partes = [self.nombre, self.paterno, self.materno]
        return " ".join(p.strip() for p in partes if p and p.strip())

    @property
    def iniciales(self):
        return ((self.nombre or "?")[:1] + (self.paterno or "")[:1]).upper()

    @property
    def ci_enmascarado(self):
        """CI parcialmente oculto (muestra los 3 últimos caracteres).
        Sirve para distinguir homónimos sin publicar el documento completo."""
        ci = (self.ci or "").strip()
        if len(ci) <= 3:
            return "•" * len(ci)
        return "•" * (len(ci) - 3) + ci[-3:]

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def save(self):
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def get_all():
        return Duenio.query.order_by(Duenio.id).all()

    @staticmethod
    def get_by_id(id):
        return db.session.get(Duenio, id)

    def update(self, nombre=None, paterno=None, materno=None, ci=None):
        if nombre  is not None: self.nombre  = nombre
        if paterno is not None: self.paterno = paterno
        if materno is not None: self.materno = materno
        if ci      is not None: self.ci      = ci
        db.session.commit()

    def delete(self):
        """Elimina el propietario y todo lo que depende de él en una sola
        transacción: terrenos, cuotas (y sus reflejos), multas y asistencias."""
        from models.terreno_model import Terreno
        from models.multa_model import Multa
        from models.asistencia_model import Asistencia

        try:
            for terreno in Terreno.query.filter_by(duenio_id=self.id).all():
                terreno.eliminar()
            Multa.query.filter_by(duenio_id=self.id).delete(synchronize_session=False)
            Asistencia.query.filter_by(duenio_id=self.id).delete(synchronize_session=False)
            db.session.flush()
            db.session.expire(self)
            db.session.delete(self)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    # ── Deuda ─────────────────────────────────────────────────────────────────
    @staticmethod
    def deudas_por_propietario(ids):
        """Deuda real de cada propietario, en dos consultas agregadas:
        cuotas pendientes de sus terrenos + multas que suman a la deuda.
        Los reflejos de cuota NO se suman (ya están contados en la cuota).
        Devuelve {duenio_id: {'cuotas': x, 'multas': y, 'total': x + y}}."""
        from sqlalchemy import func
        from models.terreno_model import Terreno
        from models.multa_model import Multa
        from models.cuota_model import Cuota

        ids = list(ids)
        resultado = {i: {"cuotas": 0.0, "multas": 0.0, "total": 0.0} for i in ids}
        if not ids:
            return resultado
        filas = (db.session.query(Terreno.duenio_id, func.coalesce(func.sum(Cuota.monto), 0))
                 .join(Cuota, Cuota.terreno_id == Terreno.id)
                 .filter(Cuota.pagado.is_(False), Terreno.duenio_id.in_(ids))
                 .group_by(Terreno.duenio_id).all())
        for duenio_id, suma in filas:
            resultado[duenio_id]["cuotas"] = float(suma or 0)
        filas = (db.session.query(Multa.duenio_id, func.coalesce(func.sum(Multa.monto), 0))
                 .filter(Multa.duenio_id.in_(ids), Multa.filtro_suma_a_deuda())
                 .group_by(Multa.duenio_id).all())
        for duenio_id, suma in filas:
            resultado[duenio_id]["multas"] = float(suma or 0)
        for datos in resultado.values():
            datos["total"] = round(datos["cuotas"] + datos["multas"], 2)
        return resultado

    @staticmethod
    def terrenos_por_propietario(ids):
        from sqlalchemy import func
        from models.terreno_model import Terreno
        ids = list(ids)
        if not ids:
            return {}
        return dict(db.session.query(Terreno.duenio_id, func.count(Terreno.id))
                    .filter(Terreno.duenio_id.in_(ids)).group_by(Terreno.duenio_id).all())

    # ── Compatibilidad con código heredado ────────────────────────────────────
    @staticmethod
    def get_user_by_username(username):
        return None

    def has_role(self, role):
        return False
