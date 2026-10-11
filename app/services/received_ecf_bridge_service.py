import logging
import uuid
from datetime import datetime, timezone
from app.services.receptor_xml_service import ReceptorXmlService
from app.services.supplier_service import SupplierService
from app.services.db_service import DatabaseService, db_firestore
from app.repositories.receptor_repository import ReceptorRepository

logger = logging.getLogger(__name__)

VALID_606_ECF_TYPES = ("31", "33", "34", "44", "45", "E31", "E33", "E34", "E44", "E45")


class ReceivedEcfBridgeService:
    """Servicio que conecta los e-CF recibidos con el módulo de Gastos y el Reporte 606.

    Garantiza que toda factura recibida y aceptada con ARECF (Estado 0) se
    registre automáticamente en la colección de gastos con includeIn606=True,
    extrayendo desglose de bienes/servicios, NCF modificado, tasas de ITBIS,
    retenciones y forma de pago del XML.
    """

    @classmethod
    def _normalize_encf_type(cls, raw_type):
        t = str(raw_type or "").strip().upper()
        if not t:
            return "E31"
        if t.isdigit():
            return f"E{t}"
        return t

    @classmethod
    def process_received_ecf(cls, owner_uid, ecf_document, sandbox=True, company_id=None):
        """Procesa un e-CF recibido para registrarlo automáticamente en el 606."""
        if not owner_uid or not ecf_document:
            return False, "Parámetros incompletos."

        # Solo comprobantes aceptados
        estado_arecf = str(ecf_document.get("estado_arecf", "0"))
        if estado_arecf != "0":
            return False, f"Documento no aceptado (estado ARECF={estado_arecf})."

        raw_type = ecf_document.get("ecf_type", "")
        clean_type = cls._normalize_encf_type(raw_type)
        if raw_type not in VALID_606_ECF_TYPES and clean_type not in VALID_606_ECF_TYPES:
            logger.info("e-CF %s de tipo %s no computable para compras 606.", ecf_document.get("encf"), clean_type)
            return False, f"Tipo {clean_type} no computable en 606."

        xml_content = ecf_document.get("xml_content", "")
        if not xml_content:
            return False, "El e-CF recibido no tiene contenido XML."

        try:
            detail, error = ReceptorXmlService.parse_ecf_detail(xml_content.encode("utf-8"))
        except Exception as e:
            logger.exception("Error al parsear detalle de e-CF recibido: %s", e)
            detail, error = None, str(e)

        if not detail:
            detail = ReceptorXmlService.default_detail()

        encf = (detail.get("encf") or ecf_document.get("encf") or "").strip()
        sender_rnc = "".join(filter(str.isdigit, str(detail.get("rnc_emisor") or ecf_document.get("sender_rnc") or "")))
        sender_name = detail.get("razon_social_emisor") or ecf_document.get("sender_name") or "Proveedor sin nombre"
        ecf_type_final = cls._normalize_encf_type(detail.get("tipo_ecf") or raw_type)

        if not encf or not sender_rnc:
            return False, "Falta e-NCF o RNC del emisor para registrar en 606."

        # ── Verificar si ya existe en gastos o facturas de proveedor ──
        existing_expense = cls._find_existing_expense(owner_uid, encf, sender_rnc, sandbox=sandbox, company_id=company_id)
        if existing_expense:
            cls._mark_ecf_as_registered(owner_uid, ecf_document.get("id"), existing_expense.get("id"), sandbox=sandbox)
            return True, f"Ya registrado como gasto {existing_expense.get('id')}."

        # ── Obtener o registrar proveedor ──
        supplier_id, _ = SupplierService.get_or_create_supplier(
            owner_uid=owner_uid,
            rnc=sender_rnc,
            name=sender_name,
            address=detail.get("direccion_emisor", ""),
            sandbox=sandbox,
            company_id=company_id,
        )

        supplier = None
        if supplier_id:
            try:
                supplier = SupplierService.get_supplier(owner_uid, supplier_id, sandbox=sandbox, company_id=company_id)
            except Exception:
                supplier = None

        tipo_gasto = (supplier or {}).get("tipoGastoDGII") or "02"

        # ── Montos y fechas ──
        monto_total = float(detail.get("monto_total") or ecf_document.get("monto_total") or 0.0)
        total_itbis = float(detail.get("total_itbis") or 0.0)
        monto_servicios = float(detail.get("monto_servicios") or 0.0)
        monto_bienes = float(detail.get("monto_bienes") or 0.0)
        if monto_servicios == 0.0 and monto_bienes == 0.0:
            monto_bienes = monto_total

        fecha_recepcion = (ecf_document.get("received_at") or "")[:10]
        fecha_emision = detail.get("fecha_emision_iso") or ""

        # Si fecha_emision es de un año anterior al año de recepción (ej. sets de prueba DGII fechados en 2020),
        # se imputa a la fecha de recepción para que aparezca en el mes donde el usuario realmente la recibió.
        if fecha_recepcion and fecha_emision:
            try:
                y_emision = int(fecha_emision[:4])
                y_recepcion = int(fecha_recepcion[:4])
                if y_emision < y_recepcion:
                    fecha_comprobante = fecha_recepcion
                else:
                    fecha_comprobante = fecha_emision
            except (ValueError, TypeError):
                fecha_comprobante = fecha_emision
        else:
            fecha_comprobante = fecha_emision or fecha_recepcion or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        fecha_vencimiento = detail.get("fecha_vencimiento_iso", "")
        forma_pago_606 = detail.get("forma_pago_606", "02")
        ncf_modificado = detail.get("ncf_modificado", "")
        retained_itbis = float(detail.get("total_itbis_retenido") or 0.0)
        retained_isr = float(detail.get("total_isr_retencion") or 0.0)
        otros_impuestos = float(detail.get("monto_impuesto_adicional") or 0.0)

        expense_id = str(uuid.uuid4())
        expense_dict = {
            "id": expense_id,
            "ownerUID": owner_uid,
            "concept": f"e-CF Recibido {encf} - {sender_name}",
            "category": "Compras y Servicios",
            "currency": "DOP",
            "exchangeRate": 1.0,
            "amountOriginal": monto_total,
            "amount": monto_total,
            "itbisAmountOriginal": total_itbis,
            "itbisAmount": total_itbis,
            "date": fecha_comprobante,
            "fechaRecepcion": fecha_recepcion,
            "receivedAt": ecf_document.get("received_at", ""),
            "fechaEmisionOriginal": fecha_emision,
            "dueDate": fecha_vencimiento,
            "rncEmisor": sender_rnc,
            "providerName": sender_name,
            "ncf": encf,
            "encf": encf,
            "ncfModificado": ncf_modificado,
            "ecfType": ecf_type_final,
            "ecfNumber": encf,
            "tipoGastoDGII": tipo_gasto,
            "paymentType": "Contado" if forma_pago_606 == "01" else "A Crédito" if forma_pago_606 == "04" else "Transferencia",
            "formaPago": forma_pago_606,
            "montoServicios": monto_servicios,
            "montoBienes": monto_bienes,
            "isITBISDeductible": True,
            "isDeductible": True,
            "includeIn606": True,
            "supplierId": supplier_id or "",
            "supplierType": "formal",
            "retainedITBIS": retained_itbis,
            "itbisWithheld": retained_itbis,
            "retainedISR": retained_isr,
            "isrWithheld": retained_isr,
            "otrosImpuestos": otros_impuestos,
            "source": "received_ecf",
            "receivedEcfId": ecf_document.get("id", ""),
            "trackId": ecf_document.get("track_id", ""),
            "notes": f"Registrado automáticamente desde portal de recepción e-CF ({encf})",
            "xmlContent": xml_content,
            "status": "Registrada",
            "approvalStatus": "Aprobado",
            "cxpStatus": "Pagado" if forma_pago_606 == "01" else "Pendiente",
            "cxpRemainingBalance": 0.0 if forma_pago_606 == "01" else monto_total,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }

        try:
            DatabaseService.save_expense(owner_uid, expense_id, expense_dict, sandbox=sandbox, company_id=company_id)
            cls._mark_ecf_as_registered(owner_uid, ecf_document.get("id"), expense_id, tipo_gasto=tipo_gasto, sandbox=sandbox)
            logger.info("e-CF %s registrado automáticamente en 606 (gasto %s).", encf, expense_id)
            return True, expense_id
        except Exception as e:
            logger.exception("Error al guardar gasto automático para e-CF %s: %s", encf, e)
            return False, str(e)

    @classmethod
    def _find_existing_expense(cls, owner_uid, encf, sender_rnc, sandbox=True, company_id=None):
        """Busca si el e-NCF ya está registrado en gastos."""
        try:
            expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, company_id=company_id)
            for exp in expenses:
                e_ncf = exp.get("ncf") or exp.get("encf") or ""
                e_rnc = "".join(filter(str.isdigit, str(exp.get("rncEmisor") or "")))
                if e_ncf == encf and (not sender_rnc or e_rnc == sender_rnc):
                    return exp
        except Exception as e:
            logger.warning("Error al buscar gasto existente para %s: %s", encf, e)
        return None

    @classmethod
    def _mark_ecf_as_registered(cls, owner_uid, ecf_doc_id, expense_id, tipo_gasto="02", sandbox=True):
        """Actualiza el documento en received_ecf para marcarlo registrado."""
        if not ecf_doc_id or db_firestore is None:
            return
        try:
            coll = ReceptorRepository._resolve_collection(owner_uid, "received_ecf", sandbox=sandbox)
            coll.document(ecf_doc_id).update({
                "registeredIn606": True,
                "expenseId": expense_id,
                "tipoGastoDGII": tipo_gasto,
                "processedAt": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.warning("No se pudo actualizar metadata en received_ecf %s: %s", ecf_doc_id, e)

    @classmethod
    def sync_unprocessed_received_ecfs(cls, owner_uid, sandbox=True, company_id=None):
        """Sincroniza todos los e-CF recibidos históricos que aún no figuren en 606."""
        processed = 0
        errors = 0
        try:
            documents = ReceptorRepository.list_received_ecf(owner_uid, sandbox=sandbox, limit=None)
            for doc in documents:
                if str(doc.get("estado_arecf", "0")) != "0":
                    continue
                if doc.get("registeredIn606"):
                    continue
                ok, _ = cls.process_received_ecf(owner_uid, doc, sandbox=sandbox, company_id=company_id)
                if ok:
                    processed += 1
                else:
                    errors += 1
        except Exception as e:
            logger.exception("Error en sync_unprocessed_received_ecfs: %s", e)
        return {"processed": processed, "errors": errors}
