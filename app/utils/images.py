"""Normalización de imágenes subidas (logos de empresa).

El objetivo es evitar guardar logos más pesados de lo necesario: se re-escalan a
un tamaño máximo, se re-codifican optimizados y se apunta a un peso objetivo.
Así el ``logoBase64`` siempre cabe en Firestore y los PDFs de WeasyPrint lo
renderizan sin depender de una URL remota inaccesible.
"""

import io

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_LOGO_DIMENSION = 1200
TARGET_LOGO_BYTES = 250 * 1024


def normalize_logo_image(file_bytes, content_type=""):
    """Normaliza una imagen de logo y devuelve ``(bytes, mime, ext)``.

    - SVG: se devuelve tal cual (ya es texto liviano).
    - Raster (PNG/JPEG/WebP/GIF): re-escala a ``MAX_LOGO_DIMENSION``, re-codifica
      optimizado y reduce dimensiones hasta acercarse a ``TARGET_LOGO_BYTES``.
    """
    mime = (content_type or "").split(";")[0].strip().lower()

    if mime == "image/svg+xml":
        return file_bytes, "image/svg+xml", "svg"

    if not file_bytes or len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("La imagen excede el tamaño permitido (5 MB).")

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.load()
    except Exception as e:
        raise ValueError("El archivo no es una imagen válida.") from e

    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_LOGO_DIMENSION, MAX_LOGO_DIMENSION), Image.LANCZOS)

    img = _as_rgba_or_rgb(img)

    out_bytes, out_mime, out_ext = _encode_under_target(img)

    return out_bytes, out_mime, out_ext


def _as_rgba_or_rgb(img):
    """Convierte a un modo sin paleta para poder re-codificar de forma estable."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        return img.convert("RGBA")
    if img.mode == "P":
        return img.convert("RGB")
    if img.mode not in ("RGB", "RGBA"):
        return img.convert("RGBA")
    return img


def _encode_under_target(img):
    """Re-codifica el logo procurando no superar ``TARGET_LOGO_BYTES``.

    Devuelve ``(bytes, mime, ext)``. Si la imagen es opaca prefiere JPEG; si tiene
    transparencia mantiene PNG y reduce dimensiones iterativamente si hace falta.
    """
    has_alpha = img.mode in ("RGBA", "LA")

    # Intento 1: PNG optimizado (lossless) si tiene alpha, JPEG q=85 si es opaco.
    if has_alpha:
        out = _encode_png(img)
        if len(out) <= TARGET_LOGO_BYTES:
            return out, "image/png", "png"
    else:
        jpeg = _encode_jpeg(img, quality=85)
        png = _encode_png(img)
        out = jpeg if len(jpeg) <= len(png) else png
        if len(out) <= TARGET_LOGO_BYTES:
            return out, ("image/jpeg" if out is jpeg else "image/png"), ("jpg" if out is jpeg else "png")

    # Intento 2: reducir dimensiones iterativamente hasta caber.
    scale = 0.8
    cur = img
    while scale > 0.05:
        w = max(1, int(cur.width * scale))
        h = max(1, int(cur.height * scale))
        cur = cur.resize((w, h), Image.LANCZOS)
        if has_alpha:
            out = _encode_png(cur)
            if len(out) <= TARGET_LOGO_BYTES:
                return out, "image/png", "png"
        else:
            jpeg = _encode_jpeg(cur, quality=85)
            if len(jpeg) <= TARGET_LOGO_BYTES:
                return jpeg, "image/jpeg", "jpg"
        scale *= 0.8

    # Último recurso: la versión más pequeña que se pudo obtener.
    if has_alpha:
        return _encode_png(cur), "image/png", "png"
    jpeg = _encode_jpeg(cur, quality=80)
    return jpeg, "image/jpeg", "jpg"


def _encode_png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _encode_jpeg(img, quality):
    rgb = img.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
