import sys
from app.services.alanube import AlanubeService

def test_payload_generation():
    print("🧪 Iniciando pruebas de generación de payload para Alanube API...")

    # 1. Datos simulados del emisor y factura en USD
    company_profile = {
        "companyRNC": "132-10912-2",
        "companyName": "Tecnología Dominicana SRL",
        "tradeName": "TecnoDom",
        "companyAddress": "Av. Winston Churchill #1012, Santo Domingo",
        "companyPhone": "809-555-0199, 809-555-0200",
        "companyEmail": "correo@emisor.com",
        "municipality": "Santo Domingo Este", # Debe ser reemplazado por código por defecto o conservado si es código
        "province": "010000"                 # Ya es un código, debe conservarse
    }

    invoice_data = {
        "ecfType": "Factura de Crédito Fiscal (E31)",
        "encf": "E310000000005",
        "currency": "USD",
        "exchangeRate": 56.8,
        "paymentType": "Contado",
        "clientRNC": "132250011",
        "clientName": "Adatum Corporation",
        "clientAddress": "Station Road, 21",
        "clientContact": "Robert Townes",
        "clientEmail": "gerard.diaz@kcpdynamics.com",
        "subtotal": 56.80,
        "totalITBIS": 10.22,
        "total": 67.02,
        "comentario": "Realizar pago en el Banco Popular",
        "notes": "Comentario secundario",
        "invoiceNumber": "FAC-000456789",
        "internalInvoiceNumber": 456789,
        "internalOrderNumber": "562344",
        "saleArea": "Santo Domingo Este",
        "saleRoute": "Ruta 1",
        "date": "2023-09-05T12:00:00",
        "items": [
            {
                "code": "001",
                "name": "ALMOHADILLA PARA ROLL-ON",
                "quantity": 1,
                "price": 56.8,
                "subtotal": 56.8,
                "itbisRate": 0.18,
                "type": "Bien"
            }
        ]
    }

    # Limpiar guiones
    company_rnc = company_profile["companyRNC"].replace("-", "").strip()
    client_rnc = invoice_data["clientRNC"].replace("-", "").strip()
    number_code = "31"
    short_code = "E31"

    # Generar payload
    payload = AlanubeService.build_payload(
        company_profile, invoice_data, company_rnc, client_rnc, number_code, short_code
    )

    # 1. Verificar idDoc
    id_doc = payload["idDoc"]
    print("• Validando idDoc...")
    assert id_doc["encf"] == "E310000000005"
    assert id_doc["taxAmountIndicator"] == 0
    assert id_doc["incomeType"] == 1
    assert id_doc["paymentType"] == 1

    # 2. Verificar sender
    sender = payload["sender"]
    print("• Validando sender...")
    assert sender["rnc"] == "132109122"
    assert sender["companyName"] == "Tecnología Dominicana SRL"
    assert sender["tradename"] == "TecnoDom"
    assert sender["branchOffice"] == "Sucursal Principal"
    assert sender["address"] == "Av. Winston Churchill #1012, Santo Domingo"
    assert sender["municipality"] == "010101" # Default por no ser código
    assert sender["province"] == "010000"     # Conservado
    assert sender["phoneNumber"] == ["809-555-0199", "809-555-0200"]
    assert sender["mail"] == "correo@emisor.com"
    assert sender["economicActivity"] == "Actividad Comercial"
    assert sender["sellerCode"] == "Carlos Segura ID458-457"
    assert sender["internalInvoiceNumber"] == 456789
    assert sender["internalOrderNumber"] == "562344"
    assert sender["saleArea"] == "Santo Domingo Este"
    assert sender["saleRoute"] == "Ruta 1"
    assert sender["stampDate"] == "2023-09-05"
    # El camp comentario debe estar en additionalInformationIssuer
    assert sender["additionalInformationIssuer"] == "Realizar pago en el Banco Popular"

    # 3. Verificar buyer
    buyer = payload["buyer"]
    print("• Validando buyer...")
    assert buyer["rnc"] == "132250011"
    assert buyer["companyName"] == "Adatum Corporation"
    assert buyer["address"] == "Station Road, 21"
    assert buyer["mail"] == "gerard.diaz@kcpdynamics.com"
    assert buyer["contact"] == "Robert Townes"

    # 4. Verificar totals
    totals = payload["totals"]
    print("• Validando totals...")
    assert totals["totalTaxedAmount"] == 56.8
    assert totals["i1AmountTaxed"] == 56.8
    assert totals["itbisS1"] == 18
    assert totals["itbisTotal"] == 10.22
    assert totals["itbis1Total"] == 10.22
    assert totals["totalAmount"] == 67.02

    # 5. Verificar otherCurrency (Otra moneda)
    other_currency = payload["otherCurrency"]
    print("• Validando otherCurrency...")
    assert other_currency["currencyType"] == "USD"
    assert other_currency["exchangeRate"] == 56.8
    assert other_currency["totalTaxedAmountOtherCurrency"] == 1.0
    assert other_currency["amountTaxed1OtherCurrency"] == 1.0
    assert other_currency["itbisTotalOtherCurrency"] == 0.18
    assert other_currency["itbis1TotalOtherCurrency"] == 0.18
    assert other_currency["totalAmountOtherCurrency"] == 1.18

    # 6. Verificar itemDetails
    item_details = payload["itemDetails"]
    print("• Validando itemDetails...")
    assert len(item_details) == 1
    item = item_details[0]
    assert item["lineNumber"] == 1
    assert item["productCode"] == "001"
    assert item["itemCodeTable"] == [{"codeType": "Interna", "itemCode": "001"}]
    assert item["itemName"] == "ALMOHADILLA PARA ROLL-ON"
    assert item["quantityItem"] == 1
    assert item["unitPriceItem"] == 56.8
    assert item["itemAmount"] == 56.8
    assert item["goodServiceIndicator"] == 1
    assert item["billingIndicator"] == 1

    # 7. Verificar otherCurrencyDetail en itemDetails
    other_currency_detail = item["otherCurrencyDetail"]
    print("• Validando otherCurrencyDetail del ítem...")
    assert other_currency_detail["priceOtherCurrency"] == 1.0
    assert other_currency_detail["discountOtherCurrency"] == 0.0
    assert other_currency_detail["surchargeAnotherCurrency"] == 0.0
    assert other_currency_detail["amountItemOtherCurrency"] == 1.0

    print("🎉 ¡Todas las pruebas de Alanube payload para E31 pasaron exitosamente!")

