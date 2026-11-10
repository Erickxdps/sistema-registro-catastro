# models/terreno_model.py
from database import db


class Terreno(db.Model):
    __tablename__ = "Terreno"
    id = db.Column(db.Integer, primary_key=True)
    duenio_id = db.Column(db.Integer, db.ForeignKey('Duenio.id', ondelete='CASCADE'), nullable=False, index=True)
    lugar = db.Column(db.String(100), nullable=False)
    manzano = db.Column(db.Integer, nullable=False, index=True)
    # Float: el 94 % de las superficies registradas tienen decimales.
    # (SQLite no cambia nada: ya guardaba esos valores como REAL.)
    metros_cuadrados = db.Column(db.Float, nullable=False)
    dueno = db.relationship('Duenio', backref='terrenos')

    def __init__(self, duenio_id, lugar, manzano, metros_cuadrados):
        self.duenio_id = duenio_id
        self.lugar = lugar
        self.manzano = manzano
        self.metros_cuadrados = metros_cuadrados

    def save(self):
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def get_all():
        return Terreno.query.order_by(Terreno.id).all()

    @staticmethod
    def get_by_id(id):
        return db.session.get(Terreno, id)

    def update(self, duenio_id=None, lugar=None, manzano=None, metros_cuadrados=None):
        """Actualiza el terreno. Si cambia de propietario, los reflejos de sus
        cuotas pendientes pasan al nuevo propietario (o se eliminan si es inmune)."""
        if duenio_id is not None:
            self.duenio_id = duenio_id
        if lugar is not None:
            self.lugar = lugar
        if manzano is not None:
            self.manzano = manzano
        if metros_cuadrados is not None:
            self.metros_cuadrados = metros_cuadrados
        db.session.flush()
        db.session.refresh(self, ["dueno"])
        for cuota in list(self.cuotas):
            cuota.sincronizar_multa()
        db.session.commit()

    def eliminar(self):
        """Elimina el terreno con sus cuotas y los reflejos de estas. No hace commit."""
        from models.cuota_model import Cuota
        from models.multa_model import Multa

        ids = db.session.query(Cuota.cuota_id).filter(Cuota.terreno_id == self.id)
        Multa.query.filter(Multa.tipo == "cuota", Multa.cuota_id.in_(ids)).delete(synchronize_session=False)
        Cuota.query.filter(Cuota.terreno_id == self.id).delete(synchronize_session=False)
        db.session.delete(self)

    def delete(self):
        try:
            self.eliminar()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def plano_manzanos():
        """Para el plano del inicio: por manzano, terrenos y cuotas pagadas/total."""
        from sqlalchemy import case, func
        from models.cuota_model import Cuota
        terrenos = dict(db.session.query(Terreno.manzano, func.count(Terreno.id)).group_by(Terreno.manzano).all())
        cuotas = {m: (int(t or 0), int(p or 0)) for m, t, p in (
            db.session.query(Terreno.manzano, func.count(Cuota.cuota_id),
                             func.sum(case((Cuota.pagado.is_(True), 1), else_=0)))
            .join(Cuota, Cuota.terreno_id == Terreno.id)
            .group_by(Terreno.manzano).all())}
        plano = []
        for manzano in sorted(terrenos):
            total, pagadas = cuotas.get(manzano, (0, 0))
            plano.append({
                "manzano": manzano, "terrenos": int(terrenos[manzano]),
                "cuotas": total, "pagadas": pagadas,
                "porcentaje": round(pagadas / total * 100) if total else None,
            })
        return plano
