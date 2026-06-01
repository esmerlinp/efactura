import sys
import xml.etree.ElementTree as ET
from app.services.dgii_xml_builder import DgiiXmlBuilder

def run_xml_tests():
    print("🧪 Iniciando pruebas de generación de XML Fiscal DGII...")
    
    # 1. Datos simulados del perfil de la empresa (Emisor)
    company_profile = {
        "companyRNC": "132-10912-2",
        "companyName": "Tecnología Dominicana SRL",
        "tradeName": "TecnoDom",
        "companyAddress": "Av. Winston Churchill #1012, Santo Domingo",
        "companyPhone": "809-555-0199",
        "municipality": "Santo Domingo Este", # Debe traducirse a 320100
        "province": "Santo Domingo"          # Debe traducirse a 320000
    }
    
    # 2. Datos simulados de la factura con retenciones en cero y moneda COP
    invoice_data = {
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E320000000005",
        "currency": "COP",                  # Debe traducirse a COP
        "paymentMethod": "Crédito",
        "clientRNC": "",                     # Sin RNC (Consumo menor de 250k)
        "clientName": "",                    # Sin Nombre
        "clientMunicipality": "Cabral",      # Debe traducirse a 040200
        "clientProvince": "Barahona",        # Debe traducirse a 040000
        "subtotal": 1500.00,
        "discountRate": 0.0,
        "totalITBIS": 270.00,
        "retainedITBIS": 0.00,               # Retención cero
        "retainedISR": 0.00,                 # Retención cero
        "total": 1770.00,
        "items": [
            {
                "code": "ART-001",
                "name": "Bandeja de Bocadillos",
                "unit": "Bandeja",           # Debe mapearse a 57
                "quantity": 2.0,
                "price": 750.00,
                "subtotal": 1500.00,
                "itbisRate": 0.18,
                "itbis_amount": 270.00,
                "type": "Bien"
            }
        ]
    }
    
    try:
        # Generar XML utilizando nuestro constructor
        xml_bytes = DgiiXmlBuilder.build_invoice_xml(company_profile, invoice_data)
        xml_str = xml_bytes.decode('utf-8')
        
        # Parsear para verificar estructura XML válida
        root = ET.fromstring(xml_str)
        print("✅ XML sintácticamente válido.")
        
        # Mostrar el XML generado
        print("\n=== XML GENERADO ===")
        print(xml_str)
        print("====================\n")
        
        # Definir Namespace oficial de la DGII
        ns = {"cf": "http://dgii.gov.do/CF"}
        
        # Validar aserciones claves
        
        # 1. Moneda
        tipo_moneda = root.find(".//cf:TipoMoneda", ns)
        print(f"• Tipo de Moneda: {tipo_moneda.text if tipo_moneda is not None else 'No encontrado'} (Esperado: COP)")
        assert tipo_moneda is not None and tipo_moneda.text == "COP", "Error en TipoMoneda"
        
        # 2. Provincia y Municipio de Emisor
        prov_emisor = root.find(".//cf:Emisor/cf:Provincia", ns)
        mun_emisor = root.find(".//cf:Emisor/cf:Municipio", ns)
        print(f"• Provincia Emisor: {prov_emisor.text} (Esperado: 320000)")
        print(f"• Municipio Emisor: {mun_emisor.text} (Esperado: 320100)")
        assert prov_emisor.text == "320000", "Error en Provincia Emisor"
        assert mun_emisor.text == "320100", "Error en Municipio Emisor"
        
        # 3. Receptor Condicional (Menor a 250k y vacío)
        rnc_receptor = root.find(".//cf:Receptor/cf:RNCReceptor", ns)
        razon_social = root.find(".//cf:Receptor/cf:RazonSocialReceptor", ns)
        print(f"• Receptor RNC: {'Omitido' if rnc_receptor is None else 'Presente'}")
        print(f"• Receptor Razón Social: {'Omitido' if razon_social is None else 'Presente'}")
        assert rnc_receptor is None and razon_social is None, "Error en campos del Receptor (deben ser omitidos)"
        
        # 4. Retenciones obligatorias explícitas
        ret_itbis = root.find(".//cf:Totales/cf:TotalITBISRetenido", ns)
        ret_isr = root.find(".//cf:Totales/cf:TotalISRRetencion", ns)
        print(f"• Retención ITBIS: {ret_itbis.text} (Esperado: 0.00)")
        print(f"• Retención ISR: {ret_isr.text} (Esperado: 0.00)")
        assert ret_itbis.text == "0.00", "Error en TotalITBISRetenido"
        assert ret_isr.text == "0.00", "Error en TotalISRRetencion"
        
        # 5. Mapeo de Unidad de Medida
        unidad_medida = root.find(".//cf:Detalle/cf:UnidadMedida", ns)
        print(f"• Unidad de Medida Ítem: {unidad_medida.text} (Esperado: 57)")
        assert unidad_medida.text == "57", "Error en UnidadMedida"
        
        print("\n🎉 ¡Todas las pruebas del generador XML de la DGII pasaron exitosamente!")
        
    except Exception as e:
        print(f"\n❌ Error durante la ejecución del test: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    run_xml_tests()
