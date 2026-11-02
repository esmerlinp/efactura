"""Verifica la estructura histórica IT-1 contra la plantilla XLS original.

Requiere ``xlrd`` en el entorno de desarrollo. No escribe el libro ni genera
archivos derivados. Se ejecuta antes de habilitar reglas fiscales productivas.
"""

from pathlib import Path

from app.fiscal_forms.it1_rules import ANNEX_A_SECTIONS, IT1_SECTIONS, IT1_RULES_VERSION


def main():
    source = Path(__file__).parents[1] / "docs" / "IT-1-2020.xls"
    if not source.exists():
        raise SystemExit(f"No existe la plantilla oficial: {source}")
    try:
        import xlrd
    except ImportError as exc:
        raise SystemExit("Instale xlrd para ejecutar la verificación XLS oficial.") from exc
    book = xlrd.open_workbook(str(source), formatting_info=False, on_demand=True)
    names = set(book.sheet_names())
    required = {"Anexo A", "IT-1"}
    missing = required - names
    if missing:
        raise SystemExit(f"Faltan hojas oficiales: {sorted(missing)}")
    print(f"IT-1 histórico {IT1_RULES_VERSION.version}: hojas verificadas: {sorted(required)}")
    print(f"Anexo A: {sum(len(section) for section in ANNEX_A_SECTIONS.values())} casillas catalogadas")
    print(f"IT-1: {sum(len(section) for section in IT1_SECTIONS.values())} casillas catalogadas")
    print("La plantilla original no fue modificada.")


if __name__ == "__main__":
    main()
