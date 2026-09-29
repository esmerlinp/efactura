"""Genera los documentos comerciales PDF de VykOne."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "contrato-servicios-estandar",
    "plan-implementacion-clientes",
)


def main() -> int:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        print("No fue posible cargar WeasyPrint. En macOS instala sus dependencias con: brew install pango", file=sys.stderr)
        print(f"Detalle: {exc}", file=sys.stderr)
        return 1

    output_dir = ROOT / "docs" / "comercial"
    for name in DOCUMENTS:
        source = output_dir / f"{name}.html"
        output = output_dir / f"{name}.pdf"
        HTML(filename=str(source), base_url=str(output_dir)).write_pdf(str(output))
        print(f"PDF generado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
