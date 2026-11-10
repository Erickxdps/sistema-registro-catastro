from flask import render_template


def usuarios(users, search="", orden="usuario"):
    return render_template("usuarios.html", users=users, search=search, orden=orden, title="Usuarios")


def registro():
    return render_template("registro.html", title="Nuevo usuario")


def actualizar(user):
    return render_template("actualizar.html", title="Editar usuario", user=user)


def login():
    return render_template("login.html", title="Iniciar sesión")


def perfil(user):
    return render_template("profile.html", title="Perfil", user=user)
