"""Administrative UI for the approved recurring-contract domain."""

from __future__ import annotations

from datetime import date
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from app.models.recurring_contract import BillingMode, RecurringContract, RecurringContractStatus
from app.services.db_service import DatabaseService, _resolve_company_id, db_firestore
from app.services.recurring_contract_flag_loader import firestore_recurring_contract_flag_loader
from app.services.recurring_contract_fiscal_service import RecurringContractFiscalService
from app.services.recurring_contract_occurrence_service import RecurringContractOccurrenceService
from app.services.recurring_contract_outbox_service import OutboxCommandService
from app.services.recurring_contract_service import RecurringContractFeatureFlags, RecurringContractService
from app.services.recurring_contract_admin_service import RecurringContractAdminService
from app.utils.decorators import check_permission
from app.utils.module_gate import require_module


recurring_contracts_admin_bp = Blueprint("recurring_contracts_admin", __name__)


@recurring_contracts_admin_bp.before_request
def _require_active_company():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    company_id = session.get("selected_company_id") or _resolve_company_id(
        session["user"].get("ownerUID")
    )
    if not company_id:
        flash("No hay una empresa activa seleccionada.", "error")
        return redirect(url_for("web_auth.select_company"))
    return None


def _context():
    owner_uid = session["user"]["ownerUID"]
    company_id = session.get('selected_company_id') or _resolve_company_id(owner_uid)
    sandbox = session.get("is_sandbox_mode", True)
    return owner_uid, company_id, sandbox


def _guard():
    if "user" not in session:
        return redirect(url_for("web_auth.login"))
    if not check_permission("canManageContracts"):
        return render_template("auth/restricted.html", feature_name="Contratos recurrentes", required_permission="canManageContracts"), 403
    return None


def _contract_from_data(data):
    if data.get("schemaVersion") != 2:
        return None
    # Firestore conserva campos legacy/extra junto al documento V2
    # (branchId, contractLines, metadata…); el dominio solo valida sus campos.
    domain_fields = set(RecurringContract.model_fields)
    return RecurringContract.model_validate({
        key: value for key, value in data.items() if key in domain_fields
    })


class _DatabaseContractRepository:
    def __init__(self, owner_uid, company_id, sandbox):
        self.owner_uid = owner_uid
        self.company_id = company_id
        self.sandbox = sandbox

    def _payload(self, contract):
        # save_contract hace set() completo: se parte del documento existente
        # para no perder campos fuera del dominio (branchId, contractLines,
        # quotation_id, metadata legacy, etc.).
        existing = DatabaseService.get_contract(
            self.owner_uid, contract.id, company_id=self.company_id, sandbox=self.sandbox
        ) or {}
        payload = dict(existing)
        payload.update(contract.model_dump(mode="json"))
        payload["schemaVersion"] = 2
        return payload

    def create(self, contract):
        return DatabaseService.save_contract(self.owner_uid, contract.id, self._payload(contract), company_id=self.company_id, sandbox=self.sandbox)

    def update(self, contract):
        return DatabaseService.save_contract(self.owner_uid, contract.id, self._payload(contract), company_id=self.company_id, sandbox=self.sandbox)


def _admin_service(owner_uid, company_id, sandbox):
    return RecurringContractAdminService(_DatabaseContractRepository(owner_uid, company_id, sandbox))


