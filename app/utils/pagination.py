# utils/pagination.py
# Lectura segura de parámetros de paginación, búsqueda y orden.
# - Por defecto 10 registros por página; la interfaz ofrece 10, 25 y 50.
# - Nunca más de MAX_PER_PAGE, aunque se pida `per_page=100000`.
# - El orden solo acepta claves de una lista blanca (nunca SQL del cliente).

from flask import request

DEFAULT_PER_PAGE = 10
OPCIONES_PER_PAGE = (10, 25, 50)
MAX_PER_PAGE = 100
MAX_SEARCH_LEN = 100


def obtener_paginacion(default_per_page=DEFAULT_PER_PAGE, max_per_page=MAX_PER_PAGE):
    """Devuelve (page, per_page, search) normalizados y acotados."""
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", default_per_page, type=int) or default_per_page
    search = (request.args.get("search", "", type=str) or "").strip()[:MAX_SEARCH_LEN]

    page = max(page, 1)
    per_page = min(max(per_page, 1), max_per_page)
    return page, per_page, search


def obtener_orden(opciones, por_defecto):
    """`opciones` es {clave: [cláusulas order_by]}. Las claves admiten el
    prefijo '-' para el orden inverso si se define así en `opciones`.
    Devuelve (clave_elegida, cláusulas)."""
    clave = request.args.get("orden", por_defecto, type=str)
    if clave not in opciones:
        clave = por_defecto
    return clave, opciones[clave]


def paginar(query, page, per_page):
    """Pagina en el servidor. Si se pide una página más allá de la última
    (p. ej. tras borrar registros), devuelve la última en vez de una vacía."""
    pag = query.paginate(page=page, per_page=per_page, error_out=False, max_per_page=MAX_PER_PAGE)
    if pag.pages and page > pag.pages:
        pag = query.paginate(page=pag.pages, per_page=per_page, error_out=False, max_per_page=MAX_PER_PAGE)
    return pag
