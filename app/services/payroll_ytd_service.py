"""
PayrollYTService — Acumulación Year-to-Date por empleado y contrato.

Diseño extendido:
  - Clave: {employeeId}_{contractId}_{year} (contrato incluido para multi-contrato)
  - Acumuladores planos para acceso rápido (grossIncome, afpEmployee, etc.)
  - Acumuladores por concepto (byConcept) para reportes detallados
  - Acumuladores mensuales (monthly) para tendencias y proyecciones

Método de retención acumulada DGII 08-04:
  - Proyecta el ingreso anual basado en lo devengado YTD + lo esperado en períodos restantes.
  - Calcula ISR anual sobre esa proyección, resta lo ya retenido YTD, divide entre períodos restantes.
"""

from datetime import date
from app.services.db_service import db_firestore, firebase_initialized


def _ytd_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_ytd_accumulations"


YTD_FIELDS = [
    "grossIncome", "afpEmployee", "sfsEmployee", "infotepEmployee",
    "isrRetention", "otherDeductions", "netSalary",
    "afpEmployer", "sfsEmployer", "srlEmployer", "infotepEmployer",
    "totalEmployerContrib", "periodsCount",
]


def get_ytd(owner_uid: str, employee_id: str, year: int,
            contract_id: str = "", sandbox: bool = True) -> dict:
    """Obtiene los acumulados YTD de un empleado/contrato para un año."""
    if not firebase_initialized or db_firestore is None:
        return _empty_ytd(employee_id, year, contract_id)
    try:
        coll = _ytd_collection(owner_uid, sandbox)
        doc_id = _ytd_doc_id(employee_id, year, contract_id)
        doc = db_firestore.collection(coll).document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ PayrollYTService.get_ytd: {e}")
    return _empty_ytd(employee_id, year, contract_id)


def get_employee_ytd(owner_uid: str, employee_id: str, year: int,
                     sandbox: bool = True) -> dict:
    """Obtiene YTD consolidado de todos los contratos de un empleado."""
    if not firebase_initialized or db_firestore is None:
        return _empty_ytd(employee_id, year)
    try:
        coll = _ytd_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll)\
            .where("employeeId", "==", employee_id)\
            .where("year", "==", year).get()

        consolidated = _empty_ytd(employee_id, year)
        for d in docs:
            data = d.to_dict()
            for field in YTD_FIELDS:
                consolidated[field] = round(
                    consolidated.get(field, 0) + data.get(field, 0), 2
                )
            # Consolidar byConcept
            by_concept = data.get("byConcept", {})
            for code, values in by_concept.items():
                cc = consolidated.setdefault("byConcept", {}).get(code, {"type": "", "amount": 0.0, "periods": 0})
                consolidated.setdefault("byConcept", {})[code] = {
                    "type": values.get("type", ""),
                    "amount": round(cc.get("amount", 0) + values.get("amount", 0), 2),
                    "periods": cc.get("periods", 0) + values.get("periods", 1),
                }
            # Consolidar monthly
            monthly = data.get("monthly", {})
            for month_key, m_values in monthly.items():
                consolidated.setdefault("monthly", {})[month_key] = m_values

        return consolidated
    except Exception as e:
        print(f"⚠️ PayrollYTService.get_employee_ytd: {e}")
        return _empty_ytd(employee_id, year)


