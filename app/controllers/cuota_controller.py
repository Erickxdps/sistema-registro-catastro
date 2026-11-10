# controllers/cuota_controller.py
# Controlador de cuotas — refactorizado para:
#   1. Reemplazar es_dueno_inmune() (import cruzado entre blueprints) por
#      la propiedad duenio.es_immune del modelo.
#   2. Eliminar los if/else de autorización duplicados.
#   3. Añadir @login_required a los endpoints AJAX que lo requerían.
#   4. Corregir delete_cuotas_by_owner que usaba columnas incorrectas
#      (id_dueno, id_terreno) que no existen en el esquema actual.
#
# IMPORTANTE: nombres de rutas, Blueprint y columnas de BD sin cambios.

from flask import Blueprint, request, redirect, url_for, flash, jsonify, render_template
from flask_login import login_required
from sqlalchemy import text
from models.cuota_model   import Cuota
from models.terreno_model import Terreno
from models.multa_model   import Multa
from views import cuota_view
from utils.decorators import role_required
from utils.validators import validar_texto, validar_monto
from database import db

cuota_bp = Blueprint("cuota", __name__)

# Ruta para obtener la lista de cuotas
@cuota_bp.route("/cuotas")
@login_required
def list_cuotas():
    cuotas = Cuota.get_all()
    
    # Agrupar cuotas por tipo/título (esto es lo que realmente queremos mostrar)
    cuotas_por_tipo = {}
    for cuota in cuotas:
        titulo = cuota.titulo
        
        if titulo not in cuotas_por_tipo:
            cuotas_por_tipo[titulo] = {
                'titulo': titulo,
                'descripcion': cuota.descripcion,
                'monto_individual': cuota.monto,
                'cuotas_individuales': [],
                'propietarios_afectados': set(),
                'total_cuotas': 0,
                'cuotas_pagadas': 0,
                'cuotas_pendientes': 0,
                'monto_total': 0,
                'monto_pagado': 0,
                'monto_pendiente': 0,
                'fecha_creacion': cuota.fecha_creacion
            }
        
        # Agregar la cuota individual al grupo
        cuotas_por_tipo[titulo]['cuotas_individuales'].append(cuota)
        cuotas_por_tipo[titulo]['total_cuotas'] += 1
        cuotas_por_tipo[titulo]['monto_total'] += cuota.monto
        
        # Contar estados
        if cuota.pagado:
            cuotas_por_tipo[titulo]['cuotas_pagadas'] += 1
            cuotas_por_tipo[titulo]['monto_pagado'] += cuota.monto
        else:
            cuotas_por_tipo[titulo]['cuotas_pendientes'] += 1
            cuotas_por_tipo[titulo]['monto_pendiente'] += cuota.monto
        
        # Agregar propietario afectado
        if cuota.terreno and cuota.terreno.dueno:
            dueno = cuota.terreno.dueno
            nombre_completo = f"{dueno.nombre} {dueno.paterno} {dueno.materno}".strip()
            cuotas_por_tipo[titulo]['propietarios_afectados'].add(nombre_completo)
    
    # Convertir sets a listas para el template
    for titulo in cuotas_por_tipo:
        cuotas_por_tipo[titulo]['propietarios_afectados'] = list(cuotas_por_tipo[titulo]['propietarios_afectados'])
        cuotas_por_tipo[titulo]['num_propietarios'] = len(cuotas_por_tipo[titulo]['propietarios_afectados'])
    
    return cuota_view.list_cuotas(cuotas, cuotas_por_tipo)

