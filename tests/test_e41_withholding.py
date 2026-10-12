import pytest
from app.web.invoices import _build_supplier_invoice_ecf_payload
from app.services.dgii_xml_builder import DgiiXmlBuilder
import xml.etree.ElementTree as ET


def test_e41_payload_calculates_isr_on_subtotal_ex_itbis():
    """Verifica que el payload de un comprobante E41 calcule la retención de ISR
    estrictamente sobre el subtotal sin ITBIS (renta/ganancias) y no sobre el total con ITBIS.
    """
    inv_data = {
        "id": "test-e41-01",
        "ecfType": "E41",
        "encf": "E410000000001",
        "supplierName": "Juan Pérez",
        "supplierRnc": "00100000001",
        "date": "2026-10-11",
        "dueDate": "2026-10-31",
        "paymentType": "Contado",
        "subtotal": 10000.0,
        "discount": 0.0,
        "itbis": 1800.0,
        "total": 11800.0,
        "retainedISR": 0.10,    # 10%
        "retainedITBIS": 1.00,  # 100%
        "items": [
            {
                "name": "Honorarios Profesionales",
                "quantity": 1.0,
                "unitPrice": 10000.0,
                "subtotal": 10000.0,
                "itbisRate": 0.18,
                "unit": "Servicio",
                "accountingAccountId": "601-01",
            }
        ],
    }

    payload = _build_supplier_invoice_ecf_payload(inv_data)

    # 10% de 10,000 = 1,000 (NO 1,180)
    assert payload["retainedISR"] == 1000.0, f"retainedISR esperado 1000.0, obtenido {payload['retainedISR']}"
    assert payload["retainedITBIS"] == 1800.0, f"retainedITBIS esperado 1800.0, obtenido {payload['retainedITBIS']}"

    # Retención a nivel de ítem para E41
    item = payload["items"][0]
    assert item.get("retainedISR") == 1000.0, f"Item retainedISR esperado 1000.0, obtenido {item.get('retainedISR')}"
    assert item.get("retainedITBIS") == 1800.0, f"Item retainedITBIS esperado 1800.0, obtenido {item.get('retainedITBIS')}"


def test_e41_xml_builder_cuadratura_retenciones():
    """Verifica que el XML de E41 generado tenga cuadratura estricta:
    sum(DetallesItems/Item/Retencion/MontoISRRetenido) == Totales/TotalISRRetencion
    y que la base no incluya ITBIS.
    """
    company = {
        "rnc": "133753652",
        "companyName": "EMPRESA DE PRUEBA SRL",
        "direccion": "AV. PRINCIPAL NO. 1",
        "municipio": "010100",
        "provincia": "010000",
        "telefono": "8095551234",
        "correo": "facturacion@empresa.com",
    }

    inv_data = {
        "id": "test-e41-multi",
        "ecfType": "E41",
        "encf": "E410000000002",
        "supplierName": "Carlos Abogado",
        "supplierRnc": "00122233344",
        "date": "2026-10-11",
        "dueDate": "2026-10-31",
        "paymentType": "Contado",
        "subtotal": 15000.0,
        "discount": 0.0,
        "itbis": 2700.0,
        "total": 17700.0,
        "retainedISR": 0.10,    # 10%
        "retainedITBIS": 1.00,  # 100%
        "items": [
            {
                "name": "Asesoría Legal 1",
                "quantity": 1.0,
                "unitPrice": 5000.0,
                "subtotal": 5000.0,
                "itbisRate": 0.18,
                "unit": "Servicio",
            },
            {
                "name": "Asesoría Legal 2",
                "quantity": 1.0,
                "unitPrice": 10000.0,
                "subtotal": 10000.0,
                "itbisRate": 0.18,
                "unit": "Servicio",
            },
        ],
    }

    payload = _build_supplier_invoice_ecf_payload(inv_data)
    xml_bytes = DgiiXmlBuilder.build_invoice_xml(company, payload)
    root = ET.fromstring(xml_bytes)

    # Verificar Totales
    total_isr_ret = float(root.findtext(".//Totales/TotalISRRetencion", "0"))
    total_itbis_ret = float(root.findtext(".//Totales/TotalITBISRetenido", "0"))
    assert total_isr_ret == 1500.0, f"TotalISRRetencion esperado 1500.0, obtenido {total_isr_ret}"
    assert total_itbis_ret == 2700.0, f"TotalITBISRetenido esperado 2700.0, obtenido {total_itbis_ret}"

    # Verificar Items y Cuadratura sum(Item) == Totales
    item_isr_sum = 0.0
    item_itbis_sum = 0.0
    for item in root.findall(".//DetallesItems/Item"):
        monto_isr = float(item.findtext(".//Retencion/MontoISRRetenido", "0"))
        monto_itbis = float(item.findtext(".//Retencion/MontoITBISRetenido", "0"))
        item_isr_sum += monto_isr
        item_itbis_sum += monto_itbis

    assert round(item_isr_sum, 2) == total_isr_ret, f"Suma ítems ISR ({item_isr_sum}) ≠ TotalISRRetencion ({total_isr_ret})"
    assert round(item_itbis_sum, 2) == total_itbis_ret, f"Suma ítems ITBIS ({item_itbis_sum}) ≠ TotalITBISRetenido ({total_itbis_ret})"