def test_debit_note_payload():
    print("\n🧪 Iniciando pruebas de generación de payload para Nota de Débito (E33)...")
    
    company_profile = {
        "companyRNC": "132109122",
        "companyName": "Mi Razón Social SRL",
        "tradeName": "Mi Nombre Comercial",
        "companyAddress": "C Luis Lembert Esq. Dr. Heriberto Pieter Plaza Hache. 10123",
        "companyPhone": "809-465-6799, 809-456-5646",
        "companyEmail": "correodelemisor@correo.com",
        "municipality": "010101",
        "province": "010000"
    }

    debit_note_data = {
        "ecfType": "Nota de Débito (E33)",
        "encf": "E330000000000",
        "currency": "USD",
        "exchangeRate": 56.8,
        "paymentType": "Contado",
        "clientRNC": "132250011",
        "clientName": "Adatum Corporation",
        "clientAddress": "Station Road, 21",
        "clientContact": "Robert Townes",
        "clientEmail": "gerard.diaz@kcpdynamics.com",
        "subtotal": 56.80,
        "totalITBIS": 10.22,
        "total": 67.02,
        "comentario": "Información adicional de prueba",
        "invoiceNumber": "FAC-000456789",
        "internalInvoiceNumber": 456789,
        "internalOrderNumber": "562344",
        "saleArea": "Santo Domingo Este",
        "saleRoute": "Ruta 1",
        "date": "2023-09-05",
        "items": [
            {
                "code": "001",
                "name": "ALMOHADILLA PARA ROLL-ON",
                "quantity": 1,
                "price": 56.8,
                "subtotal": 56.8,
                "itbisRate": 0.18,
                "type": "Bien"
            }
        ],
        "informationReference": {
            "modificationCode": 3,
            "ncfModified": "E31000000000",
            "ncfModifiedDate": "2023-09-05",
            "reasonForModification": "Agrego monto no cobrado"
        }
    }

    company_rnc = company_profile["companyRNC"]
    client_rnc = debit_note_data["clientRNC"]

    payload = AlanubeService.build_payload(
        company_profile, debit_note_data, company_rnc, client_rnc, "33", "E33"
    )

    # Verificar idDoc
    assert payload["idDoc"]["encf"] == "E330000000000"
    assert payload["idDoc"]["debitNoteIndicator"] == 0
    
    # Verificar informationReference
    assert "informationReference" in payload
    ref = payload["informationReference"]
    assert ref["modificationCode"] == 3
    assert ref["ncfModified"] == "E31000000000"
    assert ref["ncfModifiedDate"] == "2023-09-05"
    assert ref["reasonForModification"] == "Agrego monto no cobrado"

    # Verificar otherCurrency
    assert "otherCurrency" in payload
    other_currency = payload["otherCurrency"]
    assert other_currency["currencyType"] == "USD"
    assert other_currency["exchangeRate"] == 56.8
    assert other_currency["totalTaxedAmountOtherCurrency"] == 1.0
    assert other_currency["totalAmountOtherCurrency"] == 1.18

    # Verificar details
    assert len(payload["itemDetails"]) == 1
    item = payload["itemDetails"][0]
    assert item["otherCurrencyDetail"]["priceOtherCurrency"] == 1.0

    print("🎉 ¡Todas las pruebas de Alanube payload para E33 pasaron exitosamente!")

