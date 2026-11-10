# controllers/reporte_controller.py
# Controlador de reportes, estadísticas y exportación de datos a Excel (.xlsx).
# Respeta estrictamente los modelos y esquemas SQL existentes.

import io
from datetime import datetime
from flask import Blueprint, render_template, send_file, flash, redirect, url_for
from flask_login import login_required
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from models.duenio_model import Duenio
from models.terreno_model import Terreno
from models.cuota_model import Cuota
from models.multa_model import Multa
from models.reunion_model import Reunion
from models.asistencia_model import Asistencia
from database import db

reporte_bp = Blueprint("reporte", __name__)


# ── Estilos para hojas de cálculo Excel ───────────────────────────────────────
def _aplicar_estilos_excel(ws, titulo="REPORTE"):
    """Aplica formato visual profesional de la Junta de Vecinos a la hoja de Excel."""
    # Colores corporativos
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=14, bold=True, color="1F4E78")
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    # Insertar título general en la fila 1 y 2
    ws.insert_rows(1, 2)
    ws['A1'] = f"JUNTA DE VECINOS CIRCUATA - {titulo}"
    ws['A1'].font = title_font
    ws['A2'] = f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws['A2'].font = Font(name="Calibri", size=9, italic=True, color="595959")

    # Estilar encabezados (fila 3)
    for cell in ws[3]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Ajustar ancho de columnas automáticamente
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            # Formatear bordes desde la fila 3
            if cell.row >= 3:
                cell.border = thin_border
            val = str(cell.value or '')
            if cell.row > 2 and len(val) > max_len:
                max_len = len(val)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)


# ── Vista principal de Reportes ──────────────────────────────────────────────
@reporte_bp.route("/reportes")
@login_required
def index():
    """Pantalla con métricas generales de recaudación y accesos directos a exportación."""
    total_duenios = Duenio.query.count()
    total_terrenos = Terreno.query.count()
    total_reuniones = Reunion.query.count()

    # Métricas de cuotas
    cuotas = Cuota.query.all()
    monto_cuotas_total = sum(c.monto for c in cuotas)
    cuotas_pagadas = [c for c in cuotas if c.pagado]
    monto_recaudado = sum(c.monto for c in cuotas_pagadas)
    monto_pendiente = monto_cuotas_total - monto_recaudado
    porcentaje_recaudacion = round((monto_recaudado / monto_cuotas_total * 100), 1) if monto_cuotas_total > 0 else 0

    # Métricas de multas
    multas = Multa.query.all()
    monto_multas_total = sum(m.monto for m in multas)

    return render_template(
        "reportes.html",
        total_duenios=total_duenios,
        total_terrenos=total_terrenos,
        total_reuniones=total_reuniones,
        total_cuotas=len(cuotas),
        monto_cuotas_total=monto_cuotas_total,
        monto_recaudado=monto_recaudado,
        monto_pendiente=monto_pendiente,
        porcentaje_recaudacion=porcentaje_recaudacion,
        total_multas=len(multas),
        monto_multas_total=monto_multas_total
    )