# Ruta para crear cuotas
@cuota_bp.route("/cuotas/create", methods=["GET", "POST"])
@login_required
@role_required("admin")
def create_cuota():
    if request.method == "POST":
        ok_tit, titulo, err_tit = validar_texto(request.form.get("titulo"), "Título de la cuota", min_len=3, max_len=150)
        ok_desc, descripcion, _ = validar_texto(request.form.get("descripcion"), "Descripción", min_len=0, max_len=500, requerido=False)
        ok_monto, monto, err_monto = validar_monto(request.form.get("monto"), "Monto por terreno", min_val=0.5)

        if not ok_tit:
            flash(err_tit, "error")
            terrenos = Terreno.query.all()
            return cuota_view.create_cuota(terrenos)

        if not ok_monto:
            flash(err_monto, "error")
            terrenos = Terreno.query.all()
            return cuota_view.create_cuota(terrenos)

        terrenos = Terreno.query.all()
        cuotas_creadas = 0

        for terreno in terrenos:
            cuota = Cuota(terreno_id=terreno.id, titulo=titulo, monto=monto, descripcion=descripcion or "")
            db.session.add(cuota)
            db.session.flush()
            _crear_multa_cuota(cuota)
            cuotas_creadas += 1

        db.session.commit()
        flash(f"¡Cuota creada exitosamente! Se aplicó a {cuotas_creadas} terrenos.", "success")
        return redirect(url_for("cuota.list_cuotas"))
    
    terrenos = Terreno.query.all()
    return cuota_view.create_cuota(terrenos)

