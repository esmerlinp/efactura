from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


APPROVAL_DOCUMENT_TYPES = {
    "expense": "Gasto / Egreso",
    "purchase_order": "Orden de Compra",
    "supplier_invoice": "Factura de Proveedor",
}


class ApprovalService:
    @staticmethod
    def _get_db():
        try:
            from app.services.db_service import db_firestore, firebase_initialized
            if firebase_initialized:
                return db_firestore
        except Exception:
            pass
        return None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _path(owner_uid: str = None, rule_id: str = None, company_id: str = None) -> str:
        if company_id:
            base = f"companies/{company_id}/approval_rules"
        else:
            base = f"users/{owner_uid}/approval_rules"
        return f"{base}/{rule_id}" if rule_id else base

    @staticmethod
    def _requests_path(owner_uid: str = None, request_id: str = None, company_id: str = None) -> str:
        if company_id:
            base = f"companies/{company_id}/approval_requests"
        else:
            base = f"users/{owner_uid}/approval_requests"
        return f"{base}/{request_id}" if request_id else base

    @staticmethod
    def _parse_amount(value) -> float:
        try:
            return float(str(value or 0).replace(",", ""))
        except Exception:
            return 0.0

    @staticmethod
    def _normalise_approvers(approvers) -> list:
        normalised = []
        for item in approvers or []:
            if isinstance(item, dict):
                uid = item.get("id") or item.get("uid") or item.get("approver_id")
                name = item.get("name") or item.get("approver_name") or item.get("email") or uid
                email = item.get("email") or item.get("approver_email") or ""
            else:
                parts = str(item).split("|")
                uid = parts[0].strip() if parts else ""
                name = parts[1].strip() if len(parts) > 1 else uid
                email = parts[2].strip() if len(parts) > 2 else ""
            if uid:
                normalised.append({"id": uid, "name": name, "email": email})
        return normalised

    @classmethod
    def get_rules(cls, owner_uid: str = None, company_id: str = None) -> list:
        db = cls._get_db()
        if not db:
            return []
        try:
            docs = db.collection(cls._path(owner_uid=owner_uid, company_id=company_id)).stream()
            rules = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = data.get("id") or doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                rules.append(data)
            rules.sort(key=lambda r: (r.get("document_type", ""), float(r.get("min_amount", 0))), reverse=True)
            return rules
        except Exception:
            return []

    @classmethod
    def get_rule(cls, owner_uid: str = None, rule_id: str = None, company_id: str = None) -> Optional[dict]:
        db = cls._get_db()
        if not db:
            return None
        try:
            doc = db.document(cls._path(owner_uid=owner_uid, rule_id=rule_id, company_id=company_id)).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = data.get("id") or doc.id
                data["branchId"] = data.get("branchId", "default-sucursal-principal")
                data["projectId"] = data.get("projectId")
                return data
        except Exception:
            pass
        return None

    @classmethod
    def save_rule(cls, owner_uid: str = None, rule_data: dict = None, company_id: str = None) -> dict:
        db = cls._get_db()
        rule_id = rule_data.get("id") or str(uuid4())
        now = cls._now()
        rule = {
            "id": rule_id,
            "document_type": rule_data.get("document_type", "expense"),
            "min_amount": cls._parse_amount(rule_data.get("min_amount", 0)),
            "approvers": cls._normalise_approvers(rule_data.get("approvers", [])),
            "require_all": bool(rule_data.get("require_all", True)),
            "is_active": bool(rule_data.get("is_active", True)),
            "notes": rule_data.get("notes", ""),
            "branchId": rule_data.get("branchId", "default-sucursal-principal"),
            "projectId": rule_data.get("projectId"),
            "createdAt": rule_data.get("createdAt") or now,
            "updatedAt": now,
        }
        if db:
            db.document(cls._path(owner_uid=owner_uid, rule_id=rule_id, company_id=company_id)).set(rule)
        return rule

    @classmethod
    def delete_rule(cls, owner_uid: str = None, rule_id: str = None, company_id: str = None):
        db = cls._get_db()
        if db:
            db.document(cls._path(owner_uid=owner_uid, rule_id=rule_id, company_id=company_id)).delete()

    @classmethod
    def check_needs_approval(cls, owner_uid: str = None, doc_type: str = "", amount: float = 0, company_id: str = None) -> tuple:
        applicable = [
            r for r in cls.get_rules(owner_uid=owner_uid, company_id=company_id)
            if r.get("document_type") == doc_type and r.get("is_active", True) and r.get("approvers")
        ]
        applicable.sort(key=lambda r: float(r.get("min_amount", 0)), reverse=True)
        for rule in applicable:
            if cls._parse_amount(amount) >= float(rule.get("min_amount", 0)):
                return True, rule
        return False, None

    @classmethod
    def get_requests(cls, owner_uid: str = None, status: str = "", approver_id: str = "", company_id: str = None) -> list:
        db = cls._get_db()
        if not db:
            return []
        try:
            query = db.collection(cls._requests_path(owner_uid=owner_uid, company_id=company_id))
            if status:
                query = query.where("status", "==", status)
            docs = query.stream()
            requests = []
            for doc in docs:
                data = doc.to_dict()
                data["id"] = data.get("id") or doc.id
                if approver_id:
                    steps = data.get("steps", [])
                    if not any(s.get("approver_id") == approver_id for s in steps):
                        continue
                data["document_label"] = APPROVAL_DOCUMENT_TYPES.get(data.get("document_type"), data.get("document_type", "Documento"))
                requests.append(data)
            requests.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
            return requests
        except Exception:
            return []

    @classmethod
    def get_request(cls, owner_uid: str = None, request_id: str = None, company_id: str = None) -> Optional[dict]:
        db = cls._get_db()
        if not db:
            return None
        try:
            doc = db.document(cls._requests_path(owner_uid=owner_uid, request_id=request_id, company_id=company_id)).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = data.get("id") or doc.id
                return data
        except Exception:
            pass
        return None

    @classmethod
    def _find_open_request(cls, owner_uid: str = None, doc_type: str = "", doc_id: str = "", sandbox: bool = True, company_id: str = None) -> Optional[dict]:
        for req in cls.get_requests(owner_uid=owner_uid, status="pending", company_id=company_id):
            if (
                req.get("document_type") == doc_type
                and req.get("document_id") == doc_id
                and bool(req.get("sandbox", True)) == bool(sandbox)
            ):
                return req
        return None

    @classmethod
    def create_approval_request(
        cls,
        owner_uid: str = None,
        doc_type: str = "",
        doc_id: str = "",
        doc_number: str = "",
        amount: float = 0,
        requestor: str = "",
        sandbox: bool = True,
        document_url: str = "",
        metadata: Optional[dict] = None,
        company_id: str = None,
    ):
        db = cls._get_db()
        needs_approval, rule = cls.check_needs_approval(owner_uid=owner_uid, doc_type=doc_type, amount=amount, company_id=company_id)
        if not needs_approval:
            return None

        existing = cls._find_open_request(owner_uid=owner_uid, doc_type=doc_type, doc_id=doc_id, sandbox=sandbox, company_id=company_id)
        if existing:
            return existing.get("id")

        request_id = str(uuid4())
        approvers = rule.get("approvers", [])
        steps = [
            {
                "approver_id": a.get("id"),
                "approver_name": a.get("name"),
                "approver_email": a.get("email"),
                "status": "pending",
                "decided_at": None,
                "comment": "",
            }
            for a in approvers
        ]

        request = {
            "id": request_id,
            "document_type": doc_type,
            "document_id": doc_id,
            "document_number": doc_number,
            "document_label": APPROVAL_DOCUMENT_TYPES.get(doc_type, doc_type),
            "document_url": document_url,
            "amount": cls._parse_amount(amount),
            "requestor": requestor,
            "rule_id": rule.get("id"),
            "require_all": rule.get("require_all", True),
            "steps": steps,
            "status": "pending",
            "sandbox": bool(sandbox),
            "metadata": metadata or {},
            "createdAt": cls._now(),
            "updatedAt": cls._now(),
        }
        if db:
            db.document(cls._requests_path(owner_uid=owner_uid, request_id=request_id, company_id=company_id)).set(request)
        return request_id

    @classmethod
    def prepare_document_approval(
        cls,
        owner_uid: str = None,
        doc_type: str = "",
        doc_id: str = "",
        document: dict = None,
        amount_field: str = "amount",
        number_field: str = "number",
        sandbox: bool = True,
        company_id: str = None,
    ) -> dict:
        amount = cls._parse_amount(document.get(amount_field) or document.get("total") or document.get("amount"))
        needs, _rule = cls.check_needs_approval(owner_uid=owner_uid, doc_type=doc_type, amount=amount, company_id=company_id)
        if not needs:
            return document

        doc_number = (
            document.get(number_field)
            or document.get("poNumber")
            or document.get("ncf")
            or document.get("ecfNumber")
            or document.get("concept")
            or doc_id
        )
        requestor = (
            document.get("requestedBy")
            or document.get("createdBy")
            or document.get("registeredBy")
            or "Sistema"
        )
        req_id = cls.create_approval_request(
            owner_uid=owner_uid,
            company_id=company_id,
            doc_type=doc_type,
            doc_id=doc_id,
            doc_number=doc_number,
            amount=amount,
            requestor=requestor,
            sandbox=sandbox,
            metadata={
                "concept": document.get("concept", ""),
                "supplierName": document.get("supplierName") or document.get("providerName", ""),
                "date": document.get("date") or document.get("orderDate", ""),
            },
        )
        if req_id:
            document["approvalRequestId"] = req_id
            if doc_type == "expense":
                document["approvalStatus"] = "Pendiente"
            elif doc_type == "purchase_order" and document.get("status") in ("borrador", "", None):
                document["status"] = "pendiente_aprobacion"
        return document

    @classmethod
    def get_pending_approvals(cls, owner_uid: str = None, approver_id: str = "", company_id: str = None) -> list:
        pending = []
        for data in cls.get_requests(owner_uid=owner_uid, status="pending", company_id=company_id):
            for step in data.get("steps", []):
                if step.get("approver_id") == approver_id and step.get("status") == "pending":
                    pending.append(data)
                    break
        return pending

    @classmethod
    def decide_approval(
        cls,
        owner_uid: str = None,
        request_id: str = "",
        approver_id: str = "",
        approved: bool = False,
        comment: str = "",
        approver_name: str = "",
        company_id: str = None,
    ) -> dict:
        db = cls._get_db()
        data = cls.get_request(owner_uid=owner_uid, request_id=request_id, company_id=company_id)
        if not data:
            return {"success": False, "error": "Solicitud no encontrada"}

        any_changed = False
        for step in data.get("steps", []):
            if step.get("approver_id") == approver_id and step.get("status") == "pending":
                step["status"] = "approved" if approved else "rejected"
                step["decided_at"] = cls._now()
                step["comment"] = comment
                if approver_name and not step.get("approver_name"):
                    step["approver_name"] = approver_name
                any_changed = True

        if not any_changed:
            return {"success": False, "error": "No tienes una decisión pendiente en esta solicitud"}

        require_all = bool(data.get("require_all", True))
        steps = data.get("steps", [])
        any_rejected = any(s.get("status") == "rejected" for s in steps)
        all_approved = all(s.get("status") == "approved" for s in steps)
        any_approved = any(s.get("status") == "approved" for s in steps)

        if any_rejected:
            data["status"] = "rejected"
        elif (require_all and all_approved) or (not require_all and any_approved):
            data["status"] = "approved"

        data["updatedAt"] = cls._now()
        if db:
            db.document(cls._requests_path(owner_uid=owner_uid, request_id=request_id, company_id=company_id)).set(data)

        if data["status"] in ("approved", "rejected"):
            cls.apply_decision_to_document(owner_uid=owner_uid, request_data=data, decided_by=approver_name or approver_id, company_id=company_id)

        return {"success": True, "status": data["status"]}

    @classmethod
    def apply_decision_to_document(cls, owner_uid: str = None, request_data: dict = None, decided_by: str = "", company_id: str = None):
        doc_type = request_data.get("document_type")
        doc_id = request_data.get("document_id")
        sandbox = bool(request_data.get("sandbox", True))
        approved = request_data.get("status") == "approved"
        rejected = request_data.get("status") == "rejected"
        if not doc_id or not (approved or rejected):
            return

        try:
            if doc_type == "expense":
                from app.services.db_service import DatabaseService
                expense = DatabaseService.get_expense(owner_uid, doc_id, sandbox=sandbox, company_id=company_id)
                if expense:
                    expense["approvalStatus"] = "Aprobado" if approved else "Rechazado"
                    expense["approvedBy"] = decided_by if approved else ""
                    expense["rejectedBy"] = decided_by if rejected else ""
                    expense["approvalRequestId"] = request_data.get("id", "")
                    DatabaseService.save_expense(owner_uid, doc_id, expense, sandbox=sandbox, company_id=company_id)
            elif doc_type == "purchase_order":
                from app.services.purchase_order_service import PurchaseOrderService
                PurchaseOrderService.update_status(
                    owner_uid=owner_uid,
                    po_id=doc_id,
                    new_status="aprobada" if approved else "rechazada",
                    sandbox=sandbox,
                    user=decided_by,
                    company_id=company_id,
                )
        except Exception:
            pass
