"""DependentsTSSService — Generación del archivo RD (Registro de Dependientes Adicionales).

Formato: texto de ancho fijo SUIRPLUS v5.0 para carga en portal TSS.
Especificación: Instructivo para Construcción de Archivos de Dependientes Adicionales v5.0 — TSS.
"""

import unicodedata
from datetime import datetime
from typing import Optional


# Códigos de parentesco permitidos por TSS para dependientes adicionales (ascendientes 1er grado)
_TSS_RD_VALID_RELATIONSHIPS = {"padre", "madre"}

# Longitud total del registro detalle según layout oficial RD v5.0
_DETALLE_LENGTH = 158


def _ascii_upper(s: str) -> str:
    """Convierte a uppercase ASCII: elimina tildes, ñ→n, etc."""
    nfkd = unicodedata.normalize("NFKD", s or "")
    return nfkd.encode("ascii", "ignore").decode("ascii").upper()


def _clean_doc(doc: str) -> str:
    """Limpia documento: solo dígitos, sin guiones ni caracteres especiales."""
    return "".join(c for c in (doc or "") if c.isdigit())


def validate_rd_export(employees: list, dependents_map: dict) -> list:
    """Valida que los datos estén listos para exportar el archivo RD.

    Solo valida los dependientes adicionales elegibles (los dependientes directos o
    informativos no forman parte del archivo RD de la TSS).

    Retorna lista de errores. Si está vacía, la exportación puede proceder.
    """
    errors = []
    for emp in employees:
        emp_id = emp.get("id", "")
        emp_name = f"{emp.get('firstName', '')} {emp.get('firstLastName', '')}".strip()

        tss_key = (emp.get("tssKey", "") or "").strip()
        if not tss_key:
            errors.append(f"Empleado {emp_name or emp_id}: sin clave de nómina TSS (tssKey)")

        cedula = _clean_doc(emp.get("cedula", "") or emp.get("idNumber", ""))
        if len(cedula) < 11:
            errors.append(f"Empleado {emp_name or emp_id}: documento titular inválido ({len(cedula)} dígitos, se requieren 11)")

        deps = [d for d in dependents_map.get(emp_id, []) if d.get("active", True)]
        for dep in deps:
            cat = dep.get("category", "")
            rel = (dep.get("relationshipCode", "") or "").strip()
            eligibility = dep.get("eligibilityStatus", "eligible")

            # Solo validar dependientes adicionales destinados a reporte RD
            if cat in ("direct", "informational") or eligibility == "ineligible":
                continue
            if not cat and rel not in _TSS_RD_VALID_RELATIONSHIPS:
                continue

            dep_name = f"{dep.get('firstName', '')} {dep.get('firstLastName', '')}".strip()
            dep_id = dep.get("id", "")

            if not dep.get("docType") or dep["docType"] not in ("C", "N"):
                errors.append(f"Dependiente {dep_name or dep_id}: tipo de documento inválido (debe ser C o N)")

            id_num = _clean_doc(dep.get("idNumber", "") or "")
            if not id_num:
                errors.append(f"Dependiente {dep_name or dep_id}: sin documento de identidad")

            if rel not in _TSS_RD_VALID_RELATIONSHIPS:
                errors.append(f"Dependiente {dep_name or dep_id}: parentesco '{rel}' no es admitido en el archivo RD (solo ascendientes en 1er grado: padre/madre)")

    return errors