# Endpoint AJAX para crear cuotas con progreso
@cuota_bp.route("/api/cuotas/create", methods=["POST"])
@login_required
@role_required("admin")
def create_cuota_ajax():
    try:
        # Obtener datos del formulario
        data = request.get_json()
        titulo = data["titulo"]
        descripcion = data.get("descripcion", "")
        monto = float(data["monto"])
        
        # Obtener todos los terrenos
        terrenos = Terreno.query.all()
        total_terrenos = len(terrenos)
        
        # Procesar en lotes de 50
        lote_size = 50
        cuotas_creadas = 0
        
        for i in range(0, total_terrenos, lote_size):
            lote_terrenos = terrenos[i:i + lote_size]
            
            # Crear cuotas para este lote
            for terreno in lote_terrenos:
                cuota = Cuota(
                    terreno_id=terreno.id, 
                    titulo=titulo, 
                    monto=monto, 
                    descripcion=descripcion
                )
                db.session.add(cuota)
                db.session.flush()  # Para obtener el cuota_id
                
                # Crear multa asociada
                _crear_multa_cuota(cuota)
                cuotas_creadas += 1
            
            # Commit del lote
            db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"¡Cuota creada exitosamente! Se aplicó a {cuotas_creadas} terrenos.",
            "total_cuotas": cuotas_creadas
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# Ruta para actualizar cuotas por ID
@cuota_bp.route("/cuotas/<int:cuota_id>/update", methods=["GET", "POST"])
@login_required
@role_required("admin")
def update_cuota(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        flash("Cuota no encontrada", "error")
        return redirect(url_for("cuota.list_cuotas"))

    if request.method == "POST":
        titulo      = request.form.get("titulo",      "").strip()
        descripcion = request.form.get("descripcion", "").strip()
        terreno_id  = request.form.get("terreno_id",  type=int)
        monto       = request.form.get("monto",       type=float)
        pagado      = request.form.get("pagado") == "on"

        cuota.update(titulo=titulo, descripcion=descripcion, terreno_id=terreno_id, monto=monto, pagado=pagado)
        _gestionar_multa_cuota(cuota, pagado)
        flash("Cuota actualizada exitosamente.", "success")
        return redirect(url_for("cuota.list_cuotas"))

    terrenos = Terreno.query.all()
    return cuota_view.update_cuota(cuota, terrenos)

# Ruta para eliminar cuotas por ID
@cuota_bp.route("/cuotas/<int:cuota_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_cuota(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if cuota:
        _eliminar_multa_cuota(cuota)
        cuota.delete()
        flash("Cuota eliminada exitosamente.", "success")
    else:
        flash("Cuota no encontrada.", "error")
    
    return redirect(url_for("cuota.list_cuotas"))

# Ruta para cambiar estado de pago de una cuota (AJAX)
@cuota_bp.route("/cuotas/<int:cuota_id>/toggle-payment", methods=["POST"])
@login_required
@role_required("admin")
def toggle_payment(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if not cuota:
        return jsonify({"success": False, "message": "Cuota no encontrada"}), 404
    
    # Cambiar estado de pago
    new_pagado = not cuota.pagado
    cuota.update(pagado=new_pagado)
    _gestionar_multa_cuota(cuota, new_pagado)
    
    return jsonify({
        "success": True, 
        "message": f"Cuota marcada como {'pagada' if new_pagado else 'pendiente'}",
        "pagado": new_pagado
    })

# Ruta para marcar como pagado
@cuota_bp.route("/cuotas/<int:cuota_id>/pagar", methods=["POST"])
@login_required
@role_required("admin")
def pagar_cuota(cuota_id):
    cuota = Cuota.get_by_id(cuota_id)
    if cuota:
        cuota.update(pagado=True)
        # Eliminar multa al marcar como pagado
        eliminar_multa_cuota(cuota)
        flash("Cuota marcada como pagada", "success")
    else:
        flash("Cuota no encontrada", "error")
    
    return redirect(url_for("cuota.list_cuotas"))

# Ruta para ver cuotas pendientes
@cuota_bp.route("/cuotas/pendientes")
@login_required
def cuotas_pendientes():
    cuotas = Cuota.get_pendientes()
    return cuota_view.list_cuotas_pendientes(cuotas)

# Funciones auxiliares para gestión de multas
def _crear_multa_cuota(cuota):
    """Crea una multa de tipo 'cuota' si el propietario no tiene inmunidad."""
    terreno = db.session.get(Terreno, cuota.terreno_id)
    if not terreno:
        return

    # Usar la propiedad del modelo en vez de un ID hardcodeado
    if terreno.dueno and terreno.dueno.es_immune:
        return

    multa = Multa(
        duenio_id=terreno.duenio_id,
        cuota_id=cuota.cuota_id,
        monto=cuota.monto,
        tipo='cuota',
        descripcion=f'Cuota no pagada: {cuota.titulo}',
    )
    multa.save()

# Alias sin prefijo para no romper las llamadas en create_cuota_ajax (lotes)
crear_multa_cuota = _crear_multa_cuota


def _gestionar_multa_cuota(cuota, pagado):
    """
    Sincroniza la multa con el estado de pago:
    - Pagado     → elimina multa existente.
    - No pagado  → crea multa si no existe.
    """
    multa = Multa.query.filter_by(cuota_id=cuota.cuota_id, tipo='cuota').first()
    if pagado and multa:
        multa.delete()
    elif not pagado and not multa:
        _crear_multa_cuota(cuota)

# Alias sin prefijo para compatibilidad con código no migrado aún
gestionar_multa_cuota = _gestionar_multa_cuota


def _eliminar_multa_cuota(cuota):
    """Elimina la multa asociada a una cuota si existe."""
    multa = Multa.query.filter_by(cuota_id=cuota.cuota_id, tipo='cuota').first()
    if multa:
        multa.delete()

# Alias sin prefijo para compatibilidad con código no migrado aún
eliminar_multa_cuota = _eliminar_multa_cuota

# Ruta para eliminar todas las cuotas de un propietario específico
@cuota_bp.route("/cuotas/delete-by-owner/<int:dueno_id>", methods=["POST"])
@login_required
@role_required('admin')
def delete_cuotas_by_owner(dueno_id):
    try:
        # Corrección: usar los nombres reales de columnas (duenio_id, terreno_id)
        terrenos = Terreno.query.filter_by(duenio_id=dueno_id).all()
        total_eliminadas = 0
        
        for terreno in terrenos:
            cuotas = Cuota.query.filter_by(terreno_id=terreno.id).all()
            for cuota in cuotas:
                _eliminar_multa_cuota(cuota)
                cuota.delete()
                total_eliminadas += 1
        
        flash(f"Se eliminaron {total_eliminadas} cuotas exitosamente.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar las cuotas: {str(e)}", "error")
    
    return redirect(url_for("cuota.list_cuotas"))

# Ruta para cambiar el estado de pago de una cuota (toggle)
@cuota_bp.route("/cuotas/<int:cuota_id>/toggle-status", methods=["POST"])
@login_required
@role_required('admin')
def toggle_cuota_status(cuota_id):
    try:
        cuota = Cuota.get_by_id(cuota_id)
        if not cuota:
            return jsonify({"success": False, "message": "Cuota no encontrada"}), 404
        
        data = request.get_json()
        nuevo_estado = data.get('pagado', False)
        
        cuota.update(pagado=nuevo_estado)
        
        mensaje = "pagada" if nuevo_estado else "marcada como pendiente"
        return jsonify({
            "success": True, 
            "message": f"Cuota {mensaje} exitosamente",
            "nuevo_estado": nuevo_estado
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# Ruta para eliminar una cuota específica
@cuota_bp.route("/cuotas/<int:cuota_id>", methods=["DELETE"])
@login_required
@role_required('admin')
def delete_cuota_single(cuota_id):
    try:
        cuota = Cuota.get_by_id(cuota_id)
        if not cuota:
            return jsonify({"success": False, "message": "Cuota no encontrada"}), 404
        
        titulo = cuota.titulo
        
        # Eliminar multas asociadas si existen
        try:
            eliminar_multa_cuota(cuota)
        except:
            pass  # Si no hay multa asociada, continuar
        
        # Eliminar la cuota
        cuota.delete()
        
        return jsonify({
            "success": True, 
            "message": f"Cuota '{titulo}' eliminada exitosamente"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# Endpoint AJAX optimizado para eliminar cuotas por título
@cuota_bp.route("/api/cuotas/delete-by-title", methods=["POST"])
@login_required
@role_required("admin")
def delete_cuotas_by_title_ajax():
    try:
        data = request.get_json()
        titulo = data.get("titulo")
        
        if not titulo:
            return jsonify({"success": False, "error": "Título es requerido"}), 400
        
        # Obtener información antes de eliminar
        cuotas_query = Cuota.query.filter_by(titulo=titulo)
        total_cuotas = cuotas_query.count()
        
        if total_cuotas == 0:
            return jsonify({"success": False, "error": f"No se encontraron cuotas con el título '{titulo}'"}), 404
        
        # Obtener propietarios afectados antes de eliminar
        cuotas_sample = cuotas_query.limit(100).all()  # Solo una muestra para contar propietarios únicos
        afectados = set()
        for cuota in cuotas_sample:
            if cuota.terreno and cuota.terreno.dueno:
                dueno_nombre = f"{cuota.terreno.dueno.nombre} {cuota.terreno.dueno.paterno or ''} {cuota.terreno.dueno.materno or ''}".strip()
                afectados.add(dueno_nombre)
        
        # Eliminación optimizada masiva usando SQL crudo
        # 1. Primero eliminar multas asociadas
        db.session.execute(
            text("""
                DELETE FROM Multa 
                WHERE cuota_id IN (
                    SELECT cuota_id FROM Cuota WHERE titulo = :titulo
                )
            """), 
            {"titulo": titulo}
        )
        
        # 2. Luego eliminar todas las cuotas de una vez
        result = db.session.execute(
            text("DELETE FROM Cuota WHERE titulo = :titulo"), 
            {"titulo": titulo}
        )
        
        eliminadas = result.rowcount
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Se eliminaron {eliminadas} cuotas del tipo '{titulo}' exitosamente.",
            "total_eliminadas": eliminadas,
            "propietarios_afectados": len(afectados)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

# Ruta para eliminar todas las cuotas por título (todas las cuotas de un tipo específico)
@cuota_bp.route("/cuotas/delete-by-title/<string:titulo>", methods=["POST"])
@login_required
@role_required('admin')
def delete_cuotas_by_title(titulo):
    try:
        # Obtener todas las cuotas con el título específico
        cuotas = Cuota.query.filter_by(titulo=titulo).all()
        total_eliminadas = len(cuotas)
        afectados = set()
        
        for cuota in cuotas:
            # Registrar propietarios afectados
            if cuota.terreno and cuota.terreno.dueno:
                dueno_nombre = f"{cuota.terreno.dueno.nombre} {cuota.terreno.dueno.paterno or ''} {cuota.terreno.dueno.materno or ''}".strip()
                afectados.add(dueno_nombre)
            
            # Eliminar multas asociadas
            eliminar_multa_cuota(cuota)
            # Eliminar la cuota
            cuota.delete()
        
        propietarios_afectados = len(afectados)
        flash(f"Se eliminaron {total_eliminadas} cuotas del tipo '{titulo}' que afectaban a {propietarios_afectados} propietarios.", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Error al eliminar las cuotas por título: {str(e)}", "error")
    
    return redirect(url_for("cuota.list_cuotas"))