"""Afiliaciones de seguro con snapshot economico inmutable."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.services.db_service import db_firestore, firebase_initialized
from app.services.insurance_cost_calculator import calculate_contribution
from app.services.insurance_plan_service import get_plan


def _collection(company_id, sandbox=True):
    return f"companies/{company_id}/{('sandbox_' if sandbox else '')}hr_insurance_enrollments"


def _now():
    return datetime.now(timezone.utc).isoformat()


def list_enrollments(company_id, employee_id="", sandbox=True):
    if not firebase_initialized or db_firestore is None:
        return []
    query = db_firestore.collection(_collection(company_id, sandbox))
    if employee_id:
        query = query.where("employeeId", "==", employee_id)
    return [{"id": doc.id, **doc.to_dict()} for doc in query.get()]


def create_enrollment(company_id, data, user_email="", sandbox=True):
    plan = get_plan(company_id, data.get("planId", ""), sandbox=sandbox)
    if not plan or plan.get("status") != "active":
        raise ValueError("El plan debe existir y estar activo.")
    result = calculate_contribution(plan.get("baseAmount", 0), plan.get("companyContribution"), plan.get("employeeContribution"))
    enrollment_id = data.get("id") or str(uuid.uuid4())
    now = _now()
    company_rule = plan["companyContribution"]
    employee_rule = plan["employeeContribution"]
    payload = dict(data)
    payload.update({
        "id": enrollment_id,
        "providerId": plan.get("providerId", ""),
        "baseAmount": str(result["totalAmount"]),
        "currency": plan.get("currency", "DOP"),
        "companyContributionType": company_rule["type"],
        "companyContributionValue": company_rule.get("value"),
        "companyContributionAmount": str(result["companyAmount"]),
        "employeeContributionType": employee_rule["type"],
        "employeeContributionValue": employee_rule.get("value"),
        "employeeContributionAmount": str(result["employeeAmount"]),
        "payrollConceptId": plan.get("payrollConceptId", "SEGURO"),
        "prorationPolicy": plan.get("prorationPolicy", "none"),
        "status": "active",
        "createdAt": now,
        "createdBy": user_email,
        "updatedAt": now,
        "updatedBy": user_email,
    })
    if not firebase_initialized or db_firestore is None:
        return payload
    db_firestore.collection(_collection(company_id, sandbox)).document(enrollment_id).set(payload)
    return payload


def cancel_enrollment(company_id, enrollment_id, end_date, user_email="", sandbox=True):
    if not firebase_initialized or db_firestore is None:
        raise ValueError("La afiliacion no esta disponible.")
    ref = db_firestore.collection(_collection(company_id, sandbox)).document(enrollment_id)
    doc = ref.get()
    if not doc.exists:
        raise ValueError("Afiliacion no encontrada.")
    now = _now()
    ref.update({"status": "cancelled", "endDate": end_date, "cancelledAt": now, "cancelledBy": user_email, "updatedAt": now, "updatedBy": user_email})


def build_payroll_transactions(company_id, employee_id, period_id, period_key,
                               period_start, period_end, payroll_line_id="",
                               contract_id="", group_id="", period_revision=1,
                               sandbox=True):
    """Construye transacciones desde snapshots, sin leer reglas del plan."""
    from app.models.transaction import PayrollTransaction
    from app.services.payroll_concept_engine import get_concept, build_concept_snapshot

    transactions = []
    now = _now()
    for enrollment in list_enrollments(company_id, employee_id, sandbox=sandbox):
        if enrollment.get("status") != "active":
            continue
        start = enrollment.get("startDate", "")
        end = enrollment.get("endDate", "")
        if start and period_end < start:
            continue
        if end and period_start > end:
            continue
        amount = Decimal(str(enrollment.get("employeeContributionAmount", "0")))
        if amount <= 0:
            continue
        concept_code = enrollment.get("payrollConceptId", "SEGURO")
        concept = get_concept(company_id, concept_code, sandbox=sandbox) or {
            "code": concept_code, "name": "Seguro", "type": "deduction", "category": "recurring"
        }
        tx = PayrollTransaction(
            id=str(uuid.uuid4()), periodId=period_id, periodKey=period_key,
            payrollLineId=payroll_line_id, employeeId=employee_id,
            contractId=contract_id, groupId=group_id, conceptCode=concept_code,
            type="deduction", amount=float(amount), source=f"insurance:{enrollment['id']}",
            sourceId=enrollment["id"], status="applied", periodRevision=period_revision,
            conceptSnapshot=build_concept_snapshot(concept), priority=350,
            notes="Afiliacion de seguro", createdAt=now, updatedAt=now,
        ).model_dump()
        tx.update({
            "insuranceEnrollmentId": enrollment["id"],
            "insurancePlanId": enrollment.get("planId", ""),
            "insuranceProviderId": enrollment.get("providerId", ""),
            "insuranceBaseAmount": enrollment.get("baseAmount", "0"),
            "insuranceCompanyAmount": enrollment.get("companyContributionAmount", "0"),
            "insuranceEmployeeAmount": enrollment.get("employeeContributionAmount", "0"),
        })
        transactions.append(tx)
    return transactions