def test_compras_payload():
    print("\n🧪 Iniciando pruebas de generación de payload para Comprobante de Compras (E41)...")
    
    company_profile = {
        "companyRNC": "132109122",
        "companyName": "Mi Razón Social SRL",
        "tradeName": "Mi Nombre Comercial",
        "companyAddress": "C Luis Lembert Esq. Dr. Heriberto Pieter Plaza Hache. 10123",
        "companyPhone": "809-465-6799, 809-456-5646",
        "companyEmail": "correodecontacto@correo.com",
        "municipality": "010101",
        "province": "010000"
    }

    compras_data = {
        "idDoc": {
            "encf": "E410000000000",
            "sequenceDueDate": "2025-12-31",
            "taxAmountIndicator": 0,
            "paymentType": 2,
            "paymentDeadline": "2023-09-30",
            "paymentTerm": "1 mes",
            "paymentFormsTable": [
                {
                    "paymentMethod": 1,
                    "paymentAmount": 50
                },
                {
                    "paymentMethod": 4,
                    "paymentAmount": 150
                }
            ],
            "paymentAccountType": "CT",
            "paymentAccountNumber": "1254545-45458-64645",
            "bankPayment": "Banco Popular"
        },
        "buyer": {
            "rnc": "00305985365",
            "companyName": "Proveedor Informal de Prueba",
            "contact": "Carlos Gomez Estrada, Teléfono 809-456-87-98",
            "mail": "contacto@proveedor.com",
            "address": "Av. Núñez de Cáceres 593, Santo Domingo 10133",
            "municipality": "010101",
            "province": "010000",
            "internalCode": "PI-545899",
            "responsibleForPayment": "132109122",
            "additionalInformation": "Otra información importante del proveedor"
        },
        "totals": {
            "totalTaxedAmount": 200,
            "i1AmountTaxed": 200,
            "itbisS1": 18,
            "itbisTotal": 36,
            "itbis1Total": 36,
            "totalAmount": 236,
            "amountPeriod": 236,
            "previousBalance": 100,
            "amountAdvancePayment": 200,
            "payValue": 136,
            "itbisTotalRetained": 36
        },
        "items": [
            {
                "code": "001",
                "name": "Compra de productos para consumo-ITBIS 18%",
                "itemDescription": "Acá se puede enviar información adicional referente al ítem",
                "quantity": 1,
                "price": 100,
                "subtotal": 100,
                "itbisRate": 0.18,
                "type": "Bien",
                "retention": {
                    "indicatorAgentWithholdingPerception": 1,
                    "itbisAmountWithheld": 18
                }
            },
            {
                "code": "002",
                "name": "Compra de productos para consumo-ITBIS 18%",
                "itemDescription": "Acá se puede enviar información adicional referente al ítem",
                "quantity": 1,
                "price": 100,
                "subtotal": 100,
                "itbisRate": 0.18,
                "type": "Bien",
                "retention": {
                    "indicatorAgentWithholdingPerception": 1,
                    "itbisAmountWithheld": 18
                }
            }
        ]
    }

    company_rnc = "132109122"
    client_rnc = "00305985365"

    payload = AlanubeService.build_payload(
        company_profile, compras_data, company_rnc, client_rnc, "41", "E41"
    )

    # Verificar idDoc campos especiales de E41
    id_doc = payload["idDoc"]
    assert id_doc["encf"] == "E410000000000"
    assert id_doc["paymentType"] == 2
    assert id_doc["paymentDeadline"] == "2023-09-30"
    assert id_doc["paymentTerm"] == "1 mes"
    assert id_doc["paymentFormsTable"] == [{"paymentMethod": 1, "paymentAmount": 50}, {"paymentMethod": 4, "paymentAmount": 150}]
    assert id_doc["paymentAccountType"] == "CT"
    assert id_doc["paymentAccountNumber"] == "1254545-45458-64645"
    assert id_doc["bankPayment"] == "Banco Popular"

    # Verificar buyer campos especiales de E41
    buyer = payload["buyer"]
    assert buyer["rnc"] == "00305985365"
    assert buyer["companyName"] == "Proveedor Informal de Prueba"
    assert buyer["internalCode"] == "PI-545899"
    assert buyer["responsibleForPayment"] == "132109122"
    assert buyer["additionalInformation"] == "Otra información importante del proveedor"

    # Verificar totals campos especiales de E41
    totals = payload["totals"]
    assert totals["totalAmount"] == 236
    assert totals["previousBalance"] == 100.0
    assert totals["amountAdvancePayment"] == 200.0
    assert totals["payValue"] == 136.0
    assert totals["itbisTotalRetained"] == 36.0

    # Verificar itemDetails retenciones e itemDescription
    item_details = payload["itemDetails"]
    assert len(item_details) == 2
    assert item_details[0]["itemDescription"] == "Acá se puede enviar información adicional referente al ítem"
    assert item_details[0]["retention"]["itbisAmountWithheld"] == 18

    print("🎉 ¡Todas las pruebas de Alanube payload para E41 pasaron exitosamente!")

