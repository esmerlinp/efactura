"""IntegrityScanner — Detector de datos huérfanos y referencias rotas en Firestore.

Recorre las colecciones principales y detecta:
- Facturas con clientId que no existe en clients
- Pagos con invoiceId que no existe en invoices  
- Asientos contables con referenceId que apunta a documento eliminado
- Empleados sin branchId válido
- Items con categoryId inexistente

Modo dry-run: solo reporta, no modifica.
"""

from datetime import datetime, timezone
from typing import Dict, List

SEVERITY_CRITICAL = "critica"
SEVERITY_HIGH = "alta"
SEVERITY_MEDIUM = "media"
SEVERITY_LOW = "baja"


class IntegrityScanner:
    """Escáner de integridad referencial para Firestore."""

    @classmethod
    def scan_all(cls, owner_uid: str, sandbox: bool = True, company_id=None) -> Dict:
        """Ejecuta todas las reglas de integridad y retorna hallazgos.

        Returns:
            Dict con {findings: [...], summary: {total, critical, high, medium, low}}
        """
        findings = []
        findings.extend(cls._scan_invoice_client_integrity(owner_uid, sandbox, company_id=company_id))
        findings.extend(cls._scan_payment_invoice_integrity(owner_uid, sandbox, company_id=company_id))
        findings.extend(cls._scan_entry_reference_integrity(owner_uid, sandbox, company_id=company_id))
        findings.extend(cls._scan_employee_branch_integrity(owner_uid, sandbox, company_id=company_id))
        findings.extend(cls._scan_item_category_integrity(owner_uid, sandbox, company_id=company_id))

        summary = {
            "total": len(findings),
            "critica": sum(1 for f in findings if f["severity"] == SEVERITY_CRITICAL),
            "alta": sum(1 for f in findings if f["severity"] == SEVERITY_HIGH),
            "media": sum(1 for f in findings if f["severity"] == SEVERITY_MEDIUM),
            "baja": sum(1 for f in findings if f["severity"] == SEVERITY_LOW),
            "scannedAt": datetime.now(timezone.utc).isoformat(),
        }

        return {"findings": findings, "summary": summary}

    @classmethod
    def _scan_invoice_client_integrity(cls, owner_uid: str, sandbox: bool, company_id=None) -> List[Dict]:
        """Detecta facturas cuyo clientId no existe en la colección de clientes."""
        findings = []
        try:
            from app.services.db_service import DatabaseService
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, include_all=True, company_id=company_id)
            clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, company_id=company_id)
            client_ids = {c.get("id", "") for c in clients if c.get("id")}
            for inv in invoices[:1000]:
                client_id = inv.get("clientId", "")
                if client_id and client_id not in client_ids:
                    findings.append({
                        "type": "factura_sin_cliente",
                        "severity": SEVERITY_CRITICAL,
                        "entityId": inv.get("id", ""),
                        "entityLabel": f"Factura {inv.get('invoiceNumber', '')}",
                        "detail": f"Cliente {client_id} no encontrado en la base de clientes.",
                        "referenceType": "invoice",
                        "referenceId": inv.get("id", ""),
                        "missingReference": client_id,
                    })
        except Exception as e:
            findings.append({
                "type": "error_escaneo",
                "severity": SEVERITY_HIGH,
                "entityId": "invoice_client_scanner",
                "entityLabel": "Error en escáner de facturas-clientes",
                "detail": str(e),
            })
        return findings

    @classmethod
    def _scan_payment_invoice_integrity(cls, owner_uid: str, sandbox: bool, company_id=None) -> List[Dict]:
        """Detecta pagos cuyo invoiceId no existe."""
        findings = []
        try:
            from app.services.db_service import DatabaseService
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, include_all=True, company_id=company_id)
            invoice_ids = {inv.get("id", "") for inv in invoices if inv.get("id")}
            for inv in invoices[:500]:
                for payment in inv.get("payments", []):
                    if payment.get("invoiceId") and payment["invoiceId"] not in invoice_ids:
                        findings.append({
                            "type": "pago_sin_factura",
                            "severity": SEVERITY_HIGH,
                            "entityId": inv.get("id", ""),
                            "entityLabel": f"Pago en factura {inv.get('invoiceNumber', '')}",
                            "detail": f"Pago referencia a factura {payment.get('invoiceId')} inexistente.",
                            "referenceType": "payment",
                            "referenceId": payment.get("id", ""),
                            "missingReference": payment.get("invoiceId"),
                        })
        except Exception as e:
            findings.append({
                "type": "error_escaneo",
                "severity": SEVERITY_HIGH,
                "entityId": "payment_scanner",
                "entityLabel": "Error en escáner de pagos",
                "detail": str(e),
            })
        return findings

    @classmethod
    def _scan_entry_reference_integrity(cls, owner_uid: str, sandbox: bool, company_id=None) -> List[Dict]:
        """Detecta asientos contables con referencias a documentos inexistentes."""
        findings = []
        try:
            from app.services.db_service import DatabaseService
            entries = DatabaseService.get_accounting_entries(owner_uid, company_id=company_id)
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, include_all=True, company_id=company_id)
            invoice_ids = {inv.get("id", "") for inv in invoices if inv.get("id")}
            for entry in entries[:500]:
                ref_id = entry.get("referenceId", "")
                ref_type = entry.get("referenceType", "")
                if ref_type in ("invoice", "expense", "credit_note") and ref_id and ref_id not in invoice_ids:
                    findings.append({
                        "type": "asiento_sin_origen",
                        "severity": SEVERITY_MEDIUM,
                        "entityId": entry.get("id", ""),
                        "entityLabel": f"Asiento {entry.get('number', '')}",
                        "detail": f"Asiento referencia {ref_type} {ref_id} que no existe.",
                        "referenceType": ref_type,
                        "referenceId": ref_id,
                    })
        except Exception as e:
            findings.append({
                "type": "error_escaneo",
                "severity": SEVERITY_HIGH,
                "entityId": "entry_scanner",
                "entityLabel": "Error en escáner de asientos",
                "detail": str(e),
            })
        return findings

    @classmethod
    def _scan_employee_branch_integrity(cls, owner_uid: str, sandbox: bool, company_id=None) -> List[Dict]:
        """Detecta empleados con branchId inexistente."""
        findings = []
        try:
            from app.services.db_service import DatabaseService
            branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox, company_id=company_id)
            branch_ids = {b.get("id", "") for b in branches if b.get("id")}
            employees = DatabaseService.get_employees(owner_uid, sandbox=sandbox, company_id=company_id) if hasattr(DatabaseService, 'get_employees') else []
            for emp in employees:
                branch_id = emp.get("branchId", "")
                if branch_id and branch_id != "default-sucursal-principal" and branch_id not in branch_ids:
                    findings.append({
                        "type": "empleado_sin_sucursal",
                        "severity": SEVERITY_MEDIUM,
                        "entityId": emp.get("id", ""),
                        "entityLabel": f"Empleado {emp.get('fullName', '')}",
                        "detail": f"Sucursal {branch_id} no encontrada.",
                    })
        except Exception as e:
            findings.append({
                "type": "error_escaneo",
                "severity": SEVERITY_HIGH,
                "entityId": "employee_scanner",
                "entityLabel": "Error en escáner de empleados",
                "detail": str(e),
            })
        return findings

    @classmethod
    def _scan_item_category_integrity(cls, owner_uid: str, sandbox: bool, company_id=None) -> List[Dict]:
        """Detecta items con categoryId inexistente."""
        findings = []
        try:
            from app.services.db_service import DatabaseService
            items = DatabaseService.get_items(owner_uid, sandbox=sandbox, company_id=company_id)
            categories = DatabaseService.get_categories(owner_uid, sandbox=sandbox, company_id=company_id)
            category_ids = {c.get("id", "") for c in categories if c.get("id")}
            for item in items[:500]:
                cat_id = item.get("categoryId", "")
                if cat_id and cat_id not in category_ids:
                    findings.append({
                        "type": "item_sin_categoria",
                        "severity": SEVERITY_LOW,
                        "entityId": item.get("id", ""),
                        "entityLabel": f"Item {item.get('name', '')}",
                        "detail": f"Categoría {cat_id} no encontrada.",
                    })
        except Exception as e:
            findings.append({
                "type": "error_escaneo",
                "severity": SEVERITY_HIGH,
                "entityId": "item_scanner",
                "entityLabel": "Error en escáner de items",
                "detail": str(e),
            })
        return findings
