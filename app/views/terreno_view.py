from flask import render_template


def list_terrenos(terrenos_paginated, search="", orden="manzano", manzano=None):
    return render_template("terrenos.html", terrenos_paginated=terrenos_paginated, search=search,
                           orden=orden, manzano=manzano, title="Terrenos")


def create_terreno(form=None, duenio=None):
    return render_template("create_terreno.html", title="Nuevo terreno", form=form or {}, duenio=duenio)


def update_terreno(terreno):
    return render_template("update_terreno.html", title="Editar terreno", terreno=terreno)