def test_gastos_menores_payload():
    print("\n🧪 Iniciando pruebas de generación de payload para Gastos Menores (E43)...")
    
    company_profile = {
        "companyRNC": "132109122",
        "companyName": "Mi Razón Social SRL",
        "tradeName": "Mi Nombre Comercial",
        "companyAddress": "C Luis Lembert Esq. Dr. Heriberto Pieter Plaza Hache. 10123",
        "companyPhone": "809-465-6799, 809-456-5646, 809-431-4489",
        "companyEmail": "micorreo@correoemisor.com",
        "municipality": "010101",
        "province": "010000"
    }

    gastos_data = {
        "idDoc": {
            "encf": "E430000000000",
            "sequenceDueDate": "2025-12-31",
            "paymentType": 1
        },
        "totals": {
            "exemptAmount": 1000,
            "totalAmount": 1000,
            "amountPeriod": 1000,
            "previousBalance": 100,
            "amountAdvancePayment": 200,
            "payValue": 900
        },
        "items": [
            {
                "lineNumber": 1,
                "billingIndicator": 4,
                "name": "Cambio periodico de gomas",
                "goodServiceIndicator": 1,
                "itemDescription": "Se realiza el cambio de la 4 gomas vehiculo principal de entregas.",
                "quantityItem": 1,
                "unitMeasure": 43,
                "unitPriceItem": 1000,
                "itemAmount": 1000
            }
        ]
    }

    company_rnc = "132109122"
    client_rnc = ""  # Gastos menores no tiene buyer

    payload = AlanubeService.build_payload(
        company_profile, gastos_data, company_rnc, client_rnc, "43", "E43"
    )

    # Verificar idDoc
    assert payload["idDoc"]["encf"] == "E430000000000"
    assert payload["idDoc"]["paymentType"] == 1

    # Verificar buyer no existe
    assert "buyer" not in payload

    # Verificar totals
    totals = payload["totals"]
    assert totals["exemptAmount"] == 1000
    assert totals["totalAmount"] == 1000
    assert totals["amountPeriod"] == 1000
    assert totals["previousBalance"] == 100
    assert totals["amountAdvancePayment"] == 200
    assert totals["payValue"] == 900

    # Verificar item details
    item_details = payload["itemDetails"]
    assert len(item_details) == 1
    item = item_details[0]
    assert item["itemName"] == "Cambio periodico de gomas"
    assert item["unitMeasure"] == 43
    assert item["itemDescription"] == "Se realiza el cambio de la 4 gomas vehiculo principal de entregas."

    print("🎉 ¡Todas las pruebas de Alanube payload para E43 pasaron exitosamente!")

