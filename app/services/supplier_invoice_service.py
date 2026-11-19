import uuid
import re
from datetime import datetime, timezone

try:
    from app.services.db_service import db_firestore, firebase_initialized, firebase_storage_bucket, DatabaseService, _company_coll
    from firebase_admin import firestore as _fstore  # needed for ArrayUnion
except ImportError:
    db_firestore = None
    firebase_initialized = False
    firebase_storage_bucket = None
    DatabaseService = None
    _fstore = None
    _company_coll = None


def serialize_field(val):
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


CXP_STATUSES = ["Pendiente", "Abonado", "Pagado", "Vencido", "Anulada"]

VOIDED_INVOICE_STATUSES = {"anulada", "anulada_dgii", "voided"}
COMPANY_ISSUED_ECF_TYPES = {"E41", "E43", "E47"}
REJECTED_DGII_STATES = {"REJECTED", "RECHAZADO", "RECHAZADA", "FAILED"}
ACCEPTED_DGII_STATES = {"ACCEPTED", "ACCEPTED_CONDITIONAL", "ACEPTADO", "ACEPTADO_CONDICIONAL", "PENDING", "EN_PROCESO"}

ALLOWED_MIME_TYPES = ["application/pdf", "image/jpeg", "image/png"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Tolerancias por defecto para validar precios e ITBIS de la factura contra la OC.
DEFAULT_PRICE_TOLERANCE_RELATIVE = 0.02   # 2% sobre el precio unitario de la OC
DEFAULT_PRICE_TOLERANCE_ABSOLUTE = 0.01   # epsilon de redondeo
DEFAULT_ITBIS_TOLERANCE = 0.005           # 0.5 puntos porcentuales


class SupplierInvoiceGuardError(Exception):
    """No se pudo verificar una condición de seguridad; la operación debe bloquearse."""


class SupplierInvoiceIntegrityError(Exception):
    """La factura o su asiento contable quedaron en un estado inconsistente."""


class SupplierInvoiceService:

    @classmethod
    def _coll(cls, sandbox):
        return "sandbox_supplier_invoices" if sandbox else "supplier_invoices"

    @classmethod
    def _coll_ref(cls, owner_uid=None, sandbox=True, company_id=None):
        from app.services.company_authorization import require_company_id
        return _company_coll(
            company_id=require_company_id(company_id, "SupplierInvoiceService"),
            coll_name=cls._coll(sandbox),
        )

    @classmethod
    def _group_coll_ref(cls, owner_uid=None, sandbox=True, company_id=None):
        from app.services.company_authorization import require_company_id
        return _company_coll(
            company_id=require_company_id(company_id, "SupplierInvoiceService group"),
            coll_name="sandbox_cxp_payment_groups" if sandbox else "cxp_payment_groups",
        )

    @classmethod
    def _available_balance(cls, doc_ref, data):
        total = float(data.get("total", 0))
        current_rem = float(data.get("cxpRemainingBalance", total))
        pending_sum = 0.0
        for pdoc in doc_ref.collection("cxp_payments").get():
            pd = pdoc.to_dict() or {}
            if str(pd.get("approvalStatus") or "").lower() == "pending":
                pending_sum += float(pd.get("amount", 0) or 0)
        return round(current_rem - pending_sum, 2)

    @classmethod
    def _counter_ref(cls, owner_uid=None, company_id=None):
        from app.services.company_authorization import require_company_id
        return _company_coll(
            company_id=require_company_id(company_id, "SupplierInvoiceService counter"),
            coll_name="config",
        ).document("supplier_invoice_counter")

    @classmethod
    def _get_next_counter(cls, owner_uid=None, company_id=None):
        """Atomically increment the supplier invoice counter using Firestore transaction."""
        from google.cloud.firestore import Transaction

        transaction = db_firestore.transaction()

        @firestore.transactional
        def increment(transaction):
            ref = cls._counter_ref(owner_uid=owner_uid, company_id=company_id)
            doc = ref.get(transaction=transaction)
            year = datetime.now(timezone.utc).strftime("%Y")

            if doc.exists:
                data = doc.to_dict()
                last_year = data.get("year", "")
                last_num = data.get("lastNumber", 0)
                if last_year == year:
                    next_num = last_num + 1
                else:
                    next_num = 1
            else:
                next_num = 1

            transaction.set(ref, {
                "year": year,
                "lastNumber": next_num,
            })
            return next_num

        try:
            return increment(transaction)
        except Exception as e:
            print(f"⚠️ Error en contador atómico de facturas proveedor: {e}")
            raise

    @classmethod
    def get_all(cls, owner_uid=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return []
        invoices = []
        try:
            docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                invoices.append(data)
            invoices.sort(key=lambda x: x.get("invoiceNumber", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener facturas proveedor: {e}")
        return invoices

    @classmethod
    def get(cls, owner_uid=None, invoice_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            doc = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener factura proveedor {invoice_id}: {e}")
        return None

    @classmethod
    def get_by_po(cls, owner_uid=None, po_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return []
        invoices = []
        try:
            docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)\
                .where("poId", "==", po_id).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                invoices.append(data)
            invoices.sort(key=lambda x: x.get("invoiceNumber", ""))
        except Exception as e:
            print(f"⚠️ Error al obtener facturas de OC {po_id}: {e}")
        return invoices

    @classmethod
    def get_by_receipt(cls, owner_uid=None, receipt_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None:
            return []
        invoices = []
        try:
            docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)\
                .where("receiptId", "==", receipt_id).get()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                invoices.append(data)
        except Exception as e:
            print(f"⚠️ Error al obtener facturas de recepción {receipt_id}: {e}")
        return invoices

    @classmethod
    def get_next_invoice_number(cls, owner_uid=None, sandbox=True, company_id=None):
        try:
            next_num = cls._get_next_counter(owner_uid=owner_uid, company_id=company_id)
        except Exception:
            year = datetime.now(timezone.utc).strftime("%Y")
            max_num = 0
            invoices = cls.get_all(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)
            for inv in invoices:
                inv_num = inv.get("invoiceNumber", "")
                m = re.match(rf"^FI-{year}-(\d{{4}})$", inv_num)
                if m:
                    num = int(m.group(1))
                    if num > max_num:
                        max_num = num
            next_num = max_num + 1
        year = datetime.now(timezone.utc).strftime("%Y")
        return f"FI-{year}-{next_num:04d}"

    @classmethod
    def _check_ncf_unique(cls, owner_uid=None, ncf=None, sandbox=True, exclude_id=None, company_id=None):
        """Check if supplierInvoiceNumber or NCF already exists."""
        if not ncf or not firebase_initialized:
            return True
        try:
            docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)\
                .where("supplierInvoiceNumber", "==", ncf).get()
            for doc in docs:
                if exclude_id and doc.id == exclude_id:
                    continue
                return False
            if len(ncf) >= 8:
                docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)\
                    .where("ncf", "==", ncf).get()
                for doc in docs:
                    if exclude_id and doc.id == exclude_id:
                        continue
                    return False
        except Exception as e:
            print(f"⚠️ Error al verificar NCF duplicado: {e}")
        return True

    @staticmethod
    def is_voided(invoice):
        """Regla única para documentos de proveedor anulados."""
        invoice = invoice or {}
        status = str(invoice.get("status", "")).strip().lower()
        cxp_status = str(invoice.get("cxpStatus", "")).strip().lower()
        void_status = str(invoice.get("voidStatus", "")).strip().lower()
        return status in VOIDED_INVOICE_STATUSES or cxp_status == "anulada" or void_status == "completed"

    @staticmethod
    def active_invoices(invoices):
        """Devuelve solo facturas no anuladas para reportes y CxP."""
        return [inv for inv in (invoices or []) if not SupplierInvoiceService.is_voided(inv)]

    @staticmethod
    def emission_block_reason(invoice):
        """Motivo por el que una factura no debe emitirse/reemitirse, o None."""
        if SupplierInvoiceService.is_voided(invoice):
            return "No se puede emitir una factura anulada."
        if str((invoice or {}).get("voidStatus") or "").strip().lower() in ("pending", "failed"):
            return "La factura tiene una anulación en proceso; no se puede emitir."
        return None

    @staticmethod
    def is_company_issued(invoice):
        """Distingue un e-CF emitido por VykOne de un documento recibido.

        Las facturas recibidas usan el NCF del proveedor y no tienen la firma,
        trackId ni metadatos de emisión propios de VykOne. Las de certificación
        (E41/E43/E47) llevan e-NCF asignado por nuestras secuencias.
        """
        invoice = invoice or {}
        encf = str(invoice.get("encf") or "").strip()
        ecf_type = str(invoice.get("ecfType") or "").strip().upper()
        status = str(invoice.get("status") or "").strip().lower()
        if invoice.get("isAutoEmitted"):
            return True
        if not encf:
            return False
        if any(invoice.get(k) for k in ("xmlSignature", "trackId", "emisionMode", "contingencyEmittedAt")):
            return True
        if status in ("emitida", "rechazado_dgii"):
            return True
        if ecf_type in COMPANY_ISSUED_ECF_TYPES and not str(invoice.get("ncf") or "").strip():
            return True
        return False

    @classmethod
    def fiscal_void_block_reason(cls, invoice):
        """Motivo por el que la anulación local está bloqueada por estado fiscal.

        La anulación de un comprobante propio ya aceptado (o en contingencia /
        pendiente de DGII) exige el flujo fiscal externo (ANECF) y no puede
        resolverse marcando la factura local como anulada.
        """
        invoice = invoice or {}
        if not cls.is_company_issued(invoice):
            return None
        status = str(invoice.get("status") or "").strip().lower()
        dgii_state = str(
            invoice.get("dgiiStatus") or invoice.get("estadoDGII") or ""
        ).strip().upper()
        if status == "rechazado_dgii" or dgii_state in REJECTED_DGII_STATES:
            return None
        if (invoice.get("contingencyEmittedAt")
                or str(invoice.get("emisionMode") or "").upper() == "FALLBACK"
                or dgii_state in {"CONTINGENCY", "CONTINGENCIA"}):
            return ("La factura fue emitida en contingencia y aún no está sincronizada con la DGII. "
                    "Sincronice o anule el comprobante por el flujo fiscal correspondiente antes de la anulación local.")
        if (status == "emitida" or invoice.get("isSyncedWithDGII")
                or dgii_state in ACCEPTED_DGII_STATES):
            return ("La factura fue emitida/aceptada por la DGII. Debe anularse mediante el flujo "
                    "de comprobantes electrónicos (ANECF) y luego registrar la anulación local.")
        if str(invoice.get("encf") or "").strip():
            return ("La factura tiene un e-NCF asignado y está pendiente de emisión o sincronización. "
                    "Resuelva el estado fiscal antes de anularla localmente.")
        return None

    @staticmethod
    def effective_accounting_date(invoice, entries=None):
        """Fecha contable efectiva: la del asiento activo o, si no existe, la del documento."""
        for entry in entries or []:
            if entry.get("date"):
                return str(entry.get("date"))[:10]
        invoice = invoice or {}
        return str(invoice.get("date") or invoice.get("createdAt") or "")[:10]

    @classmethod
    def validate_period(cls, company_id, date_str):
        """Valida que el período fiscal de la fecha esté abierto.

        Lanza ValueError si el período está cerrado o si no pudo verificarse
        (fail-closed). No-op solo si no hay fecha.
        """
        if not date_str:
            return
        try:
            from app.services.fiscal_period_service import FiscalPeriodService
        except ImportError:
            return
        FiscalPeriodService.validate_period_open(company_id, str(date_str), company_id=company_id)

    @classmethod
    def _active_accounting_entries(cls, owner_uid=None, invoice_id=None, sandbox=True, company_id=None):
        try:
            entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox, company_id=company_id)
            return [
                e for e in (entries or [])
                if e.get("status") != "voided"
                and e.get("referenceId") == invoice_id
                and e.get("referenceType") in ("supplier_invoice", "expense")
            ]
        except Exception as e:
            raise SupplierInvoiceGuardError(
                "No se pudo verificar el asiento contable de la factura; operación bloqueada."
            ) from e

    @classmethod
    def has_payments(cls, owner_uid=None, invoice_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None or not invoice_id:
            return False
        try:
            docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id)\
                .document(invoice_id).collection("cxp_payments").limit(1).get()
            return len(docs) > 0
        except Exception as e:
            print(f"⚠️ Error al verificar pagos de factura {invoice_id}: {e}")
            raise SupplierInvoiceGuardError(
                "No se pudo verificar si la factura tiene pagos; operación bloqueada."
            ) from e

    @classmethod
    def has_accounting_entry(cls, owner_uid=None, invoice_id=None, sandbox=True, company_id=None):
        if not firebase_initialized or db_firestore is None or not invoice_id:
            return False
        return bool(cls._active_accounting_entries(
            owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id
        ))

    @staticmethod
    def is_emitted(invoice):
        invoice = invoice or {}
        status = str(invoice.get("status") or "").strip().lower()
        dgii_state = str(invoice.get("dgiiStatus") or "").strip().upper()
        if status == "rechazado_dgii" or dgii_state in REJECTED_DGII_STATES:
            return False
        if status == "emitida":
            return True
        if invoice.get("isSyncedWithDGII") and invoice.get("encf"):
            return True
        return bool(
            SupplierInvoiceService.is_company_issued(invoice)
            and (invoice.get("xmlSignature") or invoice.get("trackId"))
        )

    @classmethod
    def validate_invoice_against_po(cls, po, invoice_items):
        """Valida que la factura no exceda lo solicitado/recibido ni duplique cantidades.

        Devuelve ``(ok, errores)``. Para partidas inventariables el tope es lo
        recibido; para servicios, lo solicitado. Se descuenta lo ya facturado
        (``invoicedQuantity``) para impedir facturas duplicadas por la misma OC.
        """
        errors = []
        po_items = (po or {}).get("items", [])
        for inv_item in (invoice_items or []):
            po_item_id = inv_item.get("poItemId") or inv_item.get("id") or ""
            if not po_item_id:
                continue
            po_item = next((i for i in po_items if i.get("id") == po_item_id), None)
            label = inv_item.get("itemName") or inv_item.get("name") or (po_item.get("name") if po_item else "—")
            if not po_item:
                errors.append(f"La partida '{label}' no pertenece a la orden de compra.")
                continue
            inv_qty = round(float(inv_item.get("quantity", 0) or 0), 4)
            if inv_qty <= 0:
                continue
            is_inv = po_item.get("isInventoriable", True)
            if not is_inv:
                service_status = str(po_item.get("serviceStatus") or "pendiente").lower()
                if service_status != "confirmado":
                    estado = "rechazado" if service_status == "rechazado" else "pendiente de confirmación"
                    errors.append(f"El servicio '{label}' no puede facturarse: {estado}.")
                    continue
            if is_inv:
                allowed = float(po_item.get("receivedQuantity", 0) or 0)
            else:
                allowed = float(po_item.get("quantity", 0) or 0)
            already_invoiced = round(float(po_item.get("invoicedQuantity", 0) or 0), 4)
            available = round(allowed - already_invoiced, 4)
            if inv_qty > available + 1e-9:
                errors.append(
                    f"Cantidad a facturar ({inv_qty:g}) de '{label}' excede lo disponible "
                    f"(límite {allowed:g}, ya facturado {already_invoiced:g})."
                )
        return (len(errors) == 0, errors)

    @classmethod
    def validate_invoice_prices(cls, po, invoice_items, tolerances=None):
        """Compara precio e ITBIS facturados contra la OC con tolerancias configurables.

        Devuelve ``(ok, differences)``. Cada diferencia es un dict con
        ``severity``: ``"error"`` (excede la tolerancia → bloquea la factura) o
        ``"warning"`` (dentro de tolerancia, se registra para trazabilidad).
        """
        tol = dict(tolerances or {})
        price_rel = float(tol.get("price_relative", DEFAULT_PRICE_TOLERANCE_RELATIVE))
        price_abs = float(tol.get("price_absolute", DEFAULT_PRICE_TOLERANCE_ABSOLUTE))
        itbis_tol = float(tol.get("itbis_absolute", DEFAULT_ITBIS_TOLERANCE))

        differences = []
        po_items = (po or {}).get("items", [])
        for inv_item in (invoice_items or []):
            po_item_id = inv_item.get("poItemId") or inv_item.get("id") or ""
            if not po_item_id:
                continue
            po_item = next((i for i in po_items if i.get("id") == po_item_id), None)
            if not po_item:
                continue
            label = inv_item.get("itemName") or inv_item.get("name") or po_item.get("name", "—")

            po_price = round(float(po_item.get("unitPrice", 0) or 0), 4)
            inv_price = round(float(inv_item.get("unitPrice", 0) or 0), 4)
            price_delta = round(inv_price - po_price, 4)
            price_limit = round(price_abs + price_rel * abs(po_price), 4)
            if abs(price_delta) > price_limit + 1e-9:
                differences.append({
                    "poItemId": po_item_id, "itemName": label, "field": "unitPrice",
                    "poValue": po_price, "invoiceValue": inv_price, "delta": price_delta,
                    "severity": "error",
                    "message": (f"Precio de '{label}' difiere de la OC: OC {po_price:,.2f}, "
                                f"factura {inv_price:,.2f} (tolerancia {price_limit:,.2f})."),
                })
            elif abs(price_delta) > 1e-9:
                differences.append({
                    "poItemId": po_item_id, "itemName": label, "field": "unitPrice",
                    "poValue": po_price, "invoiceValue": inv_price, "delta": price_delta,
                    "severity": "warning",
                    "message": (f"Precio de '{label}' difiere de la OC dentro de tolerancia: "
                                f"OC {po_price:,.2f}, factura {inv_price:,.2f}."),
                })

            po_itbis = round(float(po_item.get("itbisRate", 0) or 0), 4)
            inv_itbis = round(float(inv_item.get("itbisRate", 0) or 0), 4)
            itbis_delta = round(inv_itbis - po_itbis, 4)
            if abs(itbis_delta) > itbis_tol + 1e-9:
                differences.append({
                    "poItemId": po_item_id, "itemName": label, "field": "itbisRate",
                    "poValue": po_itbis, "invoiceValue": inv_itbis, "delta": itbis_delta,
                    "severity": "error",
                    "message": (f"ITBIS de '{label}' difiere de la OC: OC {po_itbis:.4f}, "
                                f"factura {inv_itbis:.4f}."),
                })
            elif abs(itbis_delta) > 1e-9:
                differences.append({
                    "poItemId": po_item_id, "itemName": label, "field": "itbisRate",
                    "poValue": po_itbis, "invoiceValue": inv_itbis, "delta": itbis_delta,
                    "severity": "warning",
                    "message": f"ITBIS de '{label}' difiere de la OC dentro de tolerancia.",
                })

        ok = all(d["severity"] != "error" for d in differences)
        return ok, differences

    @classmethod
    def record_invoice_quantities(cls, owner_uid=None, po_id=None, invoice_items=None,
                                  sandbox=True, company_id=None):
        """Acumula ``invoicedQuantity`` en las partidas de la OC tras facturar."""
        if not po_id:
            return
        try:
            from app.services.purchase_order_service import PurchaseOrderService
            po = PurchaseOrderService.get_purchase_order(
                owner_uid=owner_uid, po_id=po_id, sandbox=sandbox, company_id=company_id
            )
            if not po:
                return
            po_items = po.get("items", [])
            changed = False
            for inv_item in (invoice_items or []):
                po_item_id = inv_item.get("poItemId") or inv_item.get("id") or ""
                po_item = next((i for i in po_items if i.get("id") == po_item_id), None)
                if not po_item:
                    continue
                inv_qty = round(float(inv_item.get("quantity", 0) or 0), 4)
                if inv_qty <= 0:
                    continue
                po_item["invoicedQuantity"] = round(
                    float(po_item.get("invoicedQuantity", 0) or 0) + inv_qty, 4
                )
                changed = True
            if changed:
                PurchaseOrderService.save_purchase_order(
                    owner_uid=owner_uid, po_id=po_id, po_dict=po,
                    sandbox=sandbox, company_id=company_id,
                )
        except Exception as e:
            print(f"⚠️ Error al registrar cantidades facturadas de OC {po_id}: {e}")

    @staticmethod
    def _retention_calculated(doc):
        """Retención ISR/ITBIS calculada de un documento (factura o gasto).

        Acepta los campos nuevos (``retentionIsrAmount``/``retentionItbisAmount``)
        con retrocompatibilidad a ``isrWithheld``/``itbisWithheld`` (gastos).
        """
        doc = doc or {}
        isr = float(doc.get("retentionIsrAmount") or doc.get("isrWithheld") or 0)
        itbis = float(doc.get("retentionItbisAmount") or doc.get("itbisWithheld") or 0)
        return round(isr, 2), round(itbis, 2)

    @classmethod
    def calculate_retention(cls, supplier, subtotal, discount, itbis):
        """Calcula la retención ISR/ITBIS de una factura de proveedor.

        - Base ISR = subtotal − descuento (base gravada, sin ITBIS).
        - Base ITBIS = monto de ITBIS (la retención es un % del ITBIS).
        Devuelve un dict con base/tasa/monto/regla/línea IR-17 y acumulados a cero.
        """
        from app.services.tax_engine import TaxEngine
        engine = TaxEngine(country="DO")
        resolved = engine.resolve_withholding(supplier or {})

        isr_base = round(float(subtotal or 0) - float(discount or 0), 2)
        isr_amount = round(isr_base * float(resolved["isr_rate"]), 2)
        itbis_base = round(float(itbis or 0), 2)
        itbis_amount = round(itbis_base * float(resolved["itbis_rate"]), 2)

        return {
            "retentionIsrBase": isr_base,
            "retentionIsrRate": resolved["isr_rate"],
            "retentionIsrAmount": isr_amount,
            "retentionIsrRule": resolved["isr_rule"] or "",
            "retentionIsrIr17Line": resolved["isr_ir17_line"],
            "retentionItbisBase": itbis_base,
            "retentionItbisRate": resolved["itbis_rate"],
            "retentionItbisAmount": itbis_amount,
            "retentionItbisRule": resolved["itbis_rule"] or "",
            "retentionStatus": "calculated",
            "retentionIsrApplied": 0.0,
            "retentionItbisApplied": 0.0,
        }

    @classmethod
    def create(cls, owner_uid=None, data=None, sandbox=True, company_id=None):
        invoice_id = str(uuid.uuid4())
        data["id"] = invoice_id
        data["ownerUID"] = owner_uid
        if "createdAt" not in data or not data["createdAt"]:
            data["createdAt"] = serialize_field(datetime.now(timezone.utc))
        data["updatedAt"] = serialize_field(datetime.now(timezone.utc))

        total = float(data.get("total", 0))
        data.setdefault("cxpStatus", "Pendiente")
        data.setdefault("cxpRemainingBalance", total)
        data.setdefault("status", "registrada")
        data.setdefault("currency", "DOP")
        data.setdefault("exchangeRate", 1.0)
        data.setdefault("notes", "")
        data.setdefault("attachmentUrls", [])
        data.setdefault("items", [])
        data.setdefault("paymentMethod", "")
        data.setdefault("paymentReference", "")
        data.setdefault("supplierRnc", "")
        data.setdefault("supplierCedula", "")
        data.setdefault("supplierType", "formal")
        data.setdefault("ecfType", "E31")
        data.setdefault("cne", "")
        data.setdefault("paymentTerms", "contado")
        data.setdefault("bankAccountId", "")
        data.setdefault("retainedISR", 0.0)
        data.setdefault("retainedITBIS", 0.0)
        data.setdefault("tipoGastoDGII", "02")
        data.setdefault("tipoServicio609", "")
        data.setdefault("detalleServicio609", "")
        data.setdefault("poId", "")
        data.setdefault("poNumber", "")
        data.setdefault("branchId", "")
        data.setdefault("projectId", None)
        data.setdefault("comentario", "")

        cls.validate_period(company_id, data.get("date") or "")

        # Calcular retención ISR/ITBIS si hay proveedor y aún no viene calculada
        if data.get("supplierId") and not data.get("retentionIsrBase"):
            try:
                from app.services.supplier_service import SupplierService
                supplier = SupplierService.get_supplier(
                    owner_uid=owner_uid, supplier_id=data["supplierId"],
                    sandbox=sandbox, company_id=company_id,
                )
                if supplier:
                    retention = cls.calculate_retention(
                        supplier, data.get("subtotal", 0), data.get("discount", 0), data.get("itbis", 0)
                    )
                    data.update(retention)
            except Exception as e:
                print(f"⚠️ Error al calcular retención de la factura: {e}")

        if firebase_initialized and db_firestore is not None:
            from app.services.db_service import run_firestore_transaction
            run_firestore_transaction(cls._create_invoice_tx, owner_uid, invoice_id, data, sandbox, company_id)
        return data

    @classmethod
    def _create_invoice_tx(cls, transaction, owner_uid, invoice_id, data, sandbox, company_id):
        """Cuerpo atómico de creación: valida contra la OC, escribe la factura y
        acumula las cantidades facturadas en la misma transacción."""
        po_id = data.get("poId") or ""
        if po_id:
            po_ref = _company_coll(
                company_id=company_id, owner_uid=owner_uid,
                coll_name="sandbox_purchase_orders" if sandbox else "purchase_orders",
            ).document(po_id)
            po_doc = po_ref.get(transaction=transaction)
            if po_doc.exists:
                po = po_doc.to_dict() or {}
                ok, errors = cls.validate_invoice_against_po(po, data.get("items", []))
                if not ok:
                    raise ValueError(" ".join(errors))
                ok, diffs = cls.validate_invoice_prices(po, data.get("items", []))
                if not ok:
                    raise ValueError(" ".join(d["message"] for d in diffs if d["severity"] == "error"))
                data["priceDifferences"] = [d for d in diffs if d["severity"] == "warning"]

                po_items = po.get("items", [])
                changed = False
                for inv_item in (data.get("items") or []):
                    pi_id = inv_item.get("poItemId") or inv_item.get("id") or ""
                    pi = next((i for i in po_items if i.get("id") == pi_id), None)
                    if not pi:
                        continue
                    q = round(float(inv_item.get("quantity", 0) or 0), 4)
                    if q <= 0:
                        continue
                    pi["invoicedQuantity"] = round(float(pi.get("invoicedQuantity", 0) or 0) + q, 4)
                    changed = True
                if changed:
                    transaction.set(po_ref, po)

        invoice_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
        transaction.set(invoice_ref, data)
        return data

    @classmethod
    def update(cls, owner_uid=None, invoice_id=None, data=None, sandbox=True, company_id=None):
        """Update non-fiscal fields of a supplier invoice.

        Una factura anulada conserva trazabilidad: solo se permite actualizar
        metadatos de comprobante/QR/auditoría, nunca importes, estado CxP,
        datos fiscales ni líneas.
        """
        if not firebase_initialized or db_firestore is None:
            return False
        try:
            data = dict(data or {})
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False
            existing = doc.to_dict() or {}
            allowed_on_void = {"qrCodeURL", "xmlContent", "updatedAt", "accountingStatus", "accountingError"}
            allowed_on_pending_void = allowed_on_void | {
                "voidStatus", "voidError", "voidEntryIds", "voidRequestedAt", "voidRequestedBy"
            }
            if cls.is_voided(existing) and set(data) - allowed_on_void:
                return False
            if str(existing.get("voidStatus") or "").lower() in ("pending", "failed") and set(data) - allowed_on_pending_void:
                return False
            data["updatedAt"] = serialize_field(datetime.now(timezone.utc))
            doc_ref.update(data)
            return True
        except Exception as e:
            print(f"⚠️ Error al actualizar factura proveedor {invoice_id}: {e}")
            return False

    @classmethod
    def add_attachment(cls, owner_uid=None, invoice_id=None, file_data=None, file_name=None, mime_type=None, sandbox=True, company_id=None):
        """Add an attachment to an existing supplier invoice."""
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            safe_name = file_name.replace(" ", "_")
            if company_id:
                dest_path = f"companies/{company_id}/supplier_invoices/{uuid.uuid4().hex}/{safe_name}"
            else:
                dest_path = f"users/{owner_uid}/supplier_invoices/{uuid.uuid4().hex}/{safe_name}"
            public_url = DatabaseService.upload_file_to_storage(file_data, dest_path, mime_type)
            if public_url:
                doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
                doc_ref.update({
                    "attachmentUrls": _fstore.ArrayUnion([public_url]),
                    "updatedAt": serialize_field(datetime.now(timezone.utc)),
                })
            return public_url
        except Exception as e:
            print(f"⚠️ Error al agregar attachment a factura proveedor {invoice_id}: {e}")
            return None

    @classmethod
    def save_payment(cls, owner_uid=None, invoice_id=None, payment_amount=0, registered_by="Usuario",
                     sandbox=True, payment_method="", payment_reference="", bank_account_id="", company_id=None,
                     payment_date=None, requested_by_uid=""):
        """Registra un pago de factura de proveedor, pendiente de aprobación.

        El pago queda ``approvalStatus=pending``. El saldo de CxP y el asiento
        contable solo se aplican al aprobar (``approve_payment``).
        """
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            payment_amount = float(payment_amount or 0)
            if payment_amount <= 0:
                return False, "El monto del pago debe ser mayor a cero."
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Factura proveedor no encontrada."
            data = doc.to_dict() or {}
            if cls.is_voided(data):
                return False, "No se puede registrar un pago sobre una factura anulada."
            if str(data.get("voidStatus") or "").lower() in ("pending", "failed"):
                return False, "La factura tiene una anulación en proceso. Resuelva la anulación antes de registrar pagos."
            current_status = data.get("cxpStatus", "Pendiente")
            if current_status == "Pagado":
                return False, "La factura ya está pagada. No se pueden registrar más pagos."
            total = float(data.get("total", 0))
            current_rem = float(data.get("cxpRemainingBalance", total))
            pending_sum = 0.0
            for pdoc in doc_ref.collection("cxp_payments").get():
                pd = pdoc.to_dict() or {}
                if str(pd.get("approvalStatus") or "").lower() == "pending":
                    pending_sum += float(pd.get("amount", 0) or 0)
            available = round(current_rem - pending_sum, 2)
            if payment_amount > available:
                return False, f"El monto (RD$ {payment_amount:,.2f}) excede el saldo disponible (RD$ {available:,.2f}) considerando pagos pendientes de aprobación."

            now = datetime.now(timezone.utc)
            payment_date_str = str(payment_date or now.strftime("%Y-%m-%d"))[:10]
            cls.validate_period(company_id, payment_date_str)

            payment_id = str(uuid.uuid4())
            payment_doc = {
                "id": payment_id,
                "amount": payment_amount,
                "paymentDate": (
                    f"{payment_date_str}T00:00:00+00:00" if payment_date else now.isoformat()
                ),
                "registeredBy": registered_by,
                "createdAt": now.isoformat(),
                "method": payment_method or "",
                "reference": payment_reference or "",
                "bankAccountId": bank_account_id,
                "approvalStatus": "pending",
                "requestedBy": requested_by_uid or "",
                "requestedByName": registered_by,
                "requestedAt": now.isoformat(),
            }
            doc_ref.collection("cxp_payments").document(payment_id).set(payment_doc)

            return True, f"Pago de RD$ {payment_amount:,.2f} registrado y pendiente de aprobación."
        except ValueError as e:
            return False, str(e)
        except SupplierInvoiceGuardError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error en save_payment supplier_invoice: {e}")
            return False, "No se pudo registrar el pago. Intente nuevamente o contacte soporte."

    @classmethod
    def _approve_payment_tx(cls, transaction, owner_uid, invoice_id, payment_id,
                            approved_by, approved_by_uid, notes, company_id, sandbox):
        """Cuerpo atómico de la aprobación (estado + saldo) dentro de una transacción."""
        inv_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
        inv_doc = inv_ref.get(transaction=transaction)
        if not inv_doc.exists:
            raise ValueError("Factura proveedor no encontrada.")
        data = inv_doc.to_dict() or {}
        if cls.is_voided(data):
            raise ValueError("No se puede aprobar un pago sobre una factura anulada.")
        pay_ref = inv_ref.collection("cxp_payments").document(payment_id)
        pay_doc = pay_ref.get(transaction=transaction)
        if not pay_doc.exists:
            raise ValueError("Pago no encontrado.")
        pay_data = pay_doc.to_dict() or {}
        status = str(pay_data.get("approvalStatus") or "").lower()
        if status == "approved":
            return "already_approved"
        if status != "pending":
            raise ValueError("Solo se puede aprobar un pago pendiente de aprobación.")

        amount = round(float(pay_data.get("amount", 0) or 0), 2)
        total = float(data.get("total", 0))
        current_rem = float(data.get("cxpRemainingBalance", total))
        if amount > current_rem:
            raise ValueError(f"El monto (RD$ {amount:,.2f}) excede el saldo pendiente (RD$ {current_rem:,.2f}).")

        new_rem = round(current_rem - amount, 2)
        new_status = "Pagado" if new_rem <= 0.01 else "Abonado"
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        due_date = data.get("dueDate", "")
        if new_status in ("Abonado", "Pendiente") and due_date and due_date < today_str:
            new_status = "Vencido"

        # Aplicar retención proporcional al pago (acumulado por factura)
        ret_isr_applied = 0.0
        ret_itbis_applied = 0.0
        if total > 0:
            factor = amount / total
            ret_isr_applied = round(float(data.get("retentionIsrAmount", 0) or 0) * factor, 2)
            ret_itbis_applied = round(float(data.get("retentionItbisAmount", 0) or 0) * factor, 2)

        invoice_update = {
            "cxpRemainingBalance": new_rem,
            "cxpStatus": new_status,
            "updatedAt": serialize_field(datetime.now(timezone.utc)),
        }
        if ret_isr_applied or ret_itbis_applied:
            invoice_update["retentionIsrApplied"] = round(
                float(data.get("retentionIsrApplied", 0) or 0) + ret_isr_applied, 2
            )
            invoice_update["retentionItbisApplied"] = round(
                float(data.get("retentionItbisApplied", 0) or 0) + ret_itbis_applied, 2
            )
            invoice_update["retentionStatus"] = "applied" if new_rem <= 0.01 else "partial"

        transaction.update(inv_ref, invoice_update)
        transaction.update(pay_ref, {
            "approvalStatus": "approved",
            "approvedBy": approved_by,
            "approvedByUid": approved_by_uid or "",
            "approvedAt": datetime.now(timezone.utc).isoformat(),
            "approvalNotes": notes or "",
            "retentionIsrApplied": ret_isr_applied,
            "retentionItbisApplied": ret_itbis_applied,
        })
        return "approved"

    @classmethod
    def approve_payment(cls, owner_uid=None, invoice_id=None, payment_id=None, approved_by="",
                        approved_by_uid="", notes="", sandbox=True, company_id=None):
        """Aprueba un pago pendiente de forma atómica (estado + saldo) y lo contabiliza."""
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            pay_ref = doc_ref.collection("cxp_payments").document(payment_id)
            pay_snap = pay_ref.get()
            if not pay_snap.exists:
                return False, "Pago no encontrado."
            payment_date_str = str((pay_snap.to_dict() or {}).get("paymentDate", "") or "")[:10]
            cls.validate_period(company_id, payment_date_str)

            from app.services.db_service import run_firestore_transaction
            result = run_firestore_transaction(
                cls._approve_payment_tx, owner_uid, invoice_id, payment_id,
                approved_by, approved_by_uid, notes, company_id, sandbox,
            )
            if result == "already_approved":
                return True, "El pago ya estaba aprobado."

            # Post-commit: saldo bancario + contabilización (idempotentes)
            pay_data = pay_ref.get().to_dict() or {}
            data = doc_ref.get().to_dict() or {}
            amount = round(float(pay_data.get("amount", 0) or 0), 2)
            bank_account_id = pay_data.get("bankAccountId", "")
            if bank_account_id:
                try:
                    from app.services.db_service import DatabaseService
                    bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox, company_id=company_id)
                    if bank_acc:
                        new_balance = bank_acc["currentBalance"] - amount
                        DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                            **bank_acc, "currentBalance": new_balance
                        }, sandbox=sandbox, company_id=company_id)
                except Exception as bank_err:
                    print(f"⚠️ Error al actualizar saldo bancario al aprobar pago: {bank_err}")

            accounting_entry_id = ""
            accounting_error = ""
            try:
                from app.services.accounting_service import AccountingService, AccountingPostingError
                entry = AccountingService.auto_generate_cxp_payment_entry(
                    company_id=company_id,
                    payment_id=payment_id,
                    amount=amount,
                    payment_date=payment_date_str,
                    bank_account_id=bank_account_id,
                    payment_method=pay_data.get("method", ""),
                    concept=f"Pago factura {data.get('supplierInvoiceNumber') or data.get('ncf') or ''} - {data.get('supplierName', '')}",
                    supplier_id=data.get("supplierId", ""),
                    supplier_name=data.get("supplierName", ""),
                    cost_center_id=data.get("costCenterId"),
                    sandbox=sandbox,
                )
                if entry:
                    accounting_entry_id = entry.get("id", "")
            except AccountingPostingError as acc_err:
                accounting_error = str(acc_err)
            except Exception as acc_err:
                accounting_error = str(acc_err)

            pay_ref.update({
                "accountingStatus": "posted" if accounting_entry_id else ("error" if accounting_error else "pending"),
                "accountingEntryId": accounting_entry_id or "",
                "accountingError": accounting_error or "",
            })
            msg = f"Pago de RD$ {amount:,.2f} aprobado."
            if accounting_error:
                msg += " ⚠️ El pago no se pudo contabilizar; revise el módulo de contabilidad."
            return True, msg
        except ValueError as e:
            return False, str(e)
        except SupplierInvoiceGuardError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error al aprobar pago {payment_id}: {e}")
            return False, "No se pudo aprobar el pago. Intente nuevamente."

    @classmethod
    def reject_payment(cls, owner_uid=None, invoice_id=None, payment_id=None, rejected_by="",
                       rejected_by_uid="", notes="", sandbox=True, company_id=None):
        """Rechaza un pago pendiente de aprobación (sin aplicar saldo ni contabilización)."""
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Factura proveedor no encontrada."
            pay_ref = doc_ref.collection("cxp_payments").document(payment_id)
            pay_doc = pay_ref.get()
            if not pay_doc.exists:
                return False, "Pago no encontrado."
            pay_data = pay_doc.to_dict() or {}
            status = str(pay_data.get("approvalStatus") or "").lower()
            if status == "rejected":
                return True, "El pago ya estaba rechazado."
            if status != "pending":
                return False, "Solo se puede rechazar un pago pendiente de aprobación."
            pay_ref.update({
                "approvalStatus": "rejected",
                "rejectedBy": rejected_by,
                "rejectedByUid": rejected_by_uid or "",
                "rejectedAt": datetime.now(timezone.utc).isoformat(),
                "rejectionNotes": notes or "",
            })
            return True, "Pago rechazado."
        except Exception as e:
            print(f"⚠️ Error al rechazar pago {payment_id}: {e}")
            return False, "No se pudo rechazar el pago."

    # ── Pagos multi-factura ──────────────────────────────────────────────

    @classmethod
    def register_multi_invoice_payment(cls, owner_uid=None, supplier_id=None, allocations=None,
                                       registered_by="Usuario", requested_by_uid="", payment_method="",
                                       payment_reference="", bank_account_id="", company_id=None,
                                       sandbox=True, payment_date=None):
        """Registra un pago que cubre varias facturas del mismo proveedor (pendiente de aprobación).

        Devuelve ``(ok, mensaje, group_id)``. ``allocations`` = ``[{"invoiceId", "amount"}]``.
        """
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado.", None
        try:
            allocations = [dict(a) for a in (allocations or [])]
            if not allocations:
                return False, "Debe indicar al menos una factura.", None
            for a in allocations:
                a["amount"] = round(float(a.get("amount", 0) or 0), 2)
            if any(a["amount"] <= 0 for a in allocations):
                return False, "Cada asignación debe ser mayor a cero.", None
            if not supplier_id:
                return False, "Debe indicar el proveedor.", None

            now = datetime.now(timezone.utc)
            payment_date_str = str(payment_date or now.strftime("%Y-%m-%d"))[:10]
            cls.validate_period(company_id, payment_date_str)

            invoice_ids = [a["invoiceId"] for a in allocations]
            if len(set(invoice_ids)) != len(invoice_ids):
                return False, "No se puede asignar la misma factura dos veces en el mismo pago.", None

            inv_data = {}
            for a in allocations:
                inv_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(a["invoiceId"])
                inv_doc = inv_ref.get()
                if not inv_doc.exists:
                    return False, f"Factura {a['invoiceId']} no encontrada.", None
                data = inv_doc.to_dict() or {}
                if cls.is_voided(data):
                    return False, f"No se puede pagar la factura anulada {a['invoiceId']}.", None
                if str(data.get("voidStatus") or "").lower() in ("pending", "failed"):
                    return False, f"La factura {a['invoiceId']} tiene una anulación en proceso.", None
                if str(data.get("cxpStatus") or "") == "Pagado":
                    return False, f"La factura {a['invoiceId']} ya está pagada.", None
                if supplier_id and data.get("supplierId") and data.get("supplierId") != supplier_id:
                    return False, f"La factura {a['invoiceId']} no pertenece al proveedor indicado.", None
                available = cls._available_balance(inv_ref, data)
                if a["amount"] > available:
                    return False, f"La asignación de RD$ {a['amount']:,.2f} excede el saldo disponible (RD$ {available:,.2f}) de la factura {a['invoiceId']}.", None
                inv_data[a["invoiceId"]] = data

            total = round(sum(a["amount"] for a in allocations), 2)
            group_id = str(uuid.uuid4())
            supplier_name = next((d.get("supplierName", "") for d in inv_data.values() if d.get("supplierName")), "")
            group_doc = {
                "id": group_id,
                "supplierId": supplier_id,
                "supplierName": supplier_name,
                "total": total,
                "paymentDate": f"{payment_date_str}T00:00:00+00:00" if payment_date else now.isoformat(),
                "paymentMethod": payment_method or "",
                "reference": payment_reference or "",
                "bankAccountId": bank_account_id or "",
                "approvalStatus": "pending",
                "requestedBy": requested_by_uid or "",
                "requestedByName": registered_by,
                "requestedAt": now.isoformat(),
                "allocations": [{"invoiceId": a["invoiceId"], "amount": a["amount"]} for a in allocations],
                "source": "multi_invoice",
                "createdAt": now.isoformat(),
            }
            cls._group_coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(group_id).set(group_doc)

            for a in allocations:
                alloc_id = f"{group_id}::{a['invoiceId']}"
                alloc_doc = {
                    "id": alloc_id,
                    "amount": a["amount"],
                    "paymentDate": group_doc["paymentDate"],
                    "registeredBy": registered_by,
                    "createdAt": now.isoformat(),
                    "method": payment_method or "",
                    "reference": payment_reference or "",
                    "bankAccountId": bank_account_id or "",
                    "approvalStatus": "pending",
                    "requestedBy": requested_by_uid or "",
                    "requestedByName": registered_by,
                    "requestedAt": now.isoformat(),
                    "groupPaymentId": group_id,
                    "source": "multi_invoice",
                }
                cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(a["invoiceId"]).collection("cxp_payments").document(alloc_id).set(alloc_doc)

            return True, f"Pago de RD$ {total:,.2f} registrado para {len(allocations)} factura(s), pendiente de aprobación.", group_id
        except ValueError as e:
            return False, str(e), None
        except SupplierInvoiceGuardError as e:
            return False, str(e), None
        except Exception as e:
            print(f"⚠️ Error al registrar pago multi-factura: {e}")
            return False, "No se pudo registrar el pago multi-factura.", None

    @classmethod
    def get_multi_invoice_payment(cls, owner_uid=None, group_id=None, company_id=None, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return None
        try:
            d = cls._group_coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(group_id).get()
            if d.exists:
                data = d.to_dict() or {}
                data["id"] = group_id
                return data
        except Exception as e:
            print(f"⚠️ Error al obtener pago multi-factura {group_id}: {e}")
        return None

    @classmethod
    def _approve_multi_invoice_tx(cls, transaction, owner_uid, group_id, approved_by,
                                  approved_by_uid, notes, company_id, sandbox):
        """Cuerpo atómico de aprobación multi-factura (estado + saldos) dentro de una transacción."""
        group_ref = cls._group_coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(group_id)
        group_doc = group_ref.get(transaction=transaction)
        if not group_doc.exists:
            raise ValueError("Pago multi-factura no encontrado.")
        group = group_doc.to_dict() or {}
        status = str(group.get("approvalStatus") or "").lower()
        if status == "approved":
            return "already_approved"
        if status != "pending":
            raise ValueError("Solo se puede aprobar un pago pendiente de aprobación.")

        allocations = group.get("allocations", [])
        for a in allocations:
            inv_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(a["invoiceId"])
            inv_doc = inv_ref.get(transaction=transaction)
            if not inv_doc.exists:
                raise ValueError(f"Factura {a['invoiceId']} no encontrada.")
            data = inv_doc.to_dict() or {}
            if cls.is_voided(data):
                raise ValueError(f"No se puede aprobar el pago: la factura {a['invoiceId']} está anulada.")
            amount = round(float(a.get("amount", 0) or 0), 2)
            current_rem = float(data.get("cxpRemainingBalance", data.get("total", 0)))
            if amount > current_rem:
                raise ValueError(f"La asignación de RD$ {amount:,.2f} excede el saldo pendiente (RD$ {current_rem:,.2f}) de la factura {a['invoiceId']}.")
            new_rem = round(current_rem - amount, 2)
            new_status = "Pagado" if new_rem <= 0.01 else "Abonado"
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            due_date = data.get("dueDate", "")
            if new_status in ("Abonado", "Pendiente") and due_date and due_date < today_str:
                new_status = "Vencido"

            # Aplicar retención proporcional a la asignación
            ret_isr_applied = 0.0
            ret_itbis_applied = 0.0
            inv_total = float(data.get("total", 0) or 0)
            if inv_total > 0:
                ret_isr_calc, ret_itbis_calc = cls._retention_calculated(data)
                factor = amount / inv_total
                ret_isr_applied = round(ret_isr_calc * factor, 2)
                ret_itbis_applied = round(ret_itbis_calc * factor, 2)

            invoice_update = {
                "cxpRemainingBalance": new_rem,
                "cxpStatus": new_status,
                "updatedAt": serialize_field(datetime.now(timezone.utc)),
            }
            if ret_isr_applied or ret_itbis_applied:
                invoice_update["retentionIsrApplied"] = round(
                    float(data.get("retentionIsrApplied", 0) or 0) + ret_isr_applied, 2
                )
                invoice_update["retentionItbisApplied"] = round(
                    float(data.get("retentionItbisApplied", 0) or 0) + ret_itbis_applied, 2
                )
                invoice_update["retentionStatus"] = "applied" if new_rem <= 0.01 else "partial"

            transaction.update(inv_ref, invoice_update)
            alloc_id = f"{group_id}::{a['invoiceId']}"
            transaction.update(inv_ref.collection("cxp_payments").document(alloc_id), {
                "approvalStatus": "approved",
                "approvedBy": approved_by,
                "approvedByUid": approved_by_uid or "",
                "approvedAt": datetime.now(timezone.utc).isoformat(),
                "retentionIsrApplied": ret_isr_applied,
                "retentionItbisApplied": ret_itbis_applied,
            })

        transaction.update(group_ref, {
            "approvalStatus": "approved",
            "approvedBy": approved_by,
            "approvedByUid": approved_by_uid or "",
            "approvedAt": datetime.now(timezone.utc).isoformat(),
            "approvalNotes": notes or "",
        })
        return "approved"

    @classmethod
    def approve_multi_invoice_payment(cls, owner_uid=None, group_id=None, approved_by="",
                                      approved_by_uid="", notes="", company_id=None, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            group_ref = cls._group_coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(group_id)
            group_snap = group_ref.get()
            if not group_snap.exists:
                return False, "Pago multi-factura no encontrado."
            group = group_snap.to_dict() or {}
            total = round(float(group.get("total", 0) or 0), 2)
            payment_date_str = str(group.get("paymentDate", "") or "")[:10]
            cls.validate_period(company_id, payment_date_str)

            from app.services.db_service import run_firestore_transaction
            result = run_firestore_transaction(
                cls._approve_multi_invoice_tx, owner_uid, group_id,
                approved_by, approved_by_uid, notes, company_id, sandbox,
            )
            if result == "already_approved":
                return True, "El pago ya estaba aprobado."

            bank_account_id = group.get("bankAccountId", "")
            if bank_account_id:
                try:
                    from app.services.db_service import DatabaseService
                    bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox, company_id=company_id)
                    if bank_acc:
                        new_balance = bank_acc["currentBalance"] - total
                        DatabaseService.save_bank_account(owner_uid, bank_account_id, {**bank_acc, "currentBalance": new_balance}, sandbox=sandbox, company_id=company_id)
                except Exception as bank_err:
                    print(f"⚠️ Error al actualizar saldo bancario al aprobar pago multi-factura: {bank_err}")

            accounting_entry_id = ""
            accounting_error = ""
            try:
                from app.services.accounting_service import AccountingService, AccountingPostingError
                entry = AccountingService.auto_generate_cxp_payment_entry(
                    company_id=company_id,
                    payment_id=group_id,
                    amount=total,
                    payment_date=payment_date_str,
                    bank_account_id=bank_account_id,
                    payment_method=group.get("paymentMethod", ""),
                    concept=f"Pago multi-factura {group.get('supplierName', '')}",
                    supplier_id=group.get("supplierId", ""),
                    supplier_name=group.get("supplierName", ""),
                    sandbox=sandbox,
                )
                if entry:
                    accounting_entry_id = entry.get("id", "")
            except AccountingPostingError as acc_err:
                accounting_error = str(acc_err)
            except Exception as acc_err:
                accounting_error = str(acc_err)

            group_ref.update({
                "accountingStatus": "posted" if accounting_entry_id else ("error" if accounting_error else "pending"),
                "accountingEntryId": accounting_entry_id or "",
                "accountingError": accounting_error or "",
            })
            msg = f"Pago multi-factura de RD$ {total:,.2f} aprobado."
            if accounting_error:
                msg += " ⚠️ El pago no se pudo contabilizar; revise el módulo de contabilidad."
            return True, msg
        except ValueError as e:
            return False, str(e)
        except SupplierInvoiceGuardError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error al aprobar pago multi-factura {group_id}: {e}")
            return False, "No se pudo aprobar el pago multi-factura."

    @classmethod
    def reject_multi_invoice_payment(cls, owner_uid=None, group_id=None, rejected_by="",
                                     rejected_by_uid="", notes="", company_id=None, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            group_ref = cls._group_coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(group_id)
            group_doc = group_ref.get()
            if not group_doc.exists:
                return False, "Pago multi-factura no encontrado."
            group = group_doc.to_dict() or {}
            status = str(group.get("approvalStatus") or "").lower()
            if status == "rejected":
                return True, "El pago ya estaba rechazado."
            if status != "pending":
                return False, "Solo se puede rechazar un pago pendiente de aprobación."
            for a in group.get("allocations", []):
                alloc_id = f"{group_id}::{a['invoiceId']}"
                cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(a["invoiceId"]).collection("cxp_payments").document(alloc_id).update({"approvalStatus": "rejected"})
            group_ref.update({
                "approvalStatus": "rejected",
                "rejectedBy": rejected_by,
                "rejectedByUid": rejected_by_uid or "",
                "rejectedAt": datetime.now(timezone.utc).isoformat(),
                "rejectionNotes": notes or "",
            })
            return True, "Pago multi-factura rechazado."
        except Exception as e:
            print(f"⚠️ Error al rechazar pago multi-factura {group_id}: {e}")
            return False, "No se pudo rechazar el pago multi-factura."

    @classmethod
    def void_multi_invoice_payment(cls, owner_uid=None, group_id=None, voided_by="", reason="",
                                   company_id=None, sandbox=True):
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            group_ref = cls._group_coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(group_id)
            group_doc = group_ref.get()
            if not group_doc.exists:
                return False, "Pago multi-factura no encontrado."
            group = group_doc.to_dict() or {}
            status = str(group.get("approvalStatus") or "").lower()
            applied = status == "approved"
            allocations = group.get("allocations", [])

            if applied:
                try:
                    from app.services.accounting_service import AccountingService, AccountingPostingError
                    AccountingService.void_cxp_payment_entry(
                        company_id, group_id,
                        user_id=voided_by,
                        reason=reason or "Anulación de pago multi-factura",
                        sandbox=sandbox,
                    )
                except AccountingPostingError as acc_err:
                    return False, f"No se pudo revertir el asiento contable del pago: {acc_err}"
                except Exception as acc_err:
                    return False, f"No se pudo revertir el asiento contable del pago: {acc_err}"

                # Restaurar saldo bancario una sola vez (crédito por el total)
                bank_account_id = group.get("bankAccountId", "")
                if bank_account_id:
                    try:
                        from app.services.db_service import DatabaseService
                        total = round(float(group.get("total", 0) or 0), 2)
                        bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox, company_id=company_id)
                        if bank_acc:
                            new_balance = bank_acc["currentBalance"] + total
                            DatabaseService.save_bank_account(owner_uid, bank_account_id, {**bank_acc, "currentBalance": new_balance}, sandbox=sandbox, company_id=company_id)
                    except Exception as bank_err:
                        print(f"⚠️ Error al restaurar saldo bancario al anular pago multi-factura: {bank_err}")

                for a in allocations:
                    inv_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(a["invoiceId"])
                    inv_doc = inv_ref.get()
                    if not inv_doc.exists:
                        continue
                    data = inv_doc.to_dict() or {}
                    amount = round(float(a.get("amount", 0) or 0), 2)
                    current_rem = float(data.get("cxpRemainingBalance", data.get("total", 0)))
                    total_inv = float(data.get("total", 0))
                    new_rem = round(current_rem + amount, 2)
                    new_status = "Pendiente" if new_rem >= total_inv - 0.01 else "Abonado"
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    due_date = data.get("dueDate", "")
                    if new_status in ("Pendiente", "Abonado") and due_date and due_date < today_str:
                        new_status = "Vencido"

                    # Revertir retención aplicada por esta asignación
                    alloc_id = f"{group_id}::{a['invoiceId']}"
                    alloc_ref = inv_ref.collection("cxp_payments").document(alloc_id)
                    alloc_data = {}
                    try:
                        alloc_doc = alloc_ref.get()
                        if alloc_doc.exists:
                            alloc_data = alloc_doc.to_dict() or {}
                    except Exception:
                        pass
                    ret_isr_applied = float(alloc_data.get("retentionIsrApplied", 0) or 0)
                    ret_itbis_applied = float(alloc_data.get("retentionItbisApplied", 0) or 0)

                    invoice_update = {
                        "cxpRemainingBalance": new_rem,
                        "cxpStatus": new_status,
                        "updatedAt": serialize_field(datetime.now(timezone.utc)),
                    }
                    if ret_isr_applied or ret_itbis_applied:
                        invoice_update["retentionIsrApplied"] = round(
                            float(data.get("retentionIsrApplied", 0) or 0) - ret_isr_applied, 2
                        )
                        invoice_update["retentionItbisApplied"] = round(
                            float(data.get("retentionItbisApplied", 0) or 0) - ret_itbis_applied, 2
                        )
                        invoice_update["retentionStatus"] = "calculated" if new_rem >= total_inv - 0.01 else "partial"
                    inv_ref.update(invoice_update)
                    alloc_ref.delete()
            else:
                for a in allocations:
                    inv_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(a["invoiceId"])
                    alloc_id = f"{group_id}::{a['invoiceId']}"
                    inv_ref.collection("cxp_payments").document(alloc_id).delete()

            group_ref.update({
                "approvalStatus": "voided",
                "voidedBy": voided_by,
                "voidedByUid": voided_by or "",
                "voidedAt": datetime.now(timezone.utc).isoformat(),
                "voidReason": reason or "",
            })
            return True, "Pago multi-factura anulado."
        except Exception as e:
            print(f"⚠️ Error al anular pago multi-factura {group_id}: {e}")
            return False, "No se pudo anular el pago multi-factura."

    @classmethod
    def ensure_cash_payment(cls, owner_uid=None, invoice_id=None, amount=0, registered_by="Usuario",
                            payment_method="", payment_reference="", bank_account_id="",
                            payment_date=None, sandbox=True, company_id=None):
        """Create the payment detail for a cash invoice exactly once."""
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            inv_doc = doc_ref.get()
            if not inv_doc.exists:
                return False, "Factura proveedor no encontrada."
            inv_data = inv_doc.to_dict() or {}
            if cls.is_voided(inv_data) or str(inv_data.get("voidStatus") or "").lower() in ("pending", "failed"):
                return False, "No se puede registrar un pago sobre una factura anulada o con anulación en proceso."
            existing = list(doc_ref.collection("cxp_payments").limit(1).stream())
            if existing:
                return True, "El pago ya estaba registrado."

            payment_id = f"cash-{invoice_id}"
            payment_doc = {
                "id": payment_id,
                "amount": round(float(amount), 2),
                "paymentDate": payment_date or datetime.now(timezone.utc).isoformat(),
                "registeredBy": registered_by,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "method": payment_method or "",
                "reference": payment_reference or "",
                "bankAccountId": bank_account_id or "",
                "source": "cash_invoice_creation",
            }
            doc_ref.collection("cxp_payments").document(payment_id).set(payment_doc)
            bank_acc = DatabaseService.get_bank_account(
                owner_uid, bank_account_id, sandbox=sandbox, company_id=company_id
            ) if bank_account_id else None
            if bank_acc:
                DatabaseService.save_bank_account(owner_uid, bank_account_id, {
                    **bank_acc,
                    "currentBalance": bank_acc["currentBalance"] - round(float(amount), 2),
                }, sandbox=sandbox, company_id=company_id)
            return True, "Detalle de pago contado creado."
        except Exception as e:
            print(f"⚠️ Error al crear pago contado de factura proveedor {invoice_id}: {e}")
            return False, str(e)

    @classmethod
    def get_payments(cls, owner_uid=None, invoice_id=None, sandbox=True, company_id=None):
        payments = []
        if not firebase_initialized or db_firestore is None:
            return payments
        try:
            docs = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id).collection("cxp_payments").get()
            for doc in docs:
                data = doc.to_dict()
                payments.append({
                    "id": doc.id,
                    "amount": float(data.get("amount", 0)),
                    "paymentDate": data.get("paymentDate", ""),
                    "registeredBy": data.get("registeredBy", ""),
                    "method": data.get("method", ""),
                    "reference": data.get("reference", ""),
                    "bankAccountId": data.get("bankAccountId", ""),
                    "createdAt": data.get("createdAt", ""),
                    "approvalStatus": data.get("approvalStatus", ""),
                    "requestedBy": data.get("requestedBy", ""),
                    "requestedByName": data.get("requestedByName", ""),
                    "approvedBy": data.get("approvedBy", ""),
                    "approvedAt": data.get("approvedAt", ""),
                    "accountingStatus": data.get("accountingStatus", ""),
                })
            payments.sort(key=lambda p: p.get("createdAt", ""), reverse=True)
        except Exception as e:
            print(f"⚠️ Error al obtener pagos de factura proveedor: {e}")
        return payments

    @classmethod
    def void_payment(cls, owner_uid=None, invoice_id=None, payment_id=None, sandbox=True, company_id=None):
        """Revierte (o cancela) un pago y recalcula el estado de la factura."""
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            inv_doc = doc_ref.get()
            if not inv_doc.exists:
                return False, "Factura proveedor no encontrada."
            inv_data = inv_doc.to_dict()
            pay_ref = doc_ref.collection("cxp_payments").document(payment_id)
            pay_doc = pay_ref.get()
            if not pay_doc.exists:
                return False, "Pago no encontrado."
            pay_data = pay_doc.to_dict()
            amount = float(pay_data.get("amount", 0))
            # Pagos legacy (sin approvalStatus) se consideran aplicados.
            applied = str(pay_data.get("approvalStatus") or "approved").lower() == "approved"

            current_rem = float(inv_data.get("cxpRemainingBalance", inv_data.get("total", 0)))
            total = float(inv_data.get("total", 0))

            if not applied:
                pay_ref.delete()
                return True, f"Pago pendiente de RD$ {amount:,.2f} cancelado."

            # Reversar el asiento contable del pago (antes de borrar el pago)
            try:
                from app.services.accounting_service import AccountingService, AccountingPostingError
                AccountingService.void_cxp_payment_entry(
                    company_id, payment_id,
                    user_id="", reason="Reversión de pago a proveedor",
                    sandbox=sandbox,
                )
            except AccountingPostingError as acc_err:
                return False, f"No se pudo revertir el asiento contable del pago: {acc_err}"
            except Exception as acc_err:
                return False, f"No se pudo revertir el asiento contable del pago: {acc_err}"

            # Restaurar saldo bancario (crédito)
            bank_account_id = pay_data.get("bankAccountId", "")
            if bank_account_id:
                try:
                    from app.services.db_service import DatabaseService
                    bank_acc = DatabaseService.get_bank_account(owner_uid, bank_account_id, sandbox=sandbox, company_id=company_id)
                    if bank_acc:
                        new_balance = bank_acc["currentBalance"] + amount
                        DatabaseService.save_bank_account(owner_uid, bank_account_id, {**bank_acc, "currentBalance": new_balance}, sandbox=sandbox, company_id=company_id)
                except Exception as bank_err:
                    print(f"⚠️ Error al restaurar saldo bancario al revertir pago: {bank_err}")

            new_rem = round(current_rem + amount, 2)
            if new_rem >= total - 0.01:
                new_status = "Pendiente"
            else:
                new_status = "Abonado"
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            due_date = inv_data.get("dueDate", "")
            if new_status in ("Pendiente", "Abonado") and due_date and due_date < today_str:
                new_status = "Vencido"

            # Revertir la retención aplicada por este pago
            ret_isr_applied = float(pay_data.get("retentionIsrApplied", 0) or 0)
            ret_itbis_applied = float(pay_data.get("retentionItbisApplied", 0) or 0)
            invoice_update = {
                "cxpRemainingBalance": new_rem,
                "cxpStatus": new_status,
                "updatedAt": serialize_field(datetime.now(timezone.utc)),
            }
            if ret_isr_applied or ret_itbis_applied:
                invoice_update["retentionIsrApplied"] = round(
                    float(inv_data.get("retentionIsrApplied", 0) or 0) - ret_isr_applied, 2
                )
                invoice_update["retentionItbisApplied"] = round(
                    float(inv_data.get("retentionItbisApplied", 0) or 0) - ret_itbis_applied, 2
                )
                invoice_update["retentionStatus"] = "calculated" if new_rem >= total - 0.01 else "partial"
            doc_ref.update(invoice_update)
            pay_ref.delete()
            return True, f"Pago de RD$ {amount:,.2f} revertido. Nuevo saldo: RD$ {new_rem:,.2f}."
        except Exception as e:
            print(f"⚠️ Error al revertir pago {payment_id}: {e}")
            return False, str(e)

    @classmethod
    def delete(cls, owner_uid=None, invoice_id=None, sandbox=True, company_id=None):
        """Elimina físicamente una factura de proveedor solo si es seguro hacerlo.

        Devuelve (ok, mensaje). Se bloquea cuando la factura tiene pagos,
        asiento contable activo, ya fue emitida a la DGII o fue anulada (para
        conservar trazabilidad). En esos casos debe usarse la anulación.
        """
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Factura proveedor no encontrada."
            data = doc.to_dict() or {}

            if cls.is_voided(data):
                return False, "No se puede eliminar una factura anulada; conserve la trazabilidad."
            if str(data.get("voidStatus") or "").lower() in ("pending", "failed"):
                return False, "La factura tiene una anulación en proceso; no se puede eliminar."
            if cls.is_emitted(data):
                return False, "No se puede eliminar una factura emitida a la DGII. Use la anulación o el flujo fiscal."
            if cls.has_payments(owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id):
                return False, "No se puede eliminar una factura con pagos registrados. Revierta los pagos o use la anulación."
            if cls.has_accounting_entry(owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id):
                return False, "No se puede eliminar una factura contabilizada. Use la anulación."

            effective_date = cls.effective_accounting_date(data)
            cls.validate_period(company_id, effective_date)

            attachment_urls = data.get("attachmentUrls", [])
            for url in attachment_urls:
                if url and not url.startswith("/static/"):
                    try:
                        from urllib.parse import urlparse
                        path = urlparse(url).path
                        if path.startswith("/"):
                            path = path[1:]
                        blob = firebase_storage_bucket.blob(path)
                        blob.delete()
                        from app.services.db_service import _invalidate_storage_cache
                        parts = path.split("/")
                        if len(parts) > 2:
                            if parts[0] == "users":
                                _invalidate_storage_cache(parts[1])
                            elif parts[0] == "companies":
                                _invalidate_storage_cache(parts[1])
                    except Exception as e:
                        print(f"⚠️ Error al eliminar archivo de storage: {e}")
            payments = doc_ref.collection("cxp_payments").get()
            for pay in payments:
                pay.reference.delete()
            doc_ref.delete()
            return True, "Factura de proveedor eliminada."
        except SupplierInvoiceGuardError as e:
            return False, str(e)
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error al eliminar factura proveedor {invoice_id}: {e}")
            return False, "No se pudo eliminar la factura. Intente nuevamente o contacte soporte."

    @classmethod
    def void(cls, owner_uid=None, invoice_id=None, reason="", voided_by="", sandbox=True, company_id=None):
        """Anula una factura de proveedor preservando trazabilidad.

        - Las facturas recibidas (NCF del proveedor) se anulan localmente.
        - Los e-CF emitidos por VykOne aceptados/ en contingencia/pendientes
          NO se anulan localmente: se bloquean hasta resolver el flujo fiscal.
        - Un e-CF rechazado por DGII sí puede anularse localmente.
        - No borra el documento; marca ``status=anulada``, saca el saldo de CxP
          y anula los asientos contables activos confirmando su persistencia.
        - Usa un estado intermedio (``voidStatus=pending``) para poder reanudar
          si falla una escritura después de reversar el asiento.
        """
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        reason = (reason or "").strip()
        if not reason:
            return False, "Debe indicar el motivo de la anulación."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Factura proveedor no encontrada."
            data = doc.to_dict() or {}
            if cls.is_voided(data):
                return False, "La factura ya está anulada."

            fiscal_block = cls.fiscal_void_block_reason(data)
            if fiscal_block:
                return False, fiscal_block

            if cls.has_payments(owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id):
                return False, "No se puede anular una factura con pagos registrados. Revierta los pagos primero."

            try:
                active_entries = cls._active_accounting_entries(
                    owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id
                )
            except SupplierInvoiceGuardError as guard_err:
                return False, str(guard_err)

            period_dates = {
                str(e.get("date"))[:10] for e in active_entries if e.get("date")
            }
            if not period_dates:
                effective_date = cls.effective_accounting_date(data)
                if effective_date:
                    period_dates.add(effective_date)
            for period_date in sorted(period_dates):
                cls.validate_period(company_id, period_date)

            void_status = str(data.get("voidStatus") or "").lower()
            if void_status != "pending":
                try:
                    doc_ref.update({
                        "voidStatus": "pending",
                        "voidReason": reason,
                        "voidRequestedAt": datetime.now(timezone.utc).isoformat(),
                        "voidRequestedBy": voided_by or "",
                        "voidCompanyId": company_id or "",
                        "voidEntryIds": [e["id"] for e in active_entries],
                        "updatedAt": serialize_field(datetime.now(timezone.utc)),
                    })
                except Exception as e:
                    print(f"⚠️ No se pudo preparar la anulación {invoice_id}: {e}")
                    return False, "No se pudo iniciar la anulación de forma segura. Intente nuevamente."

            from app.services.accounting_service import AccountingService
            try:
                for entry in active_entries:
                    if entry.get("status") == "voided":
                        continue
                    voided_entry = AccountingService.void_entry(
                        company_id, entry["id"],
                        reason=reason,
                        user_id=voided_by or "",
                        sandbox=sandbox,
                    )
                    if not voided_entry or voided_entry.get("status") != "voided":
                        raise SupplierInvoiceIntegrityError(
                            f"No se confirmó la reversión del asiento {entry['id']}."
                        )
            except Exception as e:
                print(f"⚠️ Error al reversar asiento de factura proveedor {invoice_id}: {e}")
                try:
                    doc_ref.update({
                        "voidStatus": "pending",
                        "voidError": str(e)[:300],
                        "updatedAt": serialize_field(datetime.now(timezone.utc)),
                    })
                except Exception:
                    pass
                return False, "No se pudo confirmar la reversión contable; la factura NO fue anulada. Reintente la anulación."

            try:
                doc_ref.update({
                    "status": "anulada",
                    "cxpStatus": "Anulada",
                    "cxpRemainingBalance": 0.0,
                    "voidStatus": "completed",
                    "voidedAt": datetime.now(timezone.utc).isoformat(),
                    "voidedBy": voided_by or "",
                    "voidReason": reason,
                    "voidEntryIds": [e["id"] for e in active_entries],
                    "voidError": "",
                    "updatedAt": serialize_field(datetime.now(timezone.utc)),
                })
            except Exception as e:
                print(f"⚠️ Asiento reversado pero no se pudo marcar anulada {invoice_id}: {e}")
                return False, ("La reversión contable fue confirmada, pero no se pudo marcar la factura como anulada. "
                               "Reintente la anulación; el estado quedó pendiente.")
            return True, "Factura de proveedor anulada correctamente."
        except ValueError as e:
            return False, str(e)
        except SupplierInvoiceGuardError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error al anular factura proveedor {invoice_id}: {e}")
            return False, "No se pudo anular la factura. Intente nuevamente o contacte soporte."

    @classmethod
    def prepare_correction(cls, owner_uid=None, invoice_id=None, reason="", corrected_by="",
                           sandbox=True, company_id=None):
        """Prepara una factura contabilizada para corrección con trazabilidad.

        Revierte (void) el asiento activo de forma verificada y deja la factura
        marcada con ``correctionStatus=in_progress``. El formulario de edición
        puede entonces corregir los datos y regenerar el asiento. No aplica a
        comprobantes emitidos/anulados ni a facturas con pagos.
        """
        reason = (reason or "").strip()
        if not reason:
            return False, "Debe indicar el motivo de la corrección."
        if not firebase_initialized or db_firestore is None:
            return False, "Firebase no inicializado."
        try:
            doc_ref = cls._coll_ref(owner_uid=owner_uid, sandbox=sandbox, company_id=company_id).document(invoice_id)
            doc = doc_ref.get()
            if not doc.exists:
                return False, "Factura proveedor no encontrada."
            data = doc.to_dict() or {}
            if cls.is_voided(data):
                return False, "No se puede corregir una factura anulada."
            if str(data.get("voidStatus") or "").lower() in ("pending", "failed"):
                return False, "La factura tiene una anulación en proceso; no se puede corregir."
            if cls.is_emitted(data):
                return False, "No se puede corregir una factura emitida a la DGII. Use el flujo fiscal."
            if cls.has_payments(owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id):
                return False, "No se puede corregir una factura con pagos registrados. Revierta los pagos primero."

            try:
                active_entries = cls._active_accounting_entries(
                    owner_uid=owner_uid, invoice_id=invoice_id, sandbox=sandbox, company_id=company_id
                )
            except SupplierInvoiceGuardError as guard_err:
                return False, str(guard_err)

            for entry in active_entries:
                if entry.get("date"):
                    cls.validate_period(company_id, entry.get("date"))

            from app.services.accounting_service import AccountingService
            for entry in active_entries:
                voided_entry = AccountingService.void_entry(
                    company_id, entry["id"],
                    reason=f"Corrección de factura: {reason}",
                    user_id=corrected_by or "",
                    sandbox=sandbox,
                )
                if not voided_entry or voided_entry.get("status") != "voided":
                    raise SupplierInvoiceIntegrityError(
                        f"No se confirmó la reversión del asiento {entry['id']}."
                    )

            doc_ref.update({
                "correctionStatus": "in_progress",
                "correctionReason": reason,
                "correctionRequestedAt": datetime.now(timezone.utc).isoformat(),
                "correctionRequestedBy": corrected_by or "",
                "accountingStatus": "pending_correction",
                "accountingError": "",
                "updatedAt": serialize_field(datetime.now(timezone.utc)),
            })
            return True, "Asiento reversado. La factura puede corregirse y se regenerará su contabilización."
        except ValueError as e:
            return False, str(e)
        except SupplierInvoiceGuardError as e:
            return False, str(e)
        except Exception as e:
            print(f"⚠️ Error al preparar corrección de factura {invoice_id}: {e}")
            return False, "No se pudo preparar la corrección de la factura. Intente nuevamente."
