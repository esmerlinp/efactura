"""Genera los documentos comerciales PDF de VykOne."""

import os
import platform
import sys
from pathlib import Path

# Fix para WeasyPrint en macOS (Apple Silicon / Intel con Homebrew)
if platform.system() == "Darwin":
    current_dyld = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    brew_paths = ["/opt/homebrew/lib", "/usr/local/lib"]
    new_paths = [p for p in brew_paths if os.path.exists(p)]
    if current_dyld:
        new_paths.append(current_dyld)
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(new_paths)


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "contrato-servicios-estandar",
    "plan-implementacion-clientes",
    "como-solicitar-demo",
    "overview-modulos",
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
