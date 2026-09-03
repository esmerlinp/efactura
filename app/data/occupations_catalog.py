"""Catálogo oficial de ocupaciones SIRLA (Ministerio de Trabajo RD).

Códigos de ocupación oficiales utilizados en los archivos de carga de
trabajadores SIRLA (DGT-3/DGT-4/DGT-5). El campo "Ocupación" de estos
archivos es numérico de 6 posiciones; el código se almacena sin ceros y se
formatea a 6 posiciones al generar el TXT (ej. 6086 -> "006086").
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
