# utils/fechas.py
# Fecha "de hoy" según la hora local de la junta, no la del servidor.
# Railway corre en UTC: sin esto, un registro hecho a las 21:00 en Bolivia
# (UTC-4, sin horario de verano) quedaría con la fecha del día siguiente.

import os
from datetime import datetime, timedelta, timezone


def _zona_local():
    try:
        horas = float(os.environ.get("APP_UTC_OFFSET_HOURS", "-4"))
    except ValueError:
        horas = -4.0
    return timezone(timedelta(hours=horas))


def ahora():
    return datetime.now(_zona_local())


def hoy():
    return ahora().date()
