# utils/http.py
# Utilidades de petición compartidas por controladores y manejadores de error.

from urllib.parse import urlparse

from flask import request


def espera_json():
    """True si la petición proviene de JavaScript (fetch/AJAX) y espera JSON."""
    return (
        request.path.startswith("/api/")
        or request.is_json
        or "X-CSRFToken" in request.headers
        or request.accept_mimetypes.best == "application/json"
    )


def es_url_interna(destino):
    """Evita redirecciones abiertas: solo se aceptan rutas relativas del mismo sitio."""
    if not destino:
        return False
    partes = urlparse(destino)
    return not partes.scheme and not partes.netloc and destino.startswith("/") and not destino.startswith("//")