def generate_tss_rd(
    employees: list,
    employer_rnc: str,
    dependents_by_employee: Optional[dict] = None,
    company_id: str = "",
    sandbox: bool = True,
) -> dict:
    """Genera archivo RD — Registro de Dependientes Adicionales en formato SUIRPLUS v5.0.

    Formato:
      E = Encabezado (14 caracteres): "E" + "RD" + RNC(11)
      D = Detalle (158 caracteres): D + clave(3) + tipo_tit(1) + doc_tit(11) +
            nombres(40) + apellido1(40) + apellido2(40) + tipo_dep(1) + doc_dep(11)
            + filler(10)
      S = Sumario (7 caracteres): "S" + total_registros(6)

    Args:
        employees: Lista de empleados (dicts con datos del modelo Employee).
        employer_rnc: RNC o Cédula del empleador (sin guiones, 11 dígitos).
        dependents_by_employee: Dict {employee_id: [dependent_dict, ...]} con
            dependientes pre-cargados. Si es None, no se incluirán dependientes.
        company_id: ID de la empresa.
        sandbox: Flag de sandbox.

    Returns:
        Dict con {content, filename, total_dependientes, total_registros, errors}.
    """
    rnc = _clean_doc(employer_rnc or "")
    if len(rnc) < 11:
        rnc = rnc.rjust(11)
    rnc = rnc[-11:]

    now = datetime.now()
    periodo_mmaaaa = now.strftime("%m%Y")

    valid_rels = _TSS_RD_VALID_RELATIONSHIPS
    output_lines = []

    # ═══════════════════════════════════════════════════════════════
    # ENCABEZADO — 14 caracteres
    # Pos: 1(1) E, 2-3(2) RD, 4-14(11) RNC
    # ═══════════════════════════════════════════════════════════════
    header = f"ERD{rnc}"
    assert len(header) == 14, f"Encabezado RD: {len(header)} chars, deben ser 14"
    output_lines.append(header)

    # ═══════════════════════════════════════════════════════════════
    # DETALLES — 158 caracteres c/u
    # ═══════════════════════════════════════════════════════════════
    dependientes_contados = 0
    deps_loaded = dependents_by_employee or {}

    for emp in employees:
        emp_id = emp.get("id", "")
        if not emp_id:
            continue

        tss_key = (emp.get("tssKey", "") or "").strip()[:3]
        if not tss_key:
            continue

        # Tipo documento titular: C=Cédula, N=NSS
        id_type = (emp.get("idType", "") or "cedula").lower()
        titular_doc_type = "C" if id_type == "cedula" else "N"

        # Documento titular (11)
        titular_doc = _clean_doc(emp.get("cedula", "") or emp.get("idNumber", ""))
        if len(titular_doc) < 11:
            continue
        titular_doc = titular_doc[-11:]

        deps = deps_loaded.get(emp_id, [])
        for dep in deps:
            if not dep.get("active", True):
                continue

            cat = dep.get("category", "")
            if cat in ("direct", "informational"):
                continue

            eligibility = dep.get("eligibilityStatus", "eligible")
            if eligibility == "ineligible":
                continue

            rel = (dep.get("relationshipCode", "") or "").strip()
            if rel not in valid_rels:
                continue

            dep_doc_type = dep.get("docType", "C") or "C"
            if dep_doc_type not in ("C", "N"):
                dep_doc_type = "C"

            # Documento dependiente (11) — Pos 148-158
            dep_doc = _clean_doc(dep.get("idNumber", "") or "")
            if not dep_doc:
                continue
            dep_doc = dep_doc.ljust(11)[:11]

            # Nombres (50 chars) — Pos 17-66: primer y segundo nombre concatenados
            nombres_raw = f"{dep.get('firstName', '')} {dep.get('middleName', '')}".strip()
            nombres = _ascii_upper(nombres_raw).ljust(50)[:50]

            # Primer apellido (40 chars) — Pos 67-106
            apellido1 = _ascii_upper(dep.get("firstLastName", "") or "").ljust(40)[:40]

            # Segundo apellido (40 chars) — Pos 107-146
            apellido2 = _ascii_upper(dep.get("secondLastName", "") or "").ljust(40)[:40]

            # ═══════════════════════════════════════════════════════════════
            # Layout oficial TSS RD v5.0 (158 caracteres):
            # Pos 1:       Tipo Registro ("D", 1)
            # Pos 2-4:     Clave Nómina TSS titular (3)
            # Pos 5:       Tipo Documento titular ("C"/"N", 1)
            # Pos 6-16:    Número Documento titular (11)
            # Pos 17-66:   Nombres dependiente (50)
            # Pos 67-106:  Primer apellido dependiente (40)
            # Pos 107-146: Segundo apellido dependiente (40)
            # Pos 147:     Tipo Documento dependiente ("C"/"N", 1)
            # Pos 148-158: Número Documento dependiente (11)
            # ═══════════════════════════════════════════════════════════════
            detalle = (
                "D"
                + tss_key.rjust(3)
                + titular_doc_type
                + titular_doc
                + nombres
                + apellido1
                + apellido2
                + dep_doc_type
                + dep_doc
            )

            assert len(detalle) == _DETALLE_LENGTH, (
                f"Detalle RD: {len(detalle)} chars, deben ser {_DETALLE_LENGTH}"
            )
            output_lines.append(detalle)
            dependientes_contados += 1

    # ═══════════════════════════════════════════════════════════════
    # SUMARIO — 7 caracteres
    # Pos: 1(1) S, 2-7(6) total registros (E + D's + S)
    # ═══════════════════════════════════════════════════════════════
    total_registros = 1 + dependientes_contados + 1
    trailer = f"S{total_registros:06d}"
    assert len(trailer) == 7, f"Sumario RD: {len(trailer)} chars, deben ser 7"
    output_lines.append(trailer)

    content = "\n".join(output_lines) + "\n"

    rnc_clean = _clean_doc(employer_rnc or "000000000")
    filename = f"{rnc_clean}_{periodo_mmaaaa}_RD.txt"

    return {
        "content": content,
        "filename": filename,
        "periodo": periodo_mmaaaa,
        "total_dependientes": dependientes_contados,
        "total_registros": total_registros,
        "resumen": {
            "tipo_archivo": "RD",
            "empleados_procesados": len([e for e in employees if (e.get("tssKey") or "").strip()]),
            "dependientes_exportados": dependientes_contados,
            "total_registros": total_registros,
        },
    }