@recurring_contracts_admin_bp.route("/operations/recurring-contracts", methods=["GET"])
@require_module("contratos")
def recurring_contract_list():
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    raw = DatabaseService.get_contracts(owner_uid, company_id=company_id, sandbox=sandbox)
    client_filter = request.args.get("client", "").strip().lower()
    status_filter = request.args.get("status", "").strip().lower()
    frequency_filter = request.args.get("frequency", "").strip().lower()
    fiscal_filter = request.args.get("fiscal", "").strip().lower()
    contracts = []
    for item in raw:
        try:
            full = DatabaseService.get_contract(owner_uid, item["id"], company_id=company_id, sandbox=sandbox)
            contract = _contract_from_data(full or {})
        except Exception:
            contract = None
        if not contract:
            continue
        if client_filter and client_filter not in f"{contract.client_name_snapshot} {contract.client_id}".lower():
            continue
        if status_filter and contract.status.value != status_filter:
            continue
        if frequency_filter and contract.frequency.value != frequency_filter:
            continue
        if fiscal_filter == "review" and not contract.needs_fiscal_review:
            continue
        if fiscal_filter == "ready" and contract.needs_fiscal_review:
            continue
        contracts.append(contract)
    return render_template(
        "operations/recurring_contracts_admin.html",
        active_page="contracts",
        contracts=contracts,
        fiscal_types=RecurringContractFiscalService.eligible_types(),
        flag_enabled=firestore_recurring_contract_flag_loader(db_firestore, company_id, sandbox),
        filters=request.args,
    )


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/<contract_id>", methods=["GET"])
@require_module("contratos")
def recurring_contract_detail(contract_id):
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    data = DatabaseService.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
    if not data:
        flash("Contrato no encontrado.", "error")
        return redirect(url_for("recurring_contracts_admin.recurring_contract_list"))
    try:
        contract = _contract_from_data(data)
    except Exception as exc:
        flash(f"El contrato no tiene un formato nuevo válido: {exc}", "error")
        return redirect(url_for("recurring_contracts_admin.recurring_contract_list"))
    occurrences = []
    outbox = []
    if db_firestore:
        occurrence_service = RecurringContractOccurrenceService(db_firestore)
        occurrence_docs = occurrence_service._collection(company_id, sandbox).where("contract_id", "==", contract.id).get()
        occurrences = [doc.to_dict() for doc in occurrence_docs]
        outbox_docs = OutboxCommandService(db_firestore)._collection(company_id, sandbox).where("contract_id", "==", contract.id).get()
        outbox = [doc.to_dict() for doc in outbox_docs]
    invoices = DatabaseService.get_invoices_by_contract(
        owner_uid, contract.id, company_id=company_id, sandbox=sandbox
    )
    invoices.sort(key=lambda inv: inv.get("date", ""), reverse=True)
    return render_template(
        "operations/recurring_contract_detail.html",
        active_page="contracts",
        contract=contract,
        occurrences=occurrences,
        outbox=outbox,
        invoices=invoices,
        fiscal_types=RecurringContractFiscalService.eligible_types(),
        flag_enabled=firestore_recurring_contract_flag_loader(db_firestore, company_id, sandbox),
    )


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/<contract_id>/status", methods=["POST"])
@require_module("contratos")
def recurring_contract_status(contract_id):
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    data = DatabaseService.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
    if not data:
        flash("Contrato no encontrado.", "error")
        return redirect(url_for("recurring_contracts_admin.recurring_contract_list"))
    contract = _contract_from_data(data)
    target = RecurringContractStatus(request.form.get("status", ""))
    updated = contract.transition_to(target)
    payload = updated.model_dump(mode="json")
    payload["schemaVersion"] = 2
    DatabaseService.save_contract(owner_uid, contract_id, payload, company_id=company_id, sandbox=sandbox)
    flash("Estado actualizado. Las condiciones históricas permanecen intactas.", "success")
    return redirect(url_for("recurring_contracts_admin.recurring_contract_detail", contract_id=contract_id))


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/new", methods=["POST"])
@require_module("contratos")
def recurring_contract_create():
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    try:
        contract = RecurringContract(
            owner_uid=owner_uid,
            company_id=company_id,
            contract_number=request.form.get("contract_number", ""),
            client_id=request.form["client_id"],
            client_name_snapshot=request.form.get("client_name", ""),
            client_rnc_snapshot=request.form.get("client_rnc", ""),
            start_date=date.fromisoformat(request.form["start_date"]),
            billing_anchor_date=date.fromisoformat(request.form["billing_anchor_date"]),
            billing_day=int(request.form.get("billing_day") or 1),
            status=RecurringContractStatus.DRAFT,
            ecf_type=request.form.get("ecf_type") or None,
            needs_fiscal_review=not bool(request.form.get("ecf_type")),
        )
        _admin_service(owner_uid, company_id, sandbox).create(contract)
        flash("Contrato creado en estado borrador.", "success")
        return redirect(url_for("recurring_contracts_admin.recurring_contract_detail", contract_id=contract.id))
    except Exception as exc:
        flash(f"No se pudo crear el contrato: {exc}", "error")
        return redirect(url_for("recurring_contracts_admin.recurring_contract_list"))


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/<contract_id>/terms", methods=["POST"])
@require_module("contratos")
def recurring_contract_terms(contract_id):
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    data = DatabaseService.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
    if not data:
        flash("Contrato no encontrado.", "error")
        return redirect(url_for("recurring_contracts_admin.recurring_contract_list"))
    try:
        contract = _contract_from_data(data)
        lines = tuple(contract.lines)
        updated = _admin_service(owner_uid, company_id, sandbox).update_terms(
            contract,
            effective_from=date.fromisoformat(request.form["effective_from"]),
            ecf_type=request.form.get("ecf_type") or None,
            currency=request.form.get("currency", contract.currency),
            payment_type=request.form.get("payment_type", contract.payment_type),
            payment_method=request.form.get("payment_method", contract.payment_method),
            credit_days=int(request.form.get("credit_days") or contract.credit_days),
            billing_mode=BillingMode(request.form.get("billing_mode", contract.billing_mode.value)),
            lines=lines,
            notes=request.form.get("notes", ""),
        )
        flash("Nueva versión contractual guardada.", "success")
    except Exception as exc:
        flash(f"No se pudo versionar el contrato: {exc}", "error")
    return redirect(url_for("recurring_contracts_admin.recurring_contract_detail", contract_id=contract_id))


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/<contract_id>/cancel-request", methods=["POST"])
@require_module("contratos")
def recurring_contract_cancel_request(contract_id):
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    data = DatabaseService.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
    if data:
        contract = _contract_from_data(data)
        _admin_service(owner_uid, company_id, sandbox).request_cancellation(contract, request.form.get("reason", "Solicitud administrativa"))
        flash("Solicitud de cancelación registrada.", "success")
    return redirect(url_for("recurring_contracts_admin.recurring_contract_detail", contract_id=contract_id))


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/<contract_id>/renew", methods=["POST"])
@require_module("contratos")
def recurring_contract_renew(contract_id):
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    data = DatabaseService.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
    try:
        contract = _contract_from_data(data or {})
        _admin_service(owner_uid, company_id, sandbox).renew(contract, new_end_date=date.fromisoformat(request.form["new_end_date"]))
        flash("Contrato renovado.", "success")
    except Exception as exc:
        flash(f"No se pudo renovar: {exc}", "error")
    return redirect(url_for("recurring_contracts_admin.recurring_contract_detail", contract_id=contract_id))


@recurring_contracts_admin_bp.route("/operations/recurring-contracts/<contract_id>/fiscal-review", methods=["POST"])
@require_module("contratos")
def recurring_contract_fiscal_review(contract_id):
    blocked = _guard()
    if blocked:
        return blocked
    owner_uid, company_id, sandbox = _context()
    data = DatabaseService.get_contract(owner_uid, contract_id, company_id=company_id, sandbox=sandbox)
    try:
        contract = _contract_from_data(data or {})
        _admin_service(owner_uid, company_id, sandbox).resolve_fiscal_review(contract, ecf_type=request.form["ecf_type"])
        flash("Revisión fiscal resuelta para futuras emisiones.", "success")
    except Exception as exc:
        flash(f"No se pudo resolver la revisión fiscal: {exc}", "error")
    return redirect(request.referrer or url_for("recurring_contracts_admin.recurring_contract_detail", contract_id=contract_id))
