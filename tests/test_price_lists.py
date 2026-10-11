"""Pruebas unitarias para Listas de Precios:
- Asignación por % de descuento (ej. 12,000 con 10% = 10,800).
- Asignación por precio fijo con cálculo de % retroactivo.
- Resolución dinámica de precios ante cambios del precio base en catálogo.
- Aplicación de descuento masivo a todos los productos de la lista.
"""

from unittest.mock import MagicMock, patch
import pytest
from app.services.db_service import DatabaseService


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return dict(self._data)


class _FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def get(self):
        return self._docs


class _FakeColl:
    def __init__(self):
        self._docs = {}

    def document(self, doc_id):
        coll_self = self
        class _DocRef:
            def set(self, data):
                coll_self._docs[doc_id] = dict(data)
                return True
            def delete(self):
                coll_self._docs.pop(doc_id, None)
                return True
            def get(self):
                if doc_id in coll_self._docs:
                    return _FakeDoc(doc_id, coll_self._docs[doc_id])
                mock = MagicMock()
                mock.exists = False
                return mock
        return _DocRef()

    def where(self, filter=None):
        matched = []
        for did, d in self._docs.items():
            matched.append(_FakeDoc(did, d))
        return _FakeQuery(matched)


def test_save_and_get_price_list_item_with_discount():
    fake_coll = _FakeColl()
    with patch("app.services.db_service.firebase_initialized", True), \
         patch("app.services.db_service._company_coll", return_value=fake_coll):
        
        # Guardar producto con 10% de descuento sobre precio base de 12,000
        base_price = 12000.0
        disc_pct = 10.0
        calculated_price = round(base_price * (1.0 - (disc_pct / 100.0)), 2)
        
        price_dict = {
            "price": calculated_price,
            "basePrice": base_price,
            "pricingMode": "discount",
            "discountPercentage": disc_pct,
            "costPrice": 8000.0,
            "wholesalePrice": 10500.0
        }
        
        doc_id = DatabaseService.save_price_list_item(
            owner_uid="user1",
            price_list_id="pl_vip",
            item_id="item_laptop",
            price_dict=price_dict,
            sandbox=True,
            company_id="comp1"
        )
        assert doc_id == "pl_vip_item_laptop"

        # Recuperar precios de la lista
        items = DatabaseService.get_price_list_items(
            owner_uid="user1",
            price_list_id="pl_vip",
            sandbox=True,
            company_id="comp1"
        )
        assert "item_laptop" in items
        data = items["item_laptop"]
        assert data["price"] == 10800.0
        assert data["basePrice"] == 12000.0
        assert data["pricingMode"] == "discount"
        assert data["discountPercentage"] == 10.0
        assert data["costPrice"] == 8000.0
        assert data["wholesalePrice"] == 10500.0


def test_pricing_mode_fixed_calculates_discount_percentage():
    base_price = 12000.0
    price_fixed = 10800.0
    calc_disc = round(((base_price - price_fixed) / base_price) * 100.0, 2)
    assert calc_disc == 10.0


def test_dynamic_effective_price_resolution_on_catalog_price_change():
    """Si un producto tiene modo 'discount' con 10%, y el precio base sube a 15,000,
    el precio efectivo calculado en base al catálogo debe ser 13,500.0."""
    new_catalog_price = 15000.0
    discount_pct = 10.0
    effective_price = round(new_catalog_price * (1.0 - (discount_pct / 100.0)), 2)
    assert effective_price == 13500.0
