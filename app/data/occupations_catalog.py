"""Catálogo Nacional de Ocupaciones (CNO-2019) adaptado de CIUO-08.

Fuente: Oficina Nacional de Estadística (ONE) — Clasificación Nacional de Ocupaciones 2019
Resolución No. 18-21 que establece la CNO-2019 en República Dominicana.
Usado por el Ministerio de Trabajo en formularios DGT-3/DGT-4 vía SIRLA.
"""

import json
import os

_OCCUPATIONS = None

def _load_catalog():
    global _OCCUPATIONS
    if _OCCUPATIONS is not None:
        return _OCCUPATIONS
    path = os.path.join(os.path.dirname(__file__), "occupations_catalog.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            _OCCUPATIONS = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _OCCUPATIONS = []
    return _OCCUPATIONS

def get_occupation(code: str) -> dict | None:
    for oc in _load_catalog():
        if oc["code"] == code:
            return oc
    return None

def get_occupation_name(code: str) -> str:
    oc = get_occupation(code)
    return oc["name"] if oc else ""

OCCUPATIONS = _load_catalog()
