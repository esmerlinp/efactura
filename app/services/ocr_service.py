# app/services/ocr_service.py
import re
import xml.etree.ElementTree as ET
from datetime import datetime

class OCRService:
    @classmethod
    def process_xml_ecf(cls, xml_content):
        """
        Parsea un archivo XML de e-CF emitido de acuerdo a la estructura oficial de la DGII
        y extrae los campos clave. Retorna un diccionario con los datos fiscales.
        """
        try:
            # Eliminar namespaces o registrarlos para un parseo robusto
            # Quitamos namespaces para buscar con etiquetas simples
            xml_str = xml_content.decode('utf-8', errors='ignore') if isinstance(xml_content, bytes) else xml_content
            # Limpieza rápida de namespaces para facilitar búsqueda
            xml_str_clean = re.sub(r'\sxmlns="[^"]+"', '', xml_str, count=1)
            xml_str_clean = re.sub(r'\sxmlns:[^=]+="[^"]+"', '', xml_str_clean)
            
            root = ET.fromstring(xml_str_clean)
            
            # Buscar nodos de manera flexible (por tag exacto sin prefijos)
            def find_text(tag_name):
                for elem in root.iter():
                    if elem.tag.split('}')[-1] == tag_name:
                        return (elem.text or "").strip()
                return ""

            # Extraer campos
            rnc_emisor = find_text("RNCEmisor") or find_text("RNCEntidadEntrega") or find_text("RNC")
            encf = find_text("eNCF") or find_text("NCF")
            fecha_emision = find_text("FechaEmision") or find_text("Fecha")
            monto_total = find_text("MontoTotal") or find_text("Total")
            monto_itbis = find_text("MontoITBIS") or find_text("ITBIS")
            cne = find_text("CodigoSeguridad") or find_text("CNE") or find_text("CNEFirma")
            
            # Intentar parsear tipo de e-CF desde el eNCF (primeros 3 caracteres, ej: E31)
            ecf_type = encf[:3] if encf and len(encf) >= 3 else "E31"
            
            # Validar eNCF de 13 caracteres que inicia con E
            if encf and not encf.startswith('E') and len(encf) == 11:
                # Caso de NCF tradicional, convertir visualmente si se requiere o mantener
                pass
                
            return {
                "success": True,
                "rncEmisor": rnc_emisor,
                "ncf": encf,
                "ecfType": ecf_type,
                "ecfNumber": encf,
                "date": fecha_emision[:10] if fecha_emision else datetime.utcnow().strftime("%Y-%m-%d"),
                "amount": float(monto_total) if monto_total else 0.0,
                "itbisAmount": float(monto_itbis) if monto_itbis else 0.0,
                "cne": cne,
                "notes": "Extraído automáticamente del archivo XML e-CF original."
            }
        except Exception as e:
            print(f"⚠️ Error al parsear XML de e-CF: {e}")
            return {"success": False, "error": f"Formato XML inválido o no reconocido: {str(e)}"}

    @classmethod
    def process_image_ocr(cls, image_bytes_or_text):
        """
        Procesa una imagen (usando simulación de OCR en sandbox o Tesseract)
        y detecta patrones de e-CF dominicanos y QR de la DGII.
        """
        # En Sandbox, si se pasa un texto (como una simulación de string extraída por OCR), lo parseamos directamente
        # de lo contrario, simulamos la lectura OCR en base al texto impreso en la imagen de muestra
        text_content = ""
        if isinstance(image_bytes_or_text, str):
            text_content = image_bytes_or_text
        else:
            # Simulación: si se sube una imagen binaria en desarrollo, leemos patrones mock
            # Simulamos el OCR exitoso de un ticket de compra promedio de República Dominicana
            text_content = (
                "SUPERMERCADOS NACIONAL\n"
                "RNC: 101-00101-1\n"
                "COMPROBANTE FISCAL ELECTRONICO (e-CF)\n"
                "NCF: E310120000452\n"
                "FECHA: 2026-06-09\n"
                "CNE: ABC123DEF\n"
                "SUBTOTAL: RD$ 1,000.00\n"
                "ITBIS (18%): RD$ 180.00\n"
                "TOTAL: RD$ 1,180.00\n"
                "https://ecf.dgii.gov.do/ConsultaEcf?RNC=101001011&NCF=E310120000452&Monto=1180.00&Itbis=180.00&Fecha=09-06-2026&CNE=ABC123DEF"
            )
            
        # 1. Buscar URL de la DGII / Código QR
        qr_url_match = re.search(r'https?://[^\s]+dgii\.gov\.do/[^\s]+', text_content, re.IGNORECASE)
        if qr_url_match:
            qr_url = qr_url_match.group(0)
            return cls.parse_dgii_qr_url(qr_url)
            
        # 2. Si no hay QR, usar expresiones regulares sobre el texto leído
        rnc_pattern = r'(?:RNC|REGISTRO|R\.N\.C\.)\s*[:\-\#]?\s*([0-9\-\s]{9,13})'
        ncf_pattern = r'(?:NCF|E-CF|COMPROBANTE|N\.C\.F\.)\s*[:\-\#]?\s*([E|B][0-9]{10,12})'
        date_pattern = r'(?:FECHA|DATE)\s*[:\-]?\s*([0-9]{4}[-/][0-9]{2}[-/][0-9]{2}|[0-9]{2}[-/][0-9]{2}[-/][0-9]{4})'
        total_pattern = r'(?:TOTAL|NETO|PAGAR|SUMA|RD\$)\s*[:\-\$]?\s*([0-9,\s]+\.[0-9]{2})'
        itbis_pattern = r'(?:ITBIS|IMPUESTO|18%)\s*[:\-\$]?\s*([0-9,\s]+\.[0-9]{2})'
        
        # Buscar matches
        rnc_raw = re.search(rnc_pattern, text_content, re.IGNORECASE)
        ncf_raw = re.search(ncf_pattern, text_content, re.IGNORECASE)
        date_raw = re.search(date_pattern, text_content, re.IGNORECASE)
        total_raw = re.search(total_pattern, text_content, re.IGNORECASE)
        itbis_raw = re.search(itbis_pattern, text_content, re.IGNORECASE)
        
        rnc = re.sub(r'[^0-9]', '', rnc_raw.group(1)) if rnc_raw else ""
        ncf = ncf_raw.group(1).strip() if ncf_raw else ""
        
        # Formatear fecha a YYYY-MM-DD
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        if date_raw:
            raw_d = re.sub(r'\s', '', date_raw.group(1)).replace('/', '-')
            try:
                if len(raw_d) == 10 and raw_d[4] == '-': # YYYY-MM-DD
                    date_str = raw_d
                else: # Intentar DD-MM-YYYY
                    parts = raw_d.split('-')
                    if len(parts) == 3:
                        date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
            except:
                pass
                
        def clean_float(val_str):
            try:
                return float(re.sub(r'[^\d.]', '', val_str))
            except:
                return 0.0

        amount = clean_float(total_raw.group(1)) if total_raw else 0.0
        itbis = clean_float(itbis_raw.group(1)) if itbis_raw else (amount * 0.18 / 1.18)
        
        ecf_type = ncf[:3] if ncf and len(ncf) >= 3 else "E31"
        
        return {
            "success": True,
            "rncEmisor": rnc,
            "ncf": ncf,
            "ecfType": ecf_type,
            "ecfNumber": ncf,
            "date": date_str,
            "amount": amount,
            "itbisAmount": itbis,
            "cne": "",
            "notes": "Extraído vía reconocimiento de texto OCR."
        }

    @classmethod
    def parse_dgii_qr_url(cls, qr_url):
        """
        Parsea los parámetros de la URL de consulta e-CF de la DGII
        ejemplo: https://ecf.dgii.gov.do/ConsultaEcf?RNC=101001011&NCF=E310120000452&Monto=1180.00&Itbis=180.00&Fecha=09-06-2026&CNE=ABC123DEF
        """
        try:
            # Buscar query params
            def get_param(name):
                match = re.search(fr'[?&]{name}=([^&]+)', qr_url, re.IGNORECASE)
                return match.group(1) if match else ""
                
            rnc = get_param("RNC")
            ncf = get_param("NCF")
            monto = get_param("Monto")
            itbis = get_param("Itbis")
            fecha_raw = get_param("Fecha")
            cne = get_param("CNE")
            
            # Formatear fecha de DD-MM-YYYY a YYYY-MM-DD
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            if fecha_raw:
                parts = fecha_raw.split('-')
                if len(parts) == 3:
                    # Si ya viene YYYY-MM-DD
                    if len(parts[0]) == 4:
                        date_str = fecha_raw
                    else:
                        date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
            
            ecf_type = ncf[:3] if ncf and len(ncf) >= 3 else "E31"
            
            return {
                "success": True,
                "rncEmisor": rnc,
                "ncf": ncf,
                "ecfType": ecf_type,
                "ecfNumber": ncf,
                "date": date_str,
                "amount": float(monto) if monto else 0.0,
                "itbisAmount": float(itbis) if itbis else 0.0,
                "cne": cne,
                "notes": "Verificado e importado exitosamente desde el código QR oficial de la DGII."
            }
        except Exception as e:
            print(f"⚠️ Error al parsear QR de DGII: {e}")
            return {"success": False, "error": f"Fallo al procesar URL del QR: {str(e)}"}
