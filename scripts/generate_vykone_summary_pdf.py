#!/usr/bin/env python3
"""
Genera el PDF del Resumen Ejecutivo y Capacidades de VykOne ERP
utilizando WeasyPrint y el motor de renderizado del sistema de diseño.
"""

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
SOURCE_HTML = ROOT / "docs" / "vykone-resumen-ejecutivo.html"
OUTPUT_PDF_DOCS = ROOT / "docs" / "VykOne_ERP_Resumen_Ejecutivo.pdf"
OUTPUT_PDF_ROOT = ROOT / "VykOne_ERP_Resumen_Ejecutivo.pdf"


def main() -> int:
    print(f"Cargando plantilla: {SOURCE_HTML}")
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        print(
            "Error al importar WeasyPrint. Verifica que las dependencias nativas (pango, cairo, gobject) "
            "estén instaladas en el sistema (ej. `brew install pango`).",
            file=sys.stderr,
        )
        print(f"Detalle: {exc}", file=sys.stderr)
        return 1

    OUTPUT_PDF_DOCS.parent.mkdir(parents=True, exist_ok=True)

    print("Renderizando PDF con WeasyPrint...")
    html_doc = HTML(filename=str(SOURCE_HTML), base_url=str(SOURCE_HTML.parent))
    html_doc.write_pdf(str(OUTPUT_PDF_DOCS))
    print(f"✅ PDF generado exitosamente en: {OUTPUT_PDF_DOCS}")

    # También guardamos una copia en el directorio raíz para acceso directo
    html_doc.write_pdf(str(OUTPUT_PDF_ROOT))
    print(f"✅ Copia guardada en raíz: {OUTPUT_PDF_ROOT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
