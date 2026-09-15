"""Tests de normalización de logos (app/utils/images.py)."""

import io
import random

import pytest
from PIL import Image

from app.utils.images import (
    MAX_LOGO_DIMENSION,
    TARGET_LOGO_BYTES,
    normalize_logo_image,
)


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _noise_rgba(size):
    rng = random.Random(1234)
    img = Image.new("RGBA", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256), 255)
    return img


def test_svg_passthrough():
    raw = b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'></svg>"
    out, mime, ext = normalize_logo_image(raw, "image/svg+xml")
    assert out == raw
    assert mime == "image/svg+xml"
    assert ext == "svg"


def test_oversized_rejected():
    raw = b"x" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        normalize_logo_image(raw, "image/png")


def test_invalid_image_rejected():
    with pytest.raises(ValueError):
        normalize_logo_image(b"esto no es una imagen", "image/png")


def test_downscales_large_raster():
    img = Image.new("RGB", (2000, 2000), (10, 120, 200))
    out, mime, ext = normalize_logo_image(_png_bytes(img), "image/png")
    decoded = Image.open(io.BytesIO(out))
    assert max(decoded.size) <= MAX_LOGO_DIMENSION


def test_targets_small_weight():
    out, mime, ext = normalize_logo_image(_png_bytes(_noise_rgba(800)), "image/png")
    assert len(out) <= TARGET_LOGO_BYTES
    assert mime in ("image/png", "image/jpeg")
