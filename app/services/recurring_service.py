"""RecurringService — Lógica de movimientos recurrentes de nómina.

Maneja:
  - Carga de movimientos aplicables por período
  - Aplicación de movimientos recurrentes (generación de PayrollTransaction)
  - Reversión de aplicaciones (recálculo)
  - Manejo de excepciones (skip, modify)
  - Actualización de saldos de préstamos
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.services.db_service import db_firestore, firebase_initialized
from app.models.transaction import PayrollTransaction
from app.models.recurring import RecurringMovement, RecurringException, RecurringApplication


def _recurring_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_recurring_movements"


def _exception_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_recurring_exceptions"


def _application_collection(owner_uid: str, sandbox: bool = True) -> str:
    prefix = "sandbox_" if sandbox else ""
    return f"users/{owner_uid}/{prefix}hr_recurring_applications"


def _doc_to_dict(doc) -> dict:
    return {"id": doc.id, **doc.to_dict()}


# ═══════════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════════


def get_recurring_movements(owner_uid: str, employee_id: str = "",
                             contract_id: str = "", status: str = "",
                             movement_type: str = "", concept_code: str = "",
                             payroll_group_id: str = "",
                             sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll = _recurring_collection(owner_uid, sandbox)
        query = db_firestore.collection(coll)
        if employee_id:
            query = query.where("employeeId", "==", employee_id)
        if contract_id:
            query = query.where("contractId", "==", contract_id)
        if status:
            query = query.where("status", "==", status)
        if movement_type:
            query = query.where("movementType", "==", movement_type)
        if concept_code:
            query = query.where("conceptCode", "==", concept_code)
        docs = query.get()
        results = [_doc_to_dict(d) for d in docs]
        if payroll_group_id:
            def _matches_payroll_group(mv):
                groups = mv.get("payrollGroupIds", []) or []
                clean = [g for g in groups if g]
                if not clean:
                    return True
                return payroll_group_id in clean
            results = [r for r in results if _matches_payroll_group(r)]
        return results
    except Exception as e:
        print(f"⚠️ RecurringService.get_recurring_movements: {e}")
        return []


def get_recurring_movement(owner_uid: str, rm_id: str,
                           sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll = _recurring_collection(owner_uid, sandbox)
        doc = db_firestore.collection(coll).document(rm_id).get()
        return _doc_to_dict(doc) if doc.exists else None
    except Exception as e:
        print(f"⚠️ RecurringService.get_recurring_movement: {e}")
        return None


def save_recurring_movement(owner_uid: str, rm_id: str, data: dict,
                            sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _recurring_collection(owner_uid, sandbox)
        now_iso = datetime.now(timezone.utc).isoformat()
        data["id"] = rm_id
        if data.get("createdAt") is None:
            data["createdAt"] = now_iso
        data["updatedAt"] = now_iso
        db_firestore.collection(coll).document(rm_id).set(data)
    except Exception as e:
        print(f"⚠️ RecurringService.save_recurring_movement: {e}")


def delete_recurring_movement(owner_uid: str, rm_id: str,
                              sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _recurring_collection(owner_uid, sandbox)
        db_firestore.collection(coll).document(rm_id).delete()
    except Exception as e:
        print(f"⚠️ RecurringService.delete_recurring_movement: {e}")


# ═══════════════════════════════════════════════════════════════════════
# EXCEPCIONES
# ═══════════════════════════════════════════════════════════════════════


def get_exception(owner_uid: str, rm_id: str, period_key: str,
                  sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll = _exception_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll)\
            .where("recurringMovementId", "==", rm_id)\
            .where("periodKey", "==", period_key).get()
        for d in docs:
            return _doc_to_dict(d)
        return None
    except Exception as e:
        print(f"⚠️ RecurringService.get_exception: {e}")
        return None


def save_exception(owner_uid: str, exc_id: str, data: dict,
                   sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _exception_collection(owner_uid, sandbox)
        data["id"] = exc_id
        db_firestore.collection(coll).document(exc_id).set(data)
    except Exception as e:
        print(f"⚠️ RecurringService.save_exception: {e}")


# ═══════════════════════════════════════════════════════════════════════
# APLICACIONES
# ═══════════════════════════════════════════════════════════════════════


def get_application(owner_uid: str, rm_id: str, period_id: str,
                    sandbox: bool = True) -> dict | None:
    if not firebase_initialized or db_firestore is None:
        return None
    try:
        coll = _application_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll)\
            .where("recurringMovementId", "==", rm_id)\
            .where("periodId", "==", period_id).get()
        for d in docs:
            return _doc_to_dict(d)
        return None
    except Exception as e:
        print(f"⚠️ RecurringService.get_application: {e}")
        return None


def save_application(owner_uid: str, app_id: str, data: dict,
                     sandbox: bool = True):
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _application_collection(owner_uid, sandbox)
        data["id"] = app_id
        db_firestore.collection(coll).document(app_id).set(data)
    except Exception as e:
        print(f"⚠️ RecurringService.save_application: {e}")


def save_applications_batch(owner_uid: str, applications: list,
                            sandbox: bool = True):
    if not firebase_initialized or db_firestore is None or not applications:
        return
    try:
        coll = _application_collection(owner_uid, sandbox)
        batch = db_firestore.batch()
        for app in applications:
            app_id = app.get("id", str(uuid.uuid4()))
            app["id"] = app_id
            batch.set(db_firestore.collection(coll).document(app_id), app)
        batch.commit()
    except Exception as e:
        print(f"⚠️ RecurringService.save_applications_batch: {e}")


def get_applications_by_period(owner_uid: str, period_id: str,
                               sandbox: bool = True) -> list:
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        coll = _application_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll)\
            .where("periodId", "==", period_id).get()
        return [_doc_to_dict(d) for d in docs]
    except Exception as e:
        print(f"⚠️ RecurringService.get_applications_by_period: {e}")
        return []


def delete_applications_by_period(owner_uid: str, period_id: str,
                                  sandbox: bool = True):
    """Elimina todas las aplicaciones de un período (usado en recálculos)."""
    if not firebase_initialized or db_firestore is None:
        return
    try:
        coll = _application_collection(owner_uid, sandbox)
        docs = db_firestore.collection(coll)\
            .where("periodId", "==", period_id).get()
        batch = db_firestore.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
    except Exception as e:
        print(f"⚠️ RecurringService.delete_applications_by_period: {e}")


# ═══════════════════════════════════════════════════════════════════════
# LÓGICA DE APLICACIÓN
# ═══════════════════════════════════════════════════════════════════════


def _normalize_movement_type(mv_type: str) -> str:
    """Normaliza cualquier tipo de movimiento a los 3 estándares: earning, deduction, employer_contrib.
    
    "loan", "garnishment", "other_deduction", etc. → "deduction"
    """
    if mv_type == "earning":
        return "earning"
    if mv_type == "employer_contrib":
        return "employer_contrib"
    return "deduction"


def is_applicable(movement: dict, period_start: str, period_end: str) -> bool:
    """Determina si un movimiento recurrente aplica en un período."""
    status = movement.get("status", "")
    if status not in ("active", "scheduled"):
        return False

    start_date = movement.get("startDate", "")
    end_date = movement.get("endDate", "")

    # Inicio: ya empezó?
    if start_date and period_end < start_date:
        return False
    # Fin: ya terminó?
    if end_date and period_start > end_date:
        return False

    # Indefinido o dentro del rango
    return True


def resolve_amount(movement: dict, base_salary: float, context: dict = None) -> float:
    """Resuelve el monto a aplicar según amountType."""
    amount_type = movement.get("amountType", "fixed")
    amount = float(movement.get("amount", 0))

    # Para préstamos, usar installmentAmount si amount no está configurado
    if movement.get("isLoan") and amount == 0:
        amount = float(movement.get("installmentAmount", 0))

    if amount_type == "fixed":
        return amount
    elif amount_type == "percentage":
        pct = float(movement.get("percentage", 0))
        salary = base_salary
        if context and context.get("other_income"):
            salary += float(context["other_income"])
        return round(salary * pct, 2)
    elif amount_type == "formula":
        formula = movement.get("formula", "")
        if formula and "baseSalary" in formula:
            try:
                simple_formula = formula.replace("baseSalary", str(base_salary))
                return round(eval(simple_formula), 2)
            except Exception:
                return amount
    return amount


def apply_recurring_for_employee(owner_uid: str, employee_id: str,
                                  contract_id: str, base_salary: float,
                                  period_id: str, period_key: str,
                                  period_start: str, period_end: str,
                                  period_revision: int,
                                  grouped_movements: dict,
                                  legal_entity_id: str = "",
                                  group_id: str = "",
                                  sandbox: bool = True) -> tuple:
    """Aplica los movimientos recurrentes de un empleado.

    Args:
        employee_id: ID del empleado
        contract_id: ID del contrato
        base_salary: Salario base del período
        period_id, period_key, period_start, period_end: Datos del período
        period_revision: Revisión del período
        grouped_movements: Dict {employeeId: [movements]} — movimientos pre-cargados
        legal_entity_id, group_id: Contexto del período

    Returns:
        (transactions, applications) donde:
          transactions: Lista de PayrollTransaction dicts
          applications: Lista de RecurringApplication dicts
    """
    transactions = []
    applications = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Obtener movimientos del empleado
    movements = grouped_movements.get(employee_id, []) if grouped_movements else []

    for mv in movements:
        if not is_applicable(mv, period_start, period_end):
            continue

        mv_id = mv.get("id", "")
        concept_code = mv.get("conceptCode", "")

        # Verificar si hay excepción para este período
        exc = get_exception(owner_uid, mv_id, period_key, sandbox=sandbox)

        if exc and exc.get("action") == "skip":
            applications.append({
                "id": str(uuid.uuid4()),
                "recurringMovementId": mv_id,
                "employeeId": employee_id,
                "periodId": period_id,
                "periodKey": period_key,
                "periodRevision": period_revision,
                "transactionId": "",
                "appliedAmount": 0.0,
                "remainingAfter": float(mv.get("remainingBalance", 0)),
                "action": "skipped",
                "appliedAt": now_iso,
            })
            continue

        # Resolver monto
        amount = resolve_amount(mv, base_salary)

        if exc and exc.get("action") == "modify":
            amount = float(exc.get("modifiedAmount", amount))

        if amount <= 0:
            continue

        transaction_id = str(uuid.uuid4())

        # Crear PayrollTransaction
        mv_type = _normalize_movement_type(mv.get("movementType", "deduction"))
        tx = PayrollTransaction(
            id=transaction_id,
            periodId=period_id,
            periodKey=period_key,
            employeeId=employee_id,
            contractId=contract_id,
            legalEntityId=legal_entity_id,
            groupId=group_id,
            conceptCode=concept_code,
            type=mv_type,
            amount=amount,
            source=f"recurring:{mv_id}",
            sourceId=mv_id,
            isRecurring=True,
            recurringMovementId=mv_id,
            periodRevision=period_revision,
            status="applied",
            conceptSnapshot={
                "code": concept_code,
                "name": mv.get("description", concept_code),
                "type": mv_type,
                "affectsISR": mv_type == "earning",
                "affectsTSS": mv_type == "earning",
                "affectsNet": mv_type == "deduction",
                "accountDebit": "",
                "accountCredit": "",
                "conceptVersion": 1,
                "category": "recurring",
                "maxPercentage": 0.0,
            },
            priority=mv.get("priority", 50),
            periodYear=int(period_key[:4]) if period_key and len(period_key) >= 4 else 0,
            notes=mv.get("description", ""),
            createdAt=now_iso,
            updatedAt=now_iso,
        )

        # Actualizar saldo si es préstamo
        remaining_after = 0.0
        if mv.get("isLoan"):
            remaining = float(mv.get("remainingBalance", 0))
            remaining_after = round(remaining - amount, 2)
            paid = mv.get("paidInstallments", 0) + 1
            new_status = "completed" if remaining_after <= 0 and mv.get("autoComplete") else "active"

            # Actualizar en DB
            mv["remainingBalance"] = max(0, remaining_after)
            mv["paidInstallments"] = paid
            if new_status == "completed":
                mv["status"] = "completed"
            save_recurring_movement(owner_uid, mv_id, mv, sandbox=sandbox)

        # Crear RecurringApplication
        app = {
            "id": str(uuid.uuid4()),
            "recurringMovementId": mv_id,
            "employeeId": employee_id,
            "periodId": period_id,
            "periodKey": period_key,
            "periodRevision": period_revision,
            "transactionId": transaction_id,
            "appliedAmount": amount,
            "remainingAfter": max(0, remaining_after),
            "action": "applied",
            "appliedAt": now_iso,
        }

        transactions.append(tx.model_dump())
        applications.append(app)

    return transactions, applications


def reverse_applications(owner_uid: str, period_id: str,
                          sandbox: bool = True):
    """Reviente las aplicaciones de un período y restaura saldos.

    Se llama durante recálculo (revertir a borrador).
    """
    applications = get_applications_by_period(owner_uid, period_id, sandbox=sandbox)
    for app in applications:
        if app.get("action") != "applied":
            continue
        rm_id = app.get("recurringMovementId", "")
        amount = float(app.get("appliedAmount", 0))
        if not rm_id or amount <= 0:
            continue

        rm = get_recurring_movement(owner_uid, rm_id, sandbox=sandbox)
        if rm and rm.get("isLoan"):
            rm["remainingBalance"] = round(float(rm.get("remainingBalance", 0)) + amount, 2)
            rm["paidInstallments"] = max(0, rm.get("paidInstallments", 1) - 1)
            if rm.get("status") == "completed":
                rm["status"] = "active"
            save_recurring_movement(owner_uid, rm_id, rm, sandbox=sandbox)

    delete_applications_by_period(owner_uid, period_id, sandbox=sandbox)