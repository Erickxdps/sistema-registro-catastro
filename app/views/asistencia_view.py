from flask import render_template


def list_asistencias(asistencias_paginated, search="", estadisticas=None, reunion=None,
                     estado="", orden="-fecha"):
    return render_template("asistencias.html", asistencias_paginated=asistencias_paginated,
                           search=search, estadisticas=estadisticas or {}, reunion=reunion,
                           estado=estado, orden=orden, title="Asistencias")


def create_asistencia(reunion=None):
    return render_template("create_asistencia.html", title="Registrar asistencia", reunion=reunion)


def update_asistencia(asistencia):
    return render_template("update_asistencia.html", title="Editar asistencia", asistencia=asistencia)