def test_pagos_exterior_payload():
    print("\n🧪 Iniciando pruebas de generación de payload para Pagos al Exterior (E47)...")
    
    company_profile = {
        "companyRNC": "132109122",
        "companyName": "Razón Social del Emisor",
        "tradeName": "Nombre Comercial del Emisor",
        "companyAddress": "Av. México No. 48, Gazcue, Distrito Nacional, Santo Domingo",
        "companyPhone": "809-499-6894, 809-564-6894",
        "companyEmail": "contacto@emisordele-ncf.com",
        "municipality": "010101",
        "province": "010000"
    }

    pagos_data = {
        "idDoc": {
            "encf": "E470000000000",
            "sequenceDueDate": "2025-12-31",
            "paymentType": 2,
            "paymentTerm": "30 días",
            "paymentDeadline": "2024-12-31",
            "paymentFormsTable": [
                {
                    "paymentMethod": 1,
                    "paymentAmount": 1000
                },
                {
                    "paymentMethod": 2,
                    "paymentAmount": 1000
                }
            ],
            "paymentAccountType": "CT",
            "paymentAccountNumber": "102645-64565-6454",
            "bankPayment": "Banco General",
            "dateFrom": "2023-08-01",
            "dateUntil": "2023-08-31"
        },
        "buyer": {
            "foreignIdentifier": "900900900",
            "companyName": "Empresa Colombiana de Comercio S.A.S"
        },
        "transport": {
            "destinationCountry": "Colombia"
        },
        "totals": {
            "exemptAmount": 100,
            "totalAmount": 100,
            "amountPeriod": 100,
            "previousBalance": 100,
            "amountAdvancePayment": 50,
            "payValue": 150,
            "isrTotalRetention": 27
        },
        "items": [
            {
                "lineNumber": 1,
                "billingIndicator": 4,
                "goodServiceIndicator": 2,
                "itemCodeTable": [
                    {
                        "codeType": "EAN",
                        "itemCode": "1224545-4545"
                    },
                    {
                        "codeType": "PLU",
                        "itemCode": "799889457844884"
                    }
                ],
                "name": "Nombre del producto o servicio.",
                "itemDescription": "Descripción adicional del ítem, el campo acepta hasta 1000 caracteres.",
                "quantityItem": 1,
                "unitMeasure": 43,
                "unitPriceItem": 100,
                "itemAmount": 100,
                "retention": {
                    "indicatorAgentWithholdingPerception": 1,
                    "isrAmountWithheld": 27
                }
            }
        ]
    }

    company_rnc = "132109122"
    client_rnc = "900900900"

    payload = AlanubeService.build_payload(
        company_profile, pagos_data, company_rnc, client_rnc, "47", "E47"
    )

    # Verificar idDoc
    assert payload["idDoc"]["encf"] == "E470000000000"
    assert payload["idDoc"]["paymentDeadline"] == "2024-12-31"
    assert payload["idDoc"]["dateFrom"] == "2023-08-01"

    # Verificar buyer foreignIdentifier
    assert "buyer" in payload
    assert payload["buyer"]["foreignIdentifier"] == "900900900"
    assert payload["buyer"]["companyName"] == "Empresa Colombiana de Comercio S.A.S"

    # Verificar transport
    assert "transport" in payload
    assert payload["transport"]["destinationCountry"] == "Colombia"

    # Verificar totals
    totals = payload["totals"]
    assert totals["exemptAmount"] == 100.0
    assert totals["totalAmount"] == 100.0
    assert totals["payValue"] == 150.0
    assert totals["isrTotalRetention"] == 27.0

    # Verificar item details
    item_details = payload["itemDetails"]
    assert len(item_details) == 1
    item = item_details[0]
    assert item["itemName"] == "Nombre del producto o servicio."
    assert item["unitMeasure"] == 43
    assert item["itemCodeTable"] == [
        {"codeType": "EAN", "itemCode": "1224545-4545"},
        {"codeType": "PLU", "itemCode": "799889457844884"}
    ]
    assert item["retention"]["isrAmountWithheld"] == 27

    print("🎉 ¡Todas las pruebas de Alanube payload para E47 pasaron exitosamente!")

