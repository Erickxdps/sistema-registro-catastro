# models/cuota_model.py
# Una Cuota es el aporte que debe un terreno. La deuda real vive aquí
# (pagado=False); la multa "reflejo" asociada se sincroniza desde Multa.

from sqlalchemy.orm import joinedload

from database import db
from utils.fechas import hoy


class Cuota(db.Model):
    __tablename__ = "Cuota"

    cuota_id = db.Column(db.Integer, primary_key=True)
    terreno_id = db.Column(db.Integer, db.ForeignKey('Terreno.id', ondelete='CASCADE'), nullable=False, index=True)
    titulo = db.Column(db.String(255), nullable=False, default='Cuota general', index=True)
    descripcion = db.Column(db.Text, nullable=True)
    monto = db.Column(db.Float, nullable=False)
    pagado = db.Column(db.Boolean, nullable=False, default=False)
    fecha_creacion = db.Column(db.Date, nullable=False, default=hoy)

    terreno = db.relationship('Terreno', backref='cuotas')

    def __init__(self, terreno_id, titulo, monto, descripcion=None, pagado=False):
        self.terreno_id = terreno_id
        self.titulo = titulo
        self.descripcion = descripcion
        self.monto = monto
        self.pagado = pagado

    # ── CRUD básico ───────────────────────────────────────────────────────────
    def save(self):
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def get_all():
        return Cuota.query.order_by(Cuota.cuota_id).all()

    @staticmethod
    def get_by_id(cuota_id):
        return db.session.get(Cuota, cuota_id)

    def update(self, terreno_id=None, titulo=None, descripcion=None, monto=None, pagado=None):
        """Actualiza la cuota y deja su reflejo sincronizado (monto, dueño, estado)."""
        if terreno_id is not None:
            self.terreno_id = terreno_id
        if titulo is not None:
            self.titulo = titulo
        if descripcion is not None:
            self.descripcion = descripcion
        if monto is not None:
            self.monto = monto
        if pagado is not None:
            self.pagado = bool(pagado)
        self.sincronizar_multa()
        db.session.commit()

    def delete(self):
        self.eliminar()
        db.session.commit()

    def to_dict(self):
        return {
            'cuota_id': self.cuota_id,
            'terreno_id': self.terreno_id,
            'titulo': self.titulo,
            'descripcion': self.descripcion,
            'monto': float(self.monto),
            'pagado': self.pagado,
            'fecha_creacion': self.fecha_creacion.isoformat() if self.fecha_creacion else None,
        }

    @staticmethod
    def get_by_terreno(terreno_id):
        return Cuota.query.filter_by(terreno_id=terreno_id).order_by(Cuota.cuota_id).all()

    @staticmethod
    def get_pendientes():
        return Cuota.query.filter_by(pagado=False).order_by(Cuota.cuota_id).all()

    # ── Operaciones de negocio (no hacen commit: lo decide el controlador) ────
    def sincronizar_multa(self):
        from models.multa_model import Multa
        db.session.flush()
        db.session.refresh(self, ["terreno"])
        return Multa.sincronizar_con_cuota(self)

    def marcar_pago(self, pagado):
        """Único punto por el que cambia el estado de pago: siempre sincroniza el reflejo."""
        self.pagado = bool(pagado)
        self.sincronizar_multa()

    def eliminar(self):
        """Elimina la cuota junto con su reflejo."""
        from models.multa_model import Multa
        Multa.eliminar_reflejos_de_cuota(self.cuota_id)
        db.session.delete(self)

    @staticmethod
    def emitir_para_todos(titulo, monto, descripcion=""):
        """Emite la cuota a TODOS los terrenos en una sola transacción.
        Devuelve la cantidad creada. No hace commit."""
        from models.multa_model import Multa
        from models.terreno_model import Terreno

        terrenos = Terreno.query.options(joinedload(Terreno.dueno)).order_by(Terreno.id).all()
        cuotas = [Cuota(terreno_id=t.id, titulo=titulo, monto=monto, descripcion=descripcion) for t in terrenos]
        db.session.add_all(cuotas)
        db.session.flush()  # asigna cuota_id a todas
        for cuota, terreno in zip(cuotas, terrenos):
            if terreno.dueno is not None and not terreno.dueno.es_immune:
                db.session.add(Multa(
                    duenio_id=terreno.duenio_id, cuota_id=cuota.cuota_id, monto=monto,
                    tipo="cuota", descripcion=f"Cuota no pagada: {titulo}",
                ))
        return len(cuotas)

    @staticmethod
    def eliminar_por_titulo(titulo):
        """Elimina toda una emisión (y sus reflejos). Devuelve cuántas cuotas borró. No hace commit."""
        from models.multa_model import Multa
        ids = db.session.query(Cuota.cuota_id).filter(Cuota.titulo == titulo)
        Multa.query.filter(Multa.tipo == "cuota", Multa.cuota_id.in_(ids)).delete(synchronize_session=False)
        return Cuota.query.filter(Cuota.titulo == titulo).delete(synchronize_session=False)

    @staticmethod
    def resumen_emisiones():
        """Una fila por emisión (título) con totales agregados en SQL."""
        from sqlalchemy import case, func
        from models.terreno_model import Terreno
        pagado_monto = func.sum(case((Cuota.pagado.is_(True), Cuota.monto), else_=0))
        pagadas = func.sum(case((Cuota.pagado.is_(True), 1), else_=0))
        filas = (db.session.query(
                    Cuota.titulo,
                    func.count(Cuota.cuota_id),
                    pagadas,
                    func.coalesce(func.sum(Cuota.monto), 0),
                    func.coalesce(pagado_monto, 0),
                    func.min(Cuota.fecha_creacion),
                    func.min(Cuota.monto),
                    func.max(Cuota.monto),
                    func.count(func.distinct(Terreno.duenio_id)),
                 )
                 .join(Terreno, Terreno.id == Cuota.terreno_id)
                 .group_by(Cuota.titulo)
                 .order_by(func.min(Cuota.fecha_creacion).desc(), Cuota.titulo)
                 .all())
        return [{
            "titulo": t, "total": int(n), "pagadas": int(p or 0), "pendientes": int(n) - int(p or 0),
            "monto_total": float(mt or 0), "monto_pagado": float(mp or 0),
            "monto_pendiente": float(mt or 0) - float(mp or 0),
            "fecha": f, "monto_min": float(mn or 0), "monto_max": float(mx or 0), "propietarios": int(nd or 0),
            "porcentaje": round(float(mp or 0) / float(mt) * 100, 1) if mt else 0.0,
        } for t, n, p, mt, mp, f, mn, mx, nd in filas]
