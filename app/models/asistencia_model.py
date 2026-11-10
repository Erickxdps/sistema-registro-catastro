# models/asistencia_model.py
from sqlalchemy import UniqueConstraint

from database import db


class Asistencia(db.Model):
    __tablename__ = "Asistencia"
    id = db.Column(db.Integer, primary_key=True)
    duenio_id = db.Column(db.Integer, db.ForeignKey('Duenio.id', ondelete='CASCADE'), nullable=False)
    id_reunion = db.Column(db.Integer, db.ForeignKey('Reunion.id', ondelete='CASCADE'), nullable=False, index=True)
    asistio = db.Column(db.Boolean, nullable=False, default=False)

    reunion = db.relationship('Reunion', backref='asistencias')
    dueno = db.relationship('Duenio', backref='asistencias')

    __table_args__ = (UniqueConstraint('duenio_id', 'id_reunion', name='_duenio_reunion_uc'),)

    def __init__(self, duenio_id, id_reunion, asistio=False):
        self.duenio_id = duenio_id
        self.id_reunion = id_reunion
        self.asistio = asistio

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        self.eliminar()
        db.session.commit()

    @staticmethod
    def get_all():
        return Asistencia.query.order_by(Asistencia.id).all()

    @staticmethod
    def get_by_id(id):
        return db.session.get(Asistencia, id)

    def update(self, duenio_id=None, id_reunion=None, asistio=None):
        if duenio_id is not None:
            self.duenio_id = duenio_id
        if id_reunion is not None:
            self.id_reunion = id_reunion
        if asistio is not None:
            self.asistio = asistio
        db.session.commit()

    # ── Operaciones de negocio (no hacen commit) ──────────────────────────────
    def marcar(self, asistio):
        """Único punto por el que cambia la asistencia: sincroniza la multa.
        Devuelve True si queda una multa de inasistencia vigente."""
        from models.duenio_model import Duenio
        from models.multa_model import Multa
        from models.reunion_model import Reunion

        self.asistio = bool(asistio)
        db.session.flush()
        reunion = db.session.get(Reunion, self.id_reunion)
        duenio = db.session.get(Duenio, self.duenio_id)
        return Multa.sincronizar_con_asistencia(self, reunion, duenio)

    def eliminar(self):
        """Elimina la asistencia y su multa de inasistencia."""
        from models.multa_model import Multa
        Multa.query.filter_by(
            duenio_id=self.duenio_id, reunion_id=self.id_reunion, tipo='asistencia'
        ).delete(synchronize_session=False)
        db.session.delete(self)