def test_dgii_friendly_errors():
    print("\n🧪 Iniciando pruebas de traducción de errores de la DGII...")
    
    # 1. Simple dict error
    err1 = {"code": "AEP2003", "message": "An error has occured while trying to authenticate with DGII"}
    res1 = AlanubeService.get_dgii_friendly_error(err1)
    assert "AEP2003 - Ocurrió un error al intentar autenticarse con la DGII (Firma/Certificado)." in res1
    
    # 2. Nested errors list (standard Alanube format)
    err2 = {
        "message": "Validation failed",
        "errors": [
            {"code": "AEP2006", "message": "The connection with DGII has timed out"}
        ]
    }
    res2 = AlanubeService.get_dgii_friendly_error(err2)
    assert "AEP2006 - La conexión con la DGII ha superado el tiempo de espera (Timeout)." in res2

    # 3. Nested response list (alternative format)
    err3 = {
        "message": "Validation failed",
        "response": [
            {"code": "AEP2012", "message": "The DGII host is unreachable"}
        ]
    }
    res3 = AlanubeService.get_dgii_friendly_error(err3)
    assert "AEP2012 - El servidor/host de la DGII se encuentra inalcanzable." in res3

    # 4. Unknown code
    err4 = {"code": "XYZ9999", "message": "Some obscure error"}
    res4 = AlanubeService.get_dgii_friendly_error(err4)
    assert res4 == "Some obscure error"

    # 5. Invalid format/fallback
    err5 = "Non-JSON response body or garbage string"
    res5 = AlanubeService.get_dgii_friendly_error(err5)
    assert res5 == "Error de comunicación con Alanube/DGII."

    print("🎉 ¡Todas las pruebas de traducción de errores de la DGII pasaron exitosamente!")

if __name__ == "__main__":
    test_payload_generation()
    test_debit_note_payload()
    test_compras_payload()
    test_gastos_menores_payload()
    test_pagos_exterior_payload()
    test_dgii_friendly_errors()
