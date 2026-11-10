# utils/busqueda.py
# Búsqueda por palabras: "ana pru" encuentra "Ana Pruebas Uno".
# Cada palabra debe coincidir (en cualquier parte) con alguna de las columnas.
# Así funcionan juntos nombre, apellidos y "nombre completo" en cualquier orden.

from sqlalchemy import String, and_, cast, or_

MAX_PALABRAS = 5


def _escapar_like(texto):
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def palabras(texto):
    return [p for p in (texto or "").split() if p][:MAX_PALABRAS]


def filtro_por_palabras(texto, columnas):
    """Devuelve una condición SQL o None si no hay texto.
    Las columnas numéricas se convierten a texto para buscar dentro de ellas."""
    condiciones = []
    for palabra in palabras(texto):
        patron = f"%{_escapar_like(palabra)}%"
        condiciones.append(or_(*[
            (col if _es_texto(col) else cast(col, String)).ilike(patron, escape="\\")
            for col in columnas
        ]))
    return and_(*condiciones) if condiciones else None


def _es_texto(col):
    try:
        return isinstance(col.type, String)
    except AttributeError:
        return True
