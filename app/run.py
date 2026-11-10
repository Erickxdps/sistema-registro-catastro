# run.py
# Punto de entrada de la aplicación.
#
# - `create_app()` construye la app (la usan las pruebas y Gunicorn).
# - `app` es la instancia por defecto: `gunicorn --chdir app run:app`.
# - `python run.py` levanta el servidor de desarrollo (solo para uso local).
#
# Configuración por variables de entorno (ver README):
#   SECRET_KEY      Recomendada en producción. Si falta, se genera una clave
#                   temporal en cada arranque (las sesiones se cierran al reiniciar).
#   DATABASE_URL    Opcional. Si no se define, se usa app/sistema.db (SQLite).
#                   Para datos persistentes en producción, apunta a PostgreSQL.
#   ADMIN_USERNAME / ADMIN_PASSWORD
#                   Opcionales: crean el primer administrador si la BD no
#                   tiene usuarios. La contraseña nunca se escribe en los logs.

import logging
import os
import secrets
import sqlite3

import click
from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_login import AnonymousUserMixin, LoginManager
from flask_wtf.csrf import CSRFError, CSRFProtect
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

from database import db
from models.user_model import User
from utils.http import espera_json

logger = logging.getLogger("circuata")
csrf = CSRFProtect()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIN_PASSWORD_LEN = 8


# ─────────────────────────── CONFIGURACIÓN ───────────────────────────────────

def es_produccion():
    """Detecta si la app corre en producción (Railway/Heroku o APP_ENV=production)."""
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("HEROKU")
        or os.environ.get("APP_ENV", "").strip().lower() == "production"
    )


def normalizar_database_url(url):
    """Railway/Heroku entregan 'postgres://', pero SQLAlchemy 2 exige 'postgresql://'."""
    if url and url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def construir_config(produccion):
    """Arma la configuración a partir del entorno, sin valores inseguros fijos."""
    database_url = normalizar_database_url(os.environ.get("DATABASE_URL", "").strip())
    secret_key = os.environ.get("SECRET_KEY", "").strip()

    # Fase de pruebas: sin DATABASE_URL se usa SQLite (app/sistema.db) también en
    # producción. OJO: en Railway el disco se restaura en cada despliegue, así que
    # los cambios hechos en producción se pierden al redesplegar. Para datos
    # persistentes basta con definir DATABASE_URL (PostgreSQL); no hay que tocar código.
    if not database_url:
        database_url = "sqlite:///" + os.path.join(BASE_DIR, "sistema.db")
        if produccion:
            logger.warning("DATABASE_URL no definida: se usa SQLite local, que NO persiste entre despliegues.")

    if not secret_key:
        # Clave aleatoria por arranque: nunca se usa una clave conocida públicamente.
        # Consecuencia: las sesiones se cierran cada vez que el servidor reinicia.
        secret_key = secrets.token_hex(32)
        logger.warning("SECRET_KEY no definida: se generó una clave temporal (las sesiones se cierran al reiniciar).")
    elif produccion and len(secret_key) < 32:
        logger.warning("SECRET_KEY es corta (<32 caracteres). Se recomienda una clave aleatoria más larga.")

    return {
        "SECRET_KEY": secret_key,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "DEBUG": False,
        # Cookies de sesión
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": produccion,
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_SAMESITE": "Lax",
        "REMEMBER_COOKIE_SECURE": produccion,
        # CSRF: el token vale mientras dure la sesión (formularios abiertos mucho rato).
        "WTF_CSRF_TIME_LIMIT": None,
        # Ninguna petición legítima de la app supera este tamaño.
        "MAX_CONTENT_LENGTH": 2 * 1024 * 1024,
        "INIT_DB": True,
    }


