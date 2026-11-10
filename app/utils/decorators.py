from functools import wraps

from flask import current_app, flash, jsonify, redirect, url_for
from flask_login import current_user

from utils.http import espera_json


def role_required(*roles):
    """Restringe una vista a usuarios autenticados con alguno de los roles dados.

    - Sin sesión: se delega en Flask-Login (redirige al login).
    - Con sesión pero sin rol: 403 JSON para peticiones AJAX, o aviso + redirección.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if not any(current_user.has_role(role) for role in roles):
                if espera_json():
                    return jsonify({"success": False, "error": "No tienes permisos para esta acción."}), 403
                flash("No tienes permisos para acceder a esta página.", "error")
                return redirect(url_for("user.index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator
