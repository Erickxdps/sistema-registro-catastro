# models/reunion_model.py
from database import db


class Reunion(db.Model):
    __tablename__ = "Reunion"
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    monto_multa = db.Column(db.Float, nullable=False, default=100.0)

    def __init__(self, fecha, hora, descripcion=None, monto_multa=100.0):
        self.fecha = fecha
        self.hora = hora
        self.descripcion = descripcion
        self.monto_multa = monto_multa

    def save(self):
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def get_all():
        return Reunion.query.order_by(Reunion.fecha.desc(), Reunion.id.desc()).all()

    @staticmethod
    def get_by_id(id):
        return db.session.get(Reunion, id)

    def update(self, fecha=None, hora=None, descripcion=None, monto_multa=None):
        if fecha is not None:
            self.fecha = fecha
        if hora is not None:
            self.hora = hora
        if descripcion is not None:
            self.descripcion = descripcion
        if monto_multa is not None:
            self.monto_multa = monto_multa
        db.session.commit()

    # ── Operaciones de negocio (no hacen commit) ──────────────────────────────
    @staticmethod
    def crear_con_asistencias(fecha, hora, descripcion, monto_multa):
        """Crea la reunión, una asistencia (ausente) por propietario y la multa
        inicial de inasistencia para los no inmunes. Todo en una transacción."""
        from models.asistencia_model import Asistencia
        from models.duenio_model import Duenio
        from models.multa_model import Multa

        reunion = Reunion(fecha=fecha, hora=hora, descripcion=descripcion, monto_multa=monto_multa)
        db.session.add(reunion)
        db.session.flush()

        duenios = Duenio.query.order_by(Duenio.id).all()
        for duenio in duenios:
            db.session.add(Asistencia(duenio_id=duenio.id, id_reunion=reunion.id))
            if monto_multa > 0 and not duenio.es_immune:
                db.session.add(Multa(
                    duenio_id=duenio.id, reunion_id=reunion.id, monto=monto_multa, tipo='asistencia',
                    descripcion=f'Multa por no asistir a reunión {reunion.id}',
                ))
        return reunion, len(duenios)

    def eliminar(self):
        """Regla única de borrado: al eliminar una reunión se eliminan sus
        asistencias y sus multas de inasistencia. Devuelve (multas, asistencias)."""
        from models.asistencia_model import Asistencia
        from models.multa_model import Multa

        multas = Multa.query.filter_by(reunion_id=self.id).delete(synchronize_session=False)
        asistencias = Asistencia.query.filter_by(id_reunion=self.id).delete(synchronize_session=False)
        db.session.delete(self)
        return multas, asistencias

    def delete(self):
        try:
            self.eliminar()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
