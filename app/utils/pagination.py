# utils/pagination.py
# Lectura segura de parámetros de paginación y búsqueda.
# Evita que un cliente pida `per_page=100000` y descargue toda la tabla.

from flask import request

MAX_PER_PAGE = 100
MAX_SEARCH_LEN = 100


def obtener_paginacion(default_per_page=10, max_per_page=MAX_PER_PAGE):
    """Devuelve (page, per_page, search) normalizados y acotados."""
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", default_per_page, type=int) or default_per_page
    search = (request.args.get("search", "", type=str) or "").strip()[:MAX_SEARCH_LEN]

    page = max(page, 1)
    per_page = min(max(per_page, 1), max_per_page)
    return page, per_page, search