def save_ytd(owner_uid: str, employee_id: str, year: int,
             data: dict, contract_id: str = "", sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _ytd_collection(owner_uid, sandbox)
        doc_id = _ytd_doc_id(employee_id, year, contract_id)
        data["employeeId"] = employee_id
        data["year"] = year
        data["contractId"] = contract_id or ""
        db_firestore.collection(coll).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ PayrollYTService.save_ytd: {e}")


def _empty_ytd(employee_id: str, year: int, contract_id: str = "") -> dict:
    return {
        "employeeId": employee_id,
        "contractId": contract_id or "",
        "year": year,
        **{f: 0.0 for f in YTD_FIELDS if f != "periodsCount"},
        "periodsCount": 0,
        "byConcept": {},
        "monthly": {},
    }


def _ytd_doc_id(employee_id: str, year: int, contract_id: str = "") -> str:
    parts = [employee_id, str(year)]
    if contract_id:
        parts.insert(1, contract_id)
    return "_".join(parts)


def accumulate_ytd(prev_ytd: dict, payroll_line: dict,
                     period_factor: int = 12, period_key: str = "") -> dict:
    """Acumula los valores de una línea de nómina en los acumuladores YTD."""
    updated = dict(prev_ytd)
    updated["grossIncome"] = round(prev_ytd.get("grossIncome", 0) + payroll_line.get("totalIncome", 0), 2)
    updated["afpEmployee"] = round(prev_ytd.get("afpEmployee", 0) + payroll_line.get("afpEmployee", 0), 2)
    updated["sfsEmployee"] = round(prev_ytd.get("sfsEmployee", 0) + payroll_line.get("sfsEmployee", 0), 2)
    updated["infotepEmployee"] = round(prev_ytd.get("infotepEmployee", 0) + payroll_line.get("infotepEmployee", 0), 2)
    updated["isrRetention"] = round(prev_ytd.get("isrRetention", 0) + payroll_line.get("isrRetention", 0), 2)
    updated["otherDeductions"] = round(prev_ytd.get("otherDeductions", 0) + payroll_line.get("otherDeductions", 0), 2)
    updated["netSalary"] = round(prev_ytd.get("netSalary", 0) + payroll_line.get("netSalary", 0), 2)
    updated["afpEmployer"] = round(prev_ytd.get("afpEmployer", 0) + payroll_line.get("afpEmployer", 0), 2)
    updated["sfsEmployer"] = round(prev_ytd.get("sfsEmployer", 0) + payroll_line.get("sfsEmployer", 0), 2)
    updated["srlEmployer"] = round(prev_ytd.get("srlEmployer", 0) + payroll_line.get("srlEmployer", 0), 2)
    updated["infotepEmployer"] = round(prev_ytd.get("infotepEmployer", 0) + payroll_line.get("infotepEmployer", 0), 2)
    updated["totalEmployerContrib"] = round(prev_ytd.get("totalEmployerContrib", 0) + payroll_line.get("totalEmployerContrib", 0), 2)
    updated["periodsCount"] = prev_ytd.get("periodsCount", 0) + 1

    # ── NUEVO: Acumular por concepto ──
    by_concept = dict(prev_ytd.get("byConcept", {}))
    transaction_summary = payroll_line.get("transactionSummary", [])
    for tx in transaction_summary:
        code = tx.get("conceptCode", "")
        amount = float(tx.get("amount", 0))
        tx_type = tx.get("type", "")
        if code:
            existing = by_concept.get(code, {"type": tx_type, "amount": 0.0, "periods": 0})
            by_concept[code] = {
                "type": tx_type,
                "amount": round(existing["amount"] + amount, 2),
                "periods": existing["periods"] + 1,
            }
    updated["byConcept"] = by_concept

    # ── NUEVO: Acumular mensual ──
    if period_key:
        monthly = dict(prev_ytd.get("monthly", {}))
        # Extraer mes del periodKey (ej: "2026-07-M" → "2026-07")
        month_key = period_key[:7] if len(period_key) >= 7 else period_key
        monthly[month_key] = {
            "grossIncome": round(
                monthly.get(month_key, {}).get("grossIncome", 0) + payroll_line.get("totalIncome", 0), 2
            ),
            "netSalary": round(
                monthly.get(month_key, {}).get("netSalary", 0) + payroll_line.get("netSalary", 0), 2
            ),
            "isrRetention": round(
                monthly.get(month_key, {}).get("isrRetention", 0) + payroll_line.get("isrRetention", 0), 2
            ),
        }
        updated["monthly"] = monthly

    return updated