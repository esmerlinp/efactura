"""DataPrivacy — Exportación DSAR, anonimización y retención de datos según Ley 172-13."""

import json
import csv
import io
from datetime import datetime, timezone
from typing import Dict, List, Optional

PII_FIELDS = {"email", "telefono", "phone", "direccion", "address", "cedula", "idNumber",
              "rnc", "contactName", "contactEmail", "contactPhone", "firstName", "lastName",
              "fullName", "razonSocial", "clientName", "providerName", "employeeName",
              "emergencyContact", "emergencyPhone", "beneficiaryName", "beneficiaryAccount"}


class DataPrivacyService:

    @classmethod
    def export_subject_data(cls, owner_uid: str, entity_type: str, entity_id: str,
                            sandbox: bool = True) -> Optional[Dict]:
        from app.services.db_service import DatabaseService
        data = {"entityType": entity_type, "entityId": entity_id, "exportedAt": datetime.now(timezone.utc).isoformat()}
        if entity_type == "employee":
            emp = DatabaseService.get_employee(owner_uid, entity_id, sandbox=sandbox) if hasattr(DatabaseService, 'get_employee') else None
            data["employee"] = cls._redact_sensitive(emp) if emp else None
            data["payments"] = cls._get_employee_payments(owner_uid, entity_id, sandbox)
        elif entity_type == "client":
            client = DatabaseService.get_client(owner_uid, entity_id, sandbox=sandbox)
            data["client"] = cls._redact_sensitive(client) if client else None
            data["invoices"] = cls._get_client_invoices(owner_uid, entity_id, sandbox)
        elif entity_type == "supplier":
            data["supplier"] = {"note": "Exportación de proveedor no implementada completamente"}
        return data

    @classmethod
    def anonymize_entity(cls, owner_uid: str, entity_type: str, entity_id: str,
                         sandbox: bool = True) -> Dict:
        from app.services.db_service import DatabaseService
        result = {"success": False, "entityType": entity_type, "entityId": entity_id}
        anon_placeholder = "[ANONIMIZADO]"
        if entity_type == "client":
            client = DatabaseService.get_client(owner_uid, entity_id, sandbox=sandbox)
            if not client:
                result["error"] = "Cliente no encontrado"
                return result
            client["razonSocial"] = f"{anon_placeholder} {entity_id[:8]}"
            client["email"] = f"anon_{entity_id[:8]}@deleted.local"
            client["telefono"] = ""
            client["direccion"] = ""
            client["rnc"] = ""
            client["isAnonymized"] = True
            client["anonymizedAt"] = datetime.now(timezone.utc).isoformat()
            DatabaseService.save_client(owner_uid, entity_id, client, sandbox=sandbox)
            result["success"] = True
        elif entity_type == "employee":
            if hasattr(DatabaseService, 'get_employee'):
                emp = DatabaseService.get_employee(owner_uid, entity_id, sandbox=sandbox)
                if not emp:
                    result["error"] = "Empleado no encontrado"
                    return result
                emp["fullName"] = f"{anon_placeholder} {entity_id[:8]}"
                emp["firstName"] = anon_placeholder
                emp["lastName"] = anon_placeholder
                emp["email"] = f"anon_{entity_id[:8]}@deleted.local"
                emp["phone"] = ""
                emp["address"] = ""
                emp["cedula"] = ""
                emp["idNumber"] = ""
                emp["emergencyContact"] = ""
                emp["emergencyPhone"] = ""
                emp["isAnonymized"] = True
                emp["anonymizedAt"] = datetime.now(timezone.utc).isoformat()
                DatabaseService.save_employee(owner_uid, entity_id, emp, sandbox=sandbox)
                result["success"] = True
        return result

    @classmethod
    def _redact_sensitive(cls, data: Optional[Dict]) -> Optional[Dict]:
        if not data:
            return data
        redacted = dict(data)
        for field in PII_FIELDS:
            if field in redacted and field not in ("id", "branchId", "projectId", "ownerUID"):
                val = redacted[field]
                if isinstance(val, str) and len(val) > 4:
                    redacted[field] = "[REDACTADO]"
        return redacted

    @classmethod
    def _get_employee_payments(cls, owner_uid: str, employee_id: str, sandbox: bool) -> List[Dict]:
        try:
            from app.services import hr_data_service as hr
            periods = hr.get_payroll_periods(owner_uid, sandbox=sandbox)
            payments = []
            for p in sorted(periods, key=lambda x: x.get("periodKey", ""), reverse=True)[:24]:
                for l in p.get("lines", []):
                    if l.get("employeeId") == employee_id:
                        payments.append({"period": p.get("periodKey", ""), "netSalary": l.get("netSalary", 0)})
                        break
            return payments
        except Exception:
            return []

    @classmethod
    def _get_client_invoices(cls, owner_uid: str, client_id: str, sandbox: bool) -> List[Dict]:
        try:
            from app.services.db_service import DatabaseService
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, include_all=True)
            return [
                {"invoiceNumber": inv.get("invoiceNumber", ""), "date": inv.get("date", ""),
                 "total": inv.get("total", 0), "status": inv.get("status", "")}
                for inv in invoices if inv.get("clientId") == client_id
            ][:100]
        except Exception:
            return []
