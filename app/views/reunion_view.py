from flask import render_template


def list_reuniones(reuniones_paginated, search="", orden="-fecha", conteos=None, hoy=None):
    return render_template("reuniones.html", reuniones_paginated=reuniones_paginated, search=search,
                           orden=orden, conteos=conteos or {}, hoy=hoy, title="Reuniones")


def create_reunion():
    return render_template("create_reunion.html", title="Nueva reunión")


def update_reunion(reunion):
    return render_template("update_reunion.html", title="Editar reunión", reunion=reunion)
