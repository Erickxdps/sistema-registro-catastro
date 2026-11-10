from flask import render_template


def list_cuotas(emisiones, cuotas_paginated, search="", titulo="", estado="", orden="terreno"):
    return render_template("cuotas.html", emisiones=emisiones, cuotas_paginated=cuotas_paginated,
                           search=search, titulo=titulo, estado=estado, orden=orden, title="Cuotas")


def create_cuota(total_terrenos=0):
    return render_template("create_cuota.html", title="Emitir cuota", total_terrenos=total_terrenos)


def update_cuota(cuota):
    return render_template("update_cuota.html", title="Editar cuota", cuota=cuota)
