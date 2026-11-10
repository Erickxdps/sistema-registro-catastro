# models/duenio_model.py
# Modelo Duenio — refactorizado para centralizar relaciones ORM, añadir la
# propiedad `es_immune` al modelo (eliminando el hardcode de IDs en controllers)
# y estandarizar la nomenclatura de atributos de relación.
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

    # ── Relaciones (se mantienen backref exactos para no romper templates) ──
    # lazy='select' es equivalente a lazy=True pero explícito para legibilidad.
    # Las relaciones con backref desde Terreno y Asistencia agregan
    # duenio.terrenos y duenio.asistencias automáticamente al registrarse.
    multas = db.relationship('Multa', backref='duenio', lazy='select')

    def __init__(self, nombre, paterno, materno, ci):
        self.nombre  = nombre
        self.paterno = paterno
        self.materno = materno
        self.ci      = ci

    # ── Propiedad: inmunidad de entidad especial ──────────────────────────────
    @property
    def es_immune(self):
        """
        Retorna True si este propietario tiene inmunidad contra multas.
        La lógica de negocio vive en el modelo, no en los controllers,
        y depende de atributos de datos (ci, nombre) en vez de IDs de BD.
        """
        if self.ci == "555":
            return True
        nombre_upper  = (self.nombre  or "").upper()
        paterno_upper = (self.paterno or "").upper()
        if nombre_upper == "JUNTA DE" and paterno_upper == "VECINOS":
            return True
        return False

    # ── Nombre completo (helper reutilizable) ─────────────────────────────────
    @property
    def nombre_completo(self):
        """Devuelve el nombre completo concatenado y sin espacios extra."""
        partes = [self.nombre, self.paterno, self.materno]
        return " ".join(p for p in partes if p).strip()

    # ── CRUD ──────────────────────────────────────────────────────────────────
    def save(self):
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def get_all():
        return Duenio.query.all()

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
        """
        Elimina el propietario y todos sus registros dependientes en cascada
        manual, ya que SQLite no siempre respeta ON DELETE CASCADE sin
        configuración extra de PRAGMA.
        """
        from models.terreno_model  import Terreno
        from models.multa_model    import Multa
        from models.asistencia_model import Asistencia
        from models.cuota_model    import Cuota

        try:
            terrenos = Terreno.query.filter_by(duenio_id=self.id).all()

            for terreno in terrenos:
                cuotas = Cuota.query.filter_by(terreno_id=terreno.id).all()
                for cuota in cuotas:
                    # Eliminar multas asociadas a la cuota
                    Multa.query.filter_by(cuota_id=cuota.cuota_id).delete()
                    db.session.delete(cuota)

                db.session.delete(terreno)

            # Multas directas del propietario (tipo 'asistencia' u otras)
            Multa.query.filter_by(duenio_id=self.id).delete()

            # Asistencias del propietario
            Asistencia.query.filter_by(duenio_id=self.id).delete()

            db.session.delete(self)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise e

    @staticmethod
    def get_user_by_username(username):
        """Alias de compatibilidad — no aplicable a Duenio, se deja por si hay refs."""
        return None

    def has_role(self, role):
        """Alias de compatibilidad con código heredado."""
        return False
