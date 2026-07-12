from app.services.dgii_direct import DgiiDirectService

class EcfEmissionService:
    
    @classmethod
    def emit_electronic_comprobante(cls, company, invoice_dict, sandbox=True):
        ecf_type = invoice_dict.get("ecfType", "Factura de Consumo (E32)")
        client_rnc = str(invoice_dict.get("clientRNC", "")).replace("-", "").strip()
        
        if "E31" in ecf_type or "fiscal-invoices" in ecf_type or "Crédito Fiscal" in ecf_type:
            if client_rnc == "000000000" or not client_rnc or len(client_rnc) not in [9, 11]:
                raise ValueError("Para emitir un Crédito Fiscal (E31) se requiere un RNC de cliente de 9 dígitos o Cédula de 11 dígitos.")
                
        return DgiiDirectService.emit_direct(company, invoice_dict, sandbox=sandbox)

    @classmethod
    def emit_cancellation(cls, company, cancellation_dict, sandbox=True):
        return DgiiDirectService.cancel_direct(company, cancellation_dict, sandbox=sandbox)

