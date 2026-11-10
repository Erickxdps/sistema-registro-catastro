from flask import render_template


def list_duenios(duenios_paginated, search="", orden="nombre", deudas=None, lotes=None):
    return render_template("duenios.html", duenios_paginated=duenios_paginated, search=search,
                           orden=orden, deudas=deudas or {}, lotes=lotes or {}, title="Propietarios")


def create_duenio(form=None):
    return render_template("create_duenio.html", title="Nuevo propietario", form=form or {})


def update_duenio(duenio):
    return render_template("update_duenio.html", title="Editar propietario", duenio=duenio)
