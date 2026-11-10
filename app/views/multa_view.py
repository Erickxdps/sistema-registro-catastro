from flask import render_template


def list_multas(multas_paginated, resumen, search="", tipo="", orden="-fecha"):
    return render_template("multas.html", multas_paginated=multas_paginated, resumen=resumen,
                           search=search, tipo=tipo, orden=orden, title="Multas")


def create_multa(form=None, duenio=None):
    return render_template("create_multa.html", title="Nueva multa", form=form or {}, duenio=duenio)


def update_multa(multa):
    return render_template("update_multa.html", title="Editar multa", multa=multa)


def multas_por_duenio(duenio, multas, deuda):
    return render_template("multas_duenio.html", duenio=duenio, multas=multas, deuda=deuda,
                           title=f"Multas de {duenio.nombre_completo}")
