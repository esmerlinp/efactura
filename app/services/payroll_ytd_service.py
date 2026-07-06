"""
PayrollYTService — Acumulación Year-to-Date por empleado para ISR acumulado y certificados fiscales.

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


def get_ytd(owner_uid: str, employee_id: str, year: int, sandbox: bool = True) -> dict:
    if not firebase_initialized or db_firestore is None:
        return _empty_ytd(employee_id, year)
    try:
        coll = _ytd_collection(owner_uid, sandbox)
        doc_id = f"{employee_id}_{year}"
        doc = db_firestore.collection(coll).document(doc_id).get()
        if doc.exists:
            return doc.to_dict()
    except Exception as e:
        print(f"⚠️ PayrollYTService.get_ytd: {e}")
    return _empty_ytd(employee_id, year)


def save_ytd(owner_uid: str, employee_id: str, year: int, data: dict, sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _ytd_collection(owner_uid, sandbox)
        doc_id = f"{employee_id}_{year}"
        db_firestore.collection(coll).document(doc_id).set(data)
    except Exception as e:
        print(f"⚠️ PayrollYTService.save_ytd: {e}")


def _empty_ytd(employee_id: str, year: int) -> dict:
    return {
        "employeeId": employee_id,
        "year": year,
        **{f: 0.0 for f in YTD_FIELDS if f != "periodsCount"},
        "periodsCount": 0,
    }


def accumulate_ytd(prev_ytd: dict, payroll_line: dict, period_factor: int = 12) -> dict:
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
    return updated
