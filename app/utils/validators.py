# utils/validators.py
# Validadores reutilizables para garantizar la integridad de los datos
# antes de interactuar con los modelos y la base de datos SQL.

import re
from typing import Tuple, Optional


def validar_texto(valor: Optional[str], nombre_campo: str = "Campo", min_len: int = 1, max_len: int = 255, requerido: bool = True) -> Tuple[bool, Optional[str], str]:
    """
    Valida y sanitiza una cadena de texto.
    Retorna: (es_valido, texto_limpio, mensaje_error)
    """
    if valor is None:
        texto = ""
    else:
        texto = str(valor).strip()

    if not texto:
        if requerido:
            return False, None, f"{nombre_campo} es obligatorio."
        return True, "", ""

    if len(texto) < min_len:
        return False, None, f"{nombre_campo} debe contener al menos {min_len} caracteres."

    if len(texto) > max_len:
        return False, None, f"{nombre_campo} no puede exceder los {max_len} caracteres."

    return True, texto, ""


def validar_ci(ci: Optional[str]) -> Tuple[bool, Optional[str], str]:
    """
    Valida que el número de carnet de identidad contenga un formato válido
    (entre 4 y 20 caracteres alfanuméricos, sin caracteres especiales inseguros).
    """
    ok, ci_limpio, err = validar_texto(ci, "Cédula de identidad (CI)", min_len=4, max_len=20, requerido=True)
    if not ok:
        return False, None, err

    # Permite números y posibles extensiones (ej. 1234567 o 1234567-1A)
    if not re.match(r'^[A-Za-z0-9\-\.]+$', ci_limpio):
        return False, None, "El CI solo debe contener números, letras y guiones válidos."

    return True, ci_limpio, ""


def validar_monto(monto_raw: any, nombre_campo: str = "Monto", min_val: float = 0.0, max_val: float = 1_000_000.0) -> Tuple[bool, Optional[float], str]:
    """
    Valida que un valor sea numérico positivo con hasta 2 decimales.
    """
    if monto_raw is None or str(monto_raw).strip() == "":
        return False, None, f"{nombre_campo} es obligatorio."

    try:
        val = float(monto_raw)
    except (ValueError, TypeError):
        return False, None, f"{nombre_campo} debe ser un valor numérico válido."

    if val < min_val:
        return False, None, f"{nombre_campo} no puede ser menor a {min_val}."

    if val > max_val:
        return False, None, f"{nombre_campo} no puede exceder {max_val:,.2f}."

    return True, round(val, 2), ""


def validar_rol(rol: Optional[str]) -> Tuple[bool, str, str]:
    """
    Valida que el rol de usuario pertenezca a la lista de roles permitidos.
    """
    roles_permitidos = ("admin", "doctor")
    r = (rol or "").strip().lower()
    if r not in roles_permitidos:
        return False, "doctor", f"El rol '{rol}' no es válido. Opciones permitidas: {', '.join(roles_permitidos)}."
    return True, r, ""


def validar_tipo_multa(tipo: Optional[str]) -> Tuple[bool, str, str]:
    """
    Valida el tipo de multa ('asistencia' o 'cuota').
    """
    tipos_validos = ("asistencia", "cuota")
    t = (tipo or "").strip().lower()
    if t not in tipos_validos:
        return False, "", f"El tipo de multa debe ser 'asistencia' o 'cuota'."
    return True, t, ""

