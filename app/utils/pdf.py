"""Opciones de generación de PDFs (WeasyPrint).

El peso de los PDFs generados se controla desde el entorno:
- PDF_OPTIMIZE_IMAGES: re-encoda imágenes eficientemente.
- PDF_DPI: resolución máxima de imágenes embebidas (el logo de la empresa
  se baja a esta resolución si su DPI efectivo lo excede).
- PDF_JPEG_QUALITY: calidad de las imágenes JPEG embebidas (0-95).
"""

from config import Config


def pdf_write_options() -> dict:
    """Retorna los kwargs para HTML.write_pdf() según la configuración."""
    opts = {'optimize_images': Config.PDF_OPTIMIZE_IMAGES}
    if Config.PDF_DPI:
        opts['dpi'] = Config.PDF_DPI
    if Config.PDF_JPEG_QUALITY:
        opts['jpeg_quality'] = Config.PDF_JPEG_QUALITY
    return opts
