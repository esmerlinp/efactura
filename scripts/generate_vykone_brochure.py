"""Genera la presentación comercial de VykOne en PDF."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "comercial" / "vykone-brochure-clientes.html"
OUTPUT = ROOT / "docs" / "comercial" / "vykone-brochure-clientes.pdf"


def main() -> int:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        print(
            "No fue posible cargar WeasyPrint. Instala sus dependencias nativas "
            "(en macOS: brew install pango) y vuelve a ejecutar el script.",
            file=sys.stderr,
        )
        print(f"Detalle: {exc}", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    HTML(filename=str(SOURCE), base_url=str(SOURCE.parent)).write_pdf(str(OUTPUT))
    print(f"PDF generado: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