# SQLite no aplica claves foráneas salvo que se active en cada conexión.
@event.listens_for(Engine, "connect")
def _activar_fk_sqlite(dbapi_connection, _record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ─────────────────────────── USUARIOS ────────────────────────────────────────

class UsuarioAnonimo(AnonymousUserMixin):
    """Visitante sin sesión. Implementa has_role para que las plantillas no fallen."""
    role = None

    def has_role(self, role):
        return False


def crear_admin_inicial():
    """Crea el primer administrador SOLO si la BD no tiene usuarios y las
    credenciales vienen del entorno. Nunca usa contraseñas fijas en el código."""
    if User.query.count() > 0:
        return
    username = (os.environ.get("ADMIN_USERNAME") or "admin").strip() or "admin"
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if len(password) < MIN_PASSWORD_LEN:
        logger.warning(
            "La base de datos no tiene usuarios. Define ADMIN_PASSWORD (mín. %d caracteres) "
            "o ejecuta: flask --app run crear-admin", MIN_PASSWORD_LEN
        )
        return
    User(username=username, password=password, role="admin").save()
    logger.info("Administrador inicial '%s' creado a partir de las variables de entorno.", username)


def _registrar_comandos(app):
    @app.cli.command("crear-admin")
    @click.option("--username", prompt="Usuario administrador")
    @click.password_option(prompt="Contraseña", confirmation_prompt="Repite la contraseña")
    def crear_admin(username, password):
        """Crea un usuario administrador."""
        username = username.strip()
        if len(password) < MIN_PASSWORD_LEN:
            raise click.ClickException(f"La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres.")
        if User.get_user_by_username(username):
            raise click.ClickException(f"El usuario '{username}' ya existe. Usa 'cambiar-password'.")
        User(username=username, password=password, role="admin").save()
        click.echo(f"Administrador '{username}' creado.")

    @app.cli.command("cambiar-password")
    @click.argument("username")
    @click.password_option(prompt="Nueva contraseña", confirmation_prompt="Repite la contraseña")
    def cambiar_password(username, password):
        """Cambia la contraseña de un usuario existente."""
        user = User.get_user_by_username(username.strip())
        if not user:
            raise click.ClickException(f"El usuario '{username}' no existe.")
        if len(password) < MIN_PASSWORD_LEN:
            raise click.ClickException(f"La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres.")
        user.set_password(password)
        db.session.commit()
        click.echo(f"Contraseña de '{user.username}' actualizada.")


# ─────────────────────────── FÁBRICA DE LA APP ───────────────────────────────

def create_app(config_overrides=None):
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    produccion = es_produccion()
    app = Flask(__name__)
    app.config.update(construir_config(produccion))
    if config_overrides:
        app.config.update(config_overrides)

    if produccion:
        # Railway termina TLS en su proxy: confiar en X-Forwarded-* para https/IP reales.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)

    from utils import plantillas
    plantillas.registrar(app)

    login_manager = LoginManager()
    login_manager.login_view = "user.login"
    login_manager.login_message = "Inicia sesión para acceder a esta página."
    login_manager.login_message_category = "warning"
    login_manager.anonymous_user = UsuarioAnonimo
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # Import diferido: los controladores importan modelos que dependen de `db`.
    from controllers import (asistencia_controller, busqueda_controller, cuota_controller, duenio_controller,
                             multa_controller, reporte_controller, reunion_controller,
                             terreno_controller, user_controller)
    app.register_blueprint(user_controller.user_bp)
    app.register_blueprint(asistencia_controller.asistencia_bp)
    app.register_blueprint(duenio_controller.duenio_bp)
    app.register_blueprint(reunion_controller.reunion_bp)
    app.register_blueprint(terreno_controller.terreno_bp)
    app.register_blueprint(cuota_controller.cuota_bp)
    app.register_blueprint(multa_controller.multa_bp)
    app.register_blueprint(reporte_controller.reporte_bp)
    app.register_blueprint(busqueda_controller.busqueda_bp)

    @app.errorhandler(CSRFError)
    def manejar_csrf(_error):
        if espera_json():
            return jsonify({"success": False, "error": "Token de seguridad inválido o ausente. Recarga la página."}), 400
        flash("El formulario expiró o no es válido. Vuelve a intentarlo.", "error")
        return redirect(url_for("user.index"))

    @app.route("/health")
    def health():
        """Healthcheck liviano para Railway: solo verifica la conexión a la BD."""
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"status": "ok"}), 200
        except Exception:
            logger.exception("Healthcheck: la base de datos no responde")
            return jsonify({"status": "error"}), 503

    _registrar_comandos(app)

    if app.config.get("INIT_DB", True):
        with app.app_context():
            db.create_all()
            crear_admin_inicial()
            # No heredar conexiones abiertas a los workers de Gunicorn (--preload).
            db.engine.dispose()

    return app


app = create_app()

if __name__ == "__main__":
    # Servidor de desarrollo. En producción se usa Gunicorn (ver Procfile).
    port = int(os.environ.get("PORT", 5000))
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port, debug=False)