# ── Exportar Propietarios a Excel ────────────────────────────────────────────
@reporte_bp.route("/reportes/exportar/duenios")
@login_required
def exportar_duenios():
    """Genera y descarga un archivo Excel con la lista completa de propietarios y sus terrenos."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Propietarios"

    ws.append(["ID", "Nombre", "Apellido Paterno", "Apellido Materno", "CI", "Cantidad Terrenos", "Lotes Asignados", "Multas Pendientes", "Total Multas (Bs.)"])

    duenios = Duenio.query.order_by(Duenio.nombre.asc()).all()
    for d in duenios:
        terrenos = d.terrenos or []
        lotes_str = ", ".join(f"Lote {t.lugar} (Mz. {t.manzano})" for t in terrenos) if terrenos else "Sin terrenos"
        multas = d.multas or []
        total_multas = sum(m.monto for m in multas)

        ws.append([
            d.id,
            d.nombre,
            d.paterno or "",
            d.materno or "",
            d.ci,
            len(terrenos),
            lotes_str,
            len(multas),
            float(total_multas)
        ])

    _aplicar_estilos_excel(ws, "PADRÓN DE PROPIETARIOS")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    nombre_archivo = f"propietarios_circuata_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=nombre_archivo, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Exportar Cuotas a Excel ──────────────────────────────────────────────────
@reporte_bp.route("/reportes/exportar/cuotas")
@login_required
def exportar_cuotas():
    """Genera y descarga un archivo Excel con el detalle financiero de cuotas."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Cuotas"

    ws.append(["ID Cuota", "Título de la Cuota", "Descripción", "Propietario", "CI", "Lote", "Manzano", "Monto (Bs.)", "Estado", "Fecha Emisión"])

    cuotas = Cuota.query.order_by(Cuota.cuota_id.desc()).all()
    for c in cuotas:
        terreno = c.terreno
        dueno = terreno.dueno if terreno else None
        dueno_nombre = f"{dueno.nombre} {dueno.paterno or ''}".strip() if dueno else "N/A"
        dueno_ci = dueno.ci if dueno else "N/A"
        lugar = terreno.lugar if terreno else "N/A"
        manzano = terreno.manzano if terreno else "N/A"

        ws.append([
            c.cuota_id,
            c.titulo,
            c.descripcion or "",
            dueno_nombre,
            dueno_ci,
            lugar,
            manzano,
            float(c.monto),
            "PAGADO" if c.pagado else "PENDIENTE",
            c.fecha_creacion.strftime('%d/%m/%Y') if c.fecha_creacion else "N/A"
        ])

    _aplicar_estilos_excel(ws, "CONTROL FINANCIERO DE CUOTAS")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    nombre_archivo = f"cuotas_circuata_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=nombre_archivo, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Exportar Multas a Excel ──────────────────────────────────────────────────
@reporte_bp.route("/reportes/exportar/multas")
@login_required
def exportar_multas():
    """Genera y descarga un archivo Excel con las multas registradas."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Multas"

    ws.append(["ID Multa", "Propietario", "CI", "Tipo de Sanción", "Monto (Bs.)", "Fecha", "Descripción"])

    multas = Multa.query.order_by(Multa.multa_id.desc()).all()
    for m in multas:
        dueno = m.duenio
        dueno_nombre = f"{dueno.nombre} {dueno.paterno or ''} {dueno.materno or ''}".strip() if dueno else "N/A"
        dueno_ci = dueno.ci if dueno else "N/A"

        ws.append([
            m.multa_id,
            dueno_nombre,
            dueno_ci,
            "Inasistencia" if m.tipo == "asistencia" else "Cuota no pagada" if m.tipo == "cuota" else m.tipo,
            float(m.monto),
            m.fecha.strftime('%d/%m/%Y') if m.fecha else "N/A",
            m.descripcion or ""
        ])

    _aplicar_estilos_excel(ws, "REGISTRO DE MULTAS Y SANCIONES")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    nombre_archivo = f"multas_circuata_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=nombre_archivo, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── Estado de cuenta imprimible (PDF/Print) ──────────────────────────────────
@reporte_bp.route("/reportes/imprimir/estado-cuenta/<int:duenio_id>")
@login_required
def estado_cuenta_imprimible(duenio_id):
    """Genera una ficha de estado de cuenta lista para imprimir o guardar como PDF."""
    duenio = db.session.get(Duenio, duenio_id)
    if not duenio:
        flash("Propietario no encontrado.", "error")
        return redirect(url_for("duenio.list_duenios"))

    terrenos = duenio.terrenos or []
    multas = duenio.multas or []
    total_multas = sum(m.monto for m in multas)

    # Buscar todas las cuotas de sus terrenos
    cuotas = Cuota.query.join(Terreno).filter(Terreno.duenio_id == duenio_id).all()
    total_cuotas = sum(c.monto for c in cuotas)
    cuotas_pendientes = [c for c in cuotas if not c.pagado]
    total_adeudado = sum(c.monto for c in cuotas_pendientes) + total_multas

    return render_template(
        "estado_cuenta.html",
        duenio=duenio,
        terrenos=terrenos,
        cuotas=cuotas,
        cuotas_pendientes=cuotas_pendientes,
        multas=multas,
        total_multas=total_multas,
        total_cuotas=total_cuotas,
        total_adeudado=total_adeudado,
        fecha_emision=datetime.now().strftime('%d/%m/%Y %H:%M')
    )

