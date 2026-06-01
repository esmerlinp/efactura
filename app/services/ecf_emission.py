from config import Config
from app.services.alanube import AlanubeService
from app.services.dgii_direct import DgiiDirectService

class EcfEmissionService:
    
    @classmethod
    def emit_electronic_comprobante(cls, company, invoice_dict, sandbox=True):
        """
        Punto de entrada único para la emisión de e-CF.
        Enruta dinámicamente según la variable E_CF_PROVIDER configurada en el .env.
        """
        # Validaciones fiscales globales agnósticas al proveedor
        ecf_type = invoice_dict.get("ecfType", "Factura de Consumo (E32)")
        client_rnc = str(invoice_dict.get("clientRNC", "")).replace("-", "").strip()
        
        # Si es Crédito Fiscal (E31) y no tiene RNC corporativo o personal válido, lanzar error
        if "E31" in ecf_type or "fiscal-invoices" in ecf_type or "Crédito Fiscal" in ecf_type:
            if client_rnc == "999999999" or not client_rnc or len(client_rnc) not in [9, 11]:
                raise ValueError("Para emitir un Crédito Fiscal (E31) se requiere un RNC de cliente de 9 dígitos o Cédula de 11 dígitos.")
                
        provider = Config.E_CF_PROVIDER.lower()
        
        if provider == 'dgii_direct':
            return DgiiDirectService.emit_direct(company, invoice_dict, sandbox=sandbox)
        else:
            # Fallback y actual predeterminado: Alanube
            return AlanubeService.emit_electronic_comprobante(company, invoice_dict, sandbox=sandbox)

    @classmethod
    def emit_cancellation(cls, company, cancellation_dict, sandbox=True):
        """
        Anula un e-CF a través del proveedor activo.
        """
        provider = Config.E_CF_PROVIDER.lower()
        
        if provider == 'dgii_direct':
            return DgiiDirectService.cancel_direct(company, cancellation_dict, sandbox=sandbox)
        else:
            return AlanubeService.emit_cancellation(company, cancellation_dict, sandbox=sandbox)

