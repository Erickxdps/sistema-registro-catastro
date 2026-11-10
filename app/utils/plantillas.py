# utils/plantillas.py
# Ayudantes para las plantillas Jinja.

from flask import request, url_for

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")
MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def url_con(**cambios):
    """URL de la página actual conservando TODOS sus filtros, orden y tamaño de
    página, y aplicando `cambios`. Un valor None (o '') quita el parámetro.
    Ej.: url_con(page=3) mantiene search, orden y per_page."""
    args = request.args.to_dict()
    for clave, valor in cambios.items():
        if valor is None or valor == "":
            args.pop(clave, None)
        else:
            args[clave] = valor
    args.update(request.view_args or {})
    return url_for(request.endpoint, **args)


def args_ocultos(*excluir):
    """Pares (clave, valor) de la consulta actual, para <input type=hidden>
    en formularios GET que deben conservar el resto de filtros."""
    return [(k, v) for k, v in request.args.items(multi=True) if k not in excluir and v != ""]


def formato_bs(valor, decimales=2):
    """1234.5 → '1.234,50' (formato boliviano)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{numero:,.{decimales}f}"
    return texto.replace(",", "\u0001").replace(".", ",").replace("\u0001", ".")


def formato_entero(valor):
    return formato_bs(valor, 0)


def formato_fecha(valor):
    return valor.strftime("%d/%m/%Y") if valor else ""


def formato_fecha_larga(valor):
    if not valor:
        return ""
    return f"{DIAS[valor.weekday()]} {valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def mes_corto(valor):
    return MESES_CORTOS[valor.month - 1] if valor else ""


def registrar(app):
    app.jinja_env.globals.update(url_con=url_con, args_ocultos=args_ocultos)
    app.jinja_env.filters.update(bs=formato_bs, entero=formato_entero, fecha=formato_fecha,
                                 fecha_larga=formato_fecha_larga, mes_corto=mes_corto)
