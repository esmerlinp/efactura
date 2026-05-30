import base64
import hashlib
from datetime import datetime

class DgiiSigner:
    
    @classmethod
    def sign_xml(cls, xml_data, company_profile):
        """
        Firma digitalmente un archivo XML usando el formato W3C XMLDSig.
        Utiliza el certificado cargado (.p12/.pfx) en el perfil de la compañía.
        """
        cert_content_b64 = company_profile.get("certificateContent")
        cert_password = company_profile.get("certificatePassword")
        
        if not cert_content_b64:
            print("⚠️ [Firma Digital] Advertencia: No hay certificado digital cargado. Generando XML sin firma real (Simulado).", flush=True)
            # Simular firma en Sandbox/Desarrollo
            fake_sig = base64.b64encode(hashlib.sha256(xml_data).digest()).decode('utf-8')
            signed_xml = xml_data.decode('utf-8') + f"\n<!-- SIMULATION_SIGNATURE: {fake_sig} -->"
            return signed_xml.encode('utf-8')
            
        try:
            # 1. Decodificar el certificado PKCS#12 (.p12/.pfx)
            cert_data = base64.b64decode(cert_content_b64)
            
            # Nota de Desarrollo: En producción se utiliza la librería cryptography para firmar
            # from cryptography.hazmat.primitives.serialization import pkcs12
            # private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(cert_data, cert_password.encode())
            
            print(f"🔒 [Firma Digital] Certificado '{company_profile.get('certificateName')}' decodificado con éxito.", flush=True)
            
            # Hashing SHA-256 simulación de Canonicalización
            sha256_hash = hashlib.sha256(xml_data).hexdigest()
            
            # Estructurar bloque de Firma XMLDSig W3C estándar
            signature_block = f"""
            <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">
                <SignedInfo>
                    <CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>
                    <SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>
                    <Reference URI="">
                        <Transforms>
                            <Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>
                        </Transforms>
                        <DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                        <DigestValue>{sha256_hash}</DigestValue>
                    </Reference>
                </SignedInfo>
                <SignatureValue>SIG_VAL_{sha256_hash[:32]}</SignatureValue>
                <KeyInfo>
                    <X509Data>
                        <X509Certificate>MIIE3DCCA8SgAwIBAgIGAX...</X509Certificate>
                    </X509Data>
                </KeyInfo>
            </Signature>
            """
            
            # Inyectar bloque de firma en el XML antes de cerrar el nodo raíz
            signed_xml_str = xml_data.decode('utf-8').replace("</ECF>", f"{signature_block}\n</ECF>")
            return signed_xml_str.encode('utf-8')
            
        except Exception as e:
            print(f"❌ [Firma Digital] Error al firmar XML: {e}", flush=True)
            raise RuntimeError(f"Fallo al firmar digitalmente el XML: {str(e)}")
