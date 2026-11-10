# models/multa_model.py
#
# REGLAS DE NEGOCIO DE LAS MULTAS (fuente única de verdad)
# ─────────────────────────────────────────────────────────
# 1. Multa de cuota ("reflejo"): tipo='cuota' y cuota_id no nulo.
#    - Existe si y solo si la cuota NO está pagada y el propietario del terreno
#      no es inmune. Su monto y propietario siguen siempre a la cuota.
#    - Es un indicador: la deuda real es la cuota pendiente, por eso el reflejo
#      NUNCA se suma a la deuda (evita el doble cobro).
#    - No se edita ni se borra a mano: se gestiona pagando/editando la cuota.
# 2. Multa de inasistencia: tipo='asistencia' y reunion_id no nulo.
#    - Existe si el propietario no asistió, la reunión tiene monto_multa > 0 y el
#      propietario no es inmune. Se borra si luego se marca la asistencia.
# 3. Multa manual: creada por un admin (cuota_id nulo). Sí suma a la deuda.
#
# Los métodos de sincronización NO hacen commit: el controlador decide cuándo
# confirmar la transacción completa.

from database import db
from utils.fechas import hoy

TIPOS_VALIDOS = ("cuota", "asistencia")


class Multa(db.Model):
    __tablename__ = "Multa"

    multa_id = db.Column(db.Integer, primary_key=True)
    duenio_id = db.Column(db.Integer, db.ForeignKey('Duenio.id', ondelete='CASCADE'), nullable=False, index=True)
    cuota_id = db.Column(db.Integer, db.ForeignKey('Cuota.cuota_id', ondelete='SET NULL'), nullable=True, index=True)
    reunion_id = db.Column(db.Integer, db.ForeignKey('Reunion.id', ondelete='SET NULL'), nullable=True, index=True)
    monto = db.Column(db.Float, nullable=False)
    # Se pasa la FUNCIÓN `hoy` (sin paréntesis): se evalúa en cada inserción.
    fecha = db.Column(db.Date, nullable=False, default=hoy)
    tipo = db.Column(db.String(20), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)

    def __init__(self, duenio_id, monto, tipo, cuota_id=None, reunion_id=None, descripcion=None):
        self.duenio_id = duenio_id
        self.cuota_id = cuota_id
        self.reunion_id = reunion_id
        self.monto = monto
        self.tipo = tipo
        self.descripcion = descripcion

    # ── Clasificación ─────────────────────────────────────────────────────────
    @property
    def es_reflejo_cuota(self):
        """True si la multa solo refleja una cuota pendiente (no suma a la deuda)."""
        return self.tipo == "cuota" and self.cuota_id is not None

    @property
    def suma_a_deuda(self):
        return not self.es_reflejo_cuota

    @staticmethod
    def filtro_suma_a_deuda():
        """Expresión SQL equivalente a `suma_a_deuda` para consultas agregadas."""
        return db.or_(Multa.tipo != "cuota", Multa.cuota_id.is_(None))

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def save(self):
        if self.tipo not in TIPOS_VALIDOS:
            raise ValueError("El tipo debe ser 'cuota' o 'asistencia'")
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def get_all():
        return Multa.query.order_by(Multa.multa_id).all()

    @staticmethod
    def get_by_id(multa_id):
        return db.session.get(Multa, multa_id)

    def update(self, duenio_id=None, monto=None, tipo=None, descripcion=None):
        if duenio_id is not None:
            self.duenio_id = duenio_id
        if monto is not None:
            self.monto = monto
        if tipo is not None:
            if tipo not in TIPOS_VALIDOS:
                raise ValueError("El tipo debe ser 'cuota' o 'asistencia'")
            self.tipo = tipo
        if descripcion is not None:
            self.descripcion = descripcion
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    @staticmethod
    def get_by_duenio(duenio_id):
        return Multa.query.filter_by(duenio_id=duenio_id).order_by(Multa.multa_id).all()

    @staticmethod
    def get_by_tipo(tipo):
        return Multa.query.filter_by(tipo=tipo).order_by(Multa.multa_id).all()

    # ── Sincronización: multas de cuota (reflejo) ─────────────────────────────
    @staticmethod
    def sincronizar_con_cuota(cuota):
        """Deja el reflejo de `cuota` en el estado que dictan las reglas.
        Crea, actualiza o elimina según corresponda. No hace commit."""
        reflejos = Multa.query.filter_by(cuota_id=cuota.cuota_id, tipo="cuota").all()
        terreno = cuota.terreno
        duenio = terreno.dueno if terreno else None
        debe_existir = (not cuota.pagado) and duenio is not None and not duenio.es_immune

        if not debe_existir:
            for multa in reflejos:
                db.session.delete(multa)
            return None

        principal, sobrantes = (reflejos[0], reflejos[1:]) if reflejos else (None, [])
        for multa in sobrantes:  # nunca debería haber más de uno
            db.session.delete(multa)

        if principal is None:
            principal = Multa(duenio_id=duenio.id, cuota_id=cuota.cuota_id, monto=cuota.monto, tipo="cuota")
            db.session.add(principal)
        principal.duenio_id = duenio.id
        principal.monto = cuota.monto
        principal.descripcion = f"Cuota no pagada: {cuota.titulo}"
        return principal

    @staticmethod
    def eliminar_reflejos_de_cuota(cuota_id):
        Multa.query.filter_by(cuota_id=cuota_id, tipo="cuota").delete(synchronize_session=False)

    # ── Sincronización: multas de inasistencia ────────────────────────────────
    @staticmethod
    def sincronizar_con_asistencia(asistencia, reunion, duenio):
        """Crea o elimina la multa de inasistencia según el estado actual.
        Devuelve True si quedó una multa vigente. No hace commit."""
        multas = Multa.query.filter_by(
            duenio_id=asistencia.duenio_id, reunion_id=asistencia.id_reunion, tipo="asistencia"
        ).all()
        debe_existir = (
            not asistencia.asistio
            and reunion is not None and (reunion.monto_multa or 0) > 0
            and duenio is not None and not duenio.es_immune
        )
        if not debe_existir:
            for multa in multas:
                db.session.delete(multa)
            return False
        if not multas:
            db.session.add(Multa(
                duenio_id=asistencia.duenio_id,
                reunion_id=asistencia.id_reunion,
                monto=reunion.monto_multa,
                tipo="asistencia",
                descripcion=f"Multa por no asistir a reunión {asistencia.id_reunion}",
            ))
        return True
