from app.services.dgii_direct import DgiiDirectService
from app.services.dgii_xml_builder import DgiiXmlBuilder

ECF_CONSUMO_32 = "Factura de Consumo (E32)"
RFCE_THRESHOLD = 250000.00


class EcfEmissionService:

    @classmethod
    def _is_consumo_32(cls, ecf_type):
        return "E32" in ecf_type or ecf_type == ECF_CONSUMO_32 or "Consumo" in ecf_type

    @classmethod
    def _es_rfce(cls, ecf_type, total):
        return cls._is_consumo_32(ecf_type) and float(total) < RFCE_THRESHOLD

    @classmethod
    def emit_electronic_comprobante(cls, company, invoice_dict, sandbox=True):
        ecf_type = invoice_dict.get("ecfType", ECF_CONSUMO_32)
        client_rnc = str(invoice_dict.get("clientRNC", "")).replace("-", "").strip()
        total = float(invoice_dict.get("total", 0.0))

        # Evita firmar y enviar XML con totales incompatibles con sus líneas.
        # El builder calcula el exento desde los ítems para no depender de la
        # persistencia opcional de montoExento/monto_exento.
        calculated = DgiiXmlBuilder._calculate_exento(invoice_dict)
        invoice_dict["montoExento"] = calculated
        invoice_dict["monto_exento"] = calculated
        DgiiXmlBuilder.validate_totals(invoice_dict)

        if "E31" in ecf_type or "fiscal-invoices" in ecf_type or "Crédito Fiscal" in ecf_type:
            if client_rnc == "000000000" or not client_rnc or len(client_rnc) not in [9, 11]:
                raise ValueError("Para emitir un Crédito Fiscal (E31) se requiere un RNC de cliente de 9 dígitos o Cédula de 11 dígitos.")

        if "E45" in ecf_type or "Gubernamental" in ecf_type:
            if client_rnc == "000000000" or not client_rnc or len(client_rnc) != 9:
                raise ValueError("Para emitir un Comprobante Gubernamental (E45) se requiere un RNC de cliente de 9 dígitos.")
        if "E46" in ecf_type or "Exportación" in ecf_type:
            if not client_rnc:
                invoice_dict["clientRNC"] = "000000000"
            # Asegurar que identificadorExtranjero esté presente si tenemos foreignTaxId
            if not invoice_dict.get("identificadorExtranjero") and invoice_dict.get("foreignTaxId"):
                invoice_dict["identificadorExtranjero"] = invoice_dict["foreignTaxId"]

        if "E44" in ecf_type or "Regímenes Especiales" in ecf_type:
            if not client_rnc or len(client_rnc) != 9:
                raise ValueError("Para emitir un Comprobante de Regímenes Especiales (E44) se requiere un RNC de cliente de 9 dígitos.")

        if cls._es_rfce(ecf_type, total):
            return DgiiDirectService.emit_rfce(company, invoice_dict, sandbox=sandbox)

        return DgiiDirectService.emit_direct(company, invoice_dict, sandbox=sandbox)

    @classmethod
    def emit_cancellation(cls, company, cancellation_dict, sandbox=True):
        return DgiiDirectService.cancel_direct(company, cancellation_dict, sandbox=sandbox)
