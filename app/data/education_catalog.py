"""Catálogo oficial de niveles educativos SIRLA (DGT-2/3/4/5).

Códigos del Ministerio de Trabajo de República Dominicana usados en el campo
"Nivel Educación" de los archivos de carga de trabajadores (SIRLA).

Fuente: especificación oficial SIRLA DGT-2/3/4/5.
"""

SIRLA_EDUCATION_LEVELS = [
    {"code": "4744", "label": "Educación Nivel Inicial / Primer ciclo nivel inicial"},
    {"code": "4745", "label": "Educación Nivel Inicial / Primer ciclo nivel inicial educación especial"},
    {"code": "4746", "label": "Educación Nivel Inicial / Segundo ciclo nivel inicial"},
    {"code": "4747", "label": "Educación Nivel Inicial / Segundo ciclo nivel inicial educación especial"},
    {"code": "4748", "label": "Educación Nivel Primario / Primer y segundo ciclo nivel primario"},
    {"code": "4749", "label": "Educación Nivel Primario / Primer y segundo ciclo nivel primario educación especial"},
    {"code": "4750", "label": "Educación Nivel Primario / Educación básica adultos semipresencial"},
    {"code": "4751", "label": "Educación Nivel Secundario Primer Ciclo / General"},
    {"code": "4752", "label": "Educación Nivel Secundario Primer Ciclo / Primer ciclo de educación nivel secundario"},
    {"code": "4753", "label": "Educación Nivel Secundario Primer Ciclo / Educación básica adultos semipresencial"},
    {"code": "4754", "label": "Educación Nivel Secundario Primer Ciclo / Profesional"},
    {"code": "4755", "label": "Educación Nivel Secundario Primer Ciclo / Técnico básico"},
    {"code": "4756", "label": "Educación Nivel Secundario Primer Ciclo / Técnico básico adaptado a educación especial"},
    {"code": "4757", "label": "Educación Nivel Secundario Primer Ciclo / Técnico básico adaptado a educación de jóvenes y adultos"},
    {"code": "4758", "label": "Educación Nivel Secundario Segundo Ciclo / Modalidad Académica"},
    {"code": "4759", "label": "Educación Nivel Secundario Segundo Ciclo / Bachillerato académico"},
    {"code": "4760", "label": "Educación Nivel Secundario Segundo Ciclo / Educación media a distancia y semipresencial para jóvenes y adultos"},
    {"code": "4761", "label": "Educación Nivel Secundario Segundo Ciclo / Modalidad Técnico Profesional y Modalidad en Artes"},
    {"code": "4762", "label": "Educación Nivel Secundario Segundo Ciclo / Bachillerato en artes"},
    {"code": "4763", "label": "Educación Nivel Secundario Segundo Ciclo / Bachillerato técnico"},
    {"code": "4764", "label": "Educación Técnico Superior o Tecnólogo / Nivel técnico superior o tecnólogo"},
    {"code": "4765", "label": "Grado / Licenciatura"},
    {"code": "4766", "label": "Grado / Medicina"},
    {"code": "4767", "label": "Grado / Odontología"},
    {"code": "4768", "label": "Grado / Ingeniería"},
    {"code": "4769", "label": "Grado / Arquitectura"},
    {"code": "4770", "label": "Maestría y Especialización / Académica"},
    {"code": "4771", "label": "Maestría y Especialización / Especialización"},
    {"code": "4772", "label": "Maestría y Especialización / Maestría"},
    {"code": "4773", "label": "Maestría y Especialización / Especialidad médica"},
    {"code": "4774", "label": "Doctorado / Doctorado"},
    {"code": "4775", "label": "Educación No Formal / Programas de alfabetización de jóvenes y adultos"},
    {"code": "4776", "label": "Educación No Formal / Programa de formación basado en competencia laboral. Modalidad habilitación"},
    {"code": "4777", "label": "Educación No Formal / Programa de formación basado en competencia laboral. Modalidad complementación"},
    {"code": "4778", "label": "Educación No Formal / Programa de técnico. Modalidad formación continua en centro"},
    {"code": "4779", "label": "Educación No Formal / Programa de técnico. Modalidad formación dual"},
    {"code": "4780", "label": "Educación No Formal / Programas de maestro técnico"},
    {"code": "4781", "label": "Educación No Formal / Programa de formación técnico profesional"},
    {"code": "4782", "label": "Educación No Formal / Programas de habilitación para el trabajo"},
]

_EDUCATION_BY_CODE = {e["code"]: e["label"] for e in SIRLA_EDUCATION_LEVELS}


def is_valid_education_code(code) -> bool:
    """True si el código es un nivel educativo oficial SIRLA."""
    return str(code or "").strip() in _EDUCATION_BY_CODE


def get_education_label(code) -> str:
    """Devuelve la descripción del código educativo oficial, o '' si no existe."""
    return _EDUCATION_BY_CODE.get(str(code or "").strip(), "")
