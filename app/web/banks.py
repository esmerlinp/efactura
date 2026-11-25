import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.db_service import DatabaseService
from app.services.accounting_service import AccountingService
from app.utils.decorators import check_permission
from app.utils.module_gate import module_enabled

web_banks_bp = Blueprint('web_banks', __name__)


@web_banks_bp.before_request
def _check_banks_module():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not module_enabled('banks'):
        if request.is_json or request.headers.get('Accept') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                "success": False,
                "error": {
                    "code": "MODULE_DISABLED",
                    "message": "El módulo 'Bancos' no está contratado en tu plan actual."
                }
            }), 403
        return render_template(
            'auth/restricted.html',
            feature_name="Bancos & Conciliación",
            required_permission="module_banks",
            custom_message="El módulo <strong>Bancos & Conciliación</strong> no está incluido en tu plan actual. "
                           "Contacta a soporte para información sobre mejoras de plan."
        ), 403


ACCOUNT_TYPES = {
    "banco": "Banco",
    "efectivo": "Efectivo",
    "tarjeta": "Tarjeta de crédito"
}


def _payment_parent_id(doc_path, coll_name):
    """Extrae el id del documento padre (factura/gasto) de un subdocumento de pago.

    Soporta el layout company-scoped y el legacy:
        companies/{company_id}/{coll_name}/{parent_id}/payments/{pmt_id}
        users/{owner_uid}/{coll_name}/{parent_id}/payments/{pmt_id}
    Devuelve None si la ruta no corresponde a la colección indicada.
    """
    parts = (doc_path or "").split('/')
    if len(parts) >= 6 and parts[2] == coll_name:
        return parts[3]
    return None


def _load_account_payment_transactions(owner_uid, account_id, sandbox, company_id,
                                      type_filter='', date_from='', date_to=''):
    """Carga pagos aplicando filtros antes de construir los movimientos."""
    transactions = []

    if type_filter in ('', 'income'):
        # Include both fiscal invoices and commercial proformas. Payments on a
        # proforma are real collections and must appear in the bank ledger.
        invoices = DatabaseService.get_invoices(
            owner_uid,
            sandbox=sandbox,
            include_all=True,
            company_id=company_id,
        )
        for inv in invoices:
            inv_id = inv.get('id')
            if not inv_id:
                continue
            for pmt in DatabaseService.get_invoice_payments(
                owner_uid, inv_id, sandbox=sandbox, company_id=company_id
            ):
                payment_date = str(pmt.get('paymentDate', ''))[:10]
                if (pmt.get('bankAccountId') != account_id or
                        (date_from and payment_date < date_from) or
                        (date_to and payment_date > date_to)):
                    continue
                transactions.append({
                    "date": payment_date,
                    "type": "income",
                    "concept": f"Pago {inv.get('invoiceNumber', '')} — {inv.get('clientName', '')}",
                    "amount": float(pmt.get('amount', 0)),
                    "reference": pmt.get('referenceNumber', ''),
                    "invoiceId": inv_id,
                    "paymentId": pmt.get("id", ""),
                    "documentType": inv.get('documentType', ''),
                })

    if type_filter in ('', 'expense'):
        from app.services.supplier_invoice_service import SupplierInvoiceService

        supplier_invoices = SupplierInvoiceService.get_all(
            owner_uid=owner_uid, sandbox=sandbox, company_id=company_id
        ) or []
        for inv in supplier_invoices:
            if SupplierInvoiceService.is_voided(inv):
                continue
            inv_id = inv.get('id')
            if not inv_id:
                continue
            for pmt in SupplierInvoiceService.get_payments(
                owner_uid=owner_uid, invoice_id=inv_id,
                sandbox=sandbox, company_id=company_id
            ):
                payment_date = str(pmt.get('paymentDate', ''))[:10]
                if (pmt.get('bankAccountId') != account_id or
                        (date_from and payment_date < date_from) or
                        (date_to and payment_date > date_to)):
                    continue
                transactions.append({
                    "date": payment_date,
                    "type": "expense",
                    "concept": f"Pago proveedor {inv.get('invoiceNumber', '')} — {inv.get('supplierName', '')}",
                    "amount": -float(pmt.get('amount', 0)),
                    "reference": pmt.get('reference', ''),
                    "expenseId": inv_id,
                    "invoiceId": ''
                })

    return transactions

@web_banks_bp.route('/banks')
def list_banks():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox, company_id=company_id)
    summary = DatabaseService.get_bank_summary(owner_uid, sandbox=sandbox, company_id=company_id)

    return render_template('banks/list.html', active_page='banks',
                           accounts=accounts, summary=summary,
                           account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/<account_id>')
def bank_detail(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    transaction_types = {"income", "expense", "transfer_in", "transfer_out"}
    type_filter = request.args.get('type', '').strip()
    if type_filter not in transaction_types:
        type_filter = ''
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    quick_filter = request.args.get('quick', 'today').strip().lower()
    if quick_filter in ('today', 'week', 'month', 'year') and not request.args.get('date_from') and not request.args.get('date_to'):
        base = datetime.now(timezone.utc)
        if quick_filter == 'today':
            date_from = date_to = today
        elif quick_filter == 'week':
            start = base - timedelta(days=base.weekday())
            date_from, date_to = start.strftime('%Y-%m-%d'), today
        elif quick_filter == 'month':
            date_from, date_to = base.strftime('%Y-%m-01'), today
        else:
            date_from, date_to = base.strftime('%Y-01-01'), today
    origin_filter = request.args.get('origin', '').strip().lower()
    movement_query = request.args.get('q', '').strip().lower()
    if not date_from and not date_to:
        date_from = date_to = today
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    page_size = 25
    refresh = request.args.get('refresh') == '1'
    from app.services.cache_service import CacheService
    cache_key = CacheService.domain_key('bank_movements', company_id, sandbox, account_id, type_filter, date_from, date_to, origin_filter, movement_query)
    if refresh:
        CacheService.invalidate_bank_movements(company_id, sandbox=sandbox)
    cached_transactions = None if refresh else CacheService.get_cache().get(cache_key)
    try:
        if date_from:
            datetime.strptime(date_from, '%Y-%m-%d')
    except ValueError:
        date_from = ''
    try:
        if date_to:
            datetime.strptime(date_to, '%Y-%m-%d')
    except ValueError:
        date_to = ''
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    transactions = cached_transactions or []
    if cached_transactions is None:
        try:
            transactions.extend(_load_account_payment_transactions(owner_uid, account_id, sandbox, company_id, type_filter, date_from, date_to))
        except Exception as e:
            print(f"⚠️ Error al cargar pagos de facturas/CxP: {e}")
        try:
            expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, company_id=company_id)
            for exp in expenses:
                expense_date = str(exp.get('date', ''))[:10]
                if (type_filter not in ('', 'expense') or exp.get('bankAccountId') != account_id or (date_from and expense_date < date_from) or (date_to and expense_date > date_to)):
                    continue
                transactions.append({"date": expense_date, "type": "expense", "concept": f"Gasto: {exp.get('concept', '')}", "amount": -float(exp.get('amount', 0)), "reference": exp.get('ncf', '') or exp.get('ecfNumber', ''), "expenseId": exp.get('id', ''), "invoiceId": ''})
                if type_filter in ('', 'expense') and exp.get('id'):
                    for pmt in DatabaseService.get_cxp_payments(owner_uid, exp['id'], sandbox=sandbox, company_id=company_id):
                        payment_date = str(pmt.get('paymentDate', ''))[:10]
                        if pmt.get('bankAccountId') == account_id and (not date_from or payment_date >= date_from) and (not date_to or payment_date <= date_to):
                            transactions.append({"date": payment_date, "type": "expense", "concept": f"Pago CxP: {exp.get('concept', '')}", "amount": -float(pmt.get('amount', 0)), "reference": '', "expenseId": exp['id'], "invoiceId": ''})
        except Exception as e:
            print(f"⚠️ Error al cargar gastos directos: {e}")
        try:
            transfers = DatabaseService.get_bank_transfers(owner_uid, sandbox=sandbox, company_id=company_id)
            for t in transfers:
                t_date = str(t.get('date', ''))[:10]
                if (date_from and t_date < date_from) or (date_to and t_date > date_to): continue
                if t.get('fromAccountId') == account_id and type_filter in ('', 'transfer_out'):
                    transactions.append({"date": t_date, "type": "transfer_out", "concept": f"Transferencia enviada: {t.get('description', '')}", "amount": -float(t.get('amount', 0)), "reference": t.get('expenseNumbering', ''), "invoiceId": ''})
                elif t.get('toAccountId') == account_id and type_filter in ('', 'transfer_in'):
                    transactions.append({"date": t_date, "type": "transfer_in", "concept": f"Transferencia recibida: {t.get('description', '')}", "amount": float(t.get('amount', 0)), "reference": t.get('incomeNumbering', ''), "invoiceId": ''})
        except Exception as e:
            print(f"⚠️ Error al cargar transferencias: {e}")

        transactions.sort(key=lambda x: x.get('date', ''), reverse=True)
        CacheService.get_cache().set(cache_key, transactions, timeout=60)
    from app.services.bank_reconciliation_service import reconcile_account
    reconciliation = reconcile_account(account, transactions)
    account_reconciliations = DatabaseService.get_reconciliations(owner_uid, sandbox=sandbox, company_id=company_id)
    last_reconciliation = next((item for item in account_reconciliations if item.get("accountId") == account_id), None)
    adjustments = DatabaseService.get_bank_adjustments(
        owner_uid, account_id, sandbox=sandbox, company_id=company_id
    )
    ledger_movements = DatabaseService.get_bank_movements(
        owner_uid, account_id, sandbox=sandbox, company_id=company_id
    )
    unified_movements = []
    for movement in ledger_movements:
        amount = float(movement.get("amount", 0) or 0)
        unified_movements.append({
            "date": str(movement.get("createdAt", ""))[:10],
            "type": movement.get("sourceType", "movement"),
            "origin": movement.get("sourceType", "Movimiento"),
            "reference": movement.get("sourceId", ""),
            "description": movement.get("description", ""),
            "inflow": amount if amount > 0 else 0.0,
            "outflow": abs(amount) if amount < 0 else 0.0,
            "status": "Registrado",
            "source_id": movement.get("sourceId", ""),
            "document_url": "",
            "reversal_of": movement.get("reversalOf", ""),
        })
    registered_payment_keys = {
        (row.get("sourceType"), row.get("sourceId"))
        for row in ledger_movements
        if row.get("sourceType") == "invoice_payment" and row.get("sourceId")
    }
    for movement in transactions:
        payment_id = movement.get("paymentId")
        if payment_id and ("invoice_payment", payment_id) in registered_payment_keys:
            continue
        if any(
            row["reference"] == movement.get("reference")
            and row["date"] == movement.get("date")
            and abs((row.get("inflow", 0) - row.get("outflow", 0)) - movement.get("amount", 0)) < 0.01
            for row in unified_movements
        ):
            continue
        amount = float(movement.get("amount", 0) or 0)
        unified_movements.append({
            "date": movement.get("date", ""),
            "type": movement.get("type", "movement"),
            "origin": movement.get("type", "Movimiento"),
            "reference": movement.get("reference", ""),
            "description": movement.get("concept", ""),
            "inflow": amount if amount > 0 else 0.0,
            "outflow": abs(amount) if amount < 0 else 0.0,
            "status": "Pendiente de migración",
            "source_id": movement.get("reference", ""),
            "document_url": url_for("web_invoices.invoice_detail", invoice_id=movement.get("invoiceId")) if movement.get("invoiceId") else (url_for("web_invoices.expense_detail", expense_id=movement.get("expenseId")) if movement.get("expenseId") else ""),
            "reversal_of": "",
        })
    unified_movements.sort(key=lambda row: row.get("date", ""), reverse=True)
    if origin_filter:
        unified_movements = [row for row in unified_movements if origin_filter in row.get("origin", "").lower()]
    if movement_query:
        unified_movements = [row for row in unified_movements if movement_query in f"{row.get('description', '')} {row.get('reference', '')}".lower()]
    running_balance = float(account.get("initialBalance", 0.0) or 0.0)
    for movement in reversed(unified_movements):
        movement["balance"] = round(running_balance + movement["inflow"] - movement["outflow"], 2)
        running_balance = movement["balance"]
        movement["reconciliation_status"] = "Conciliable" if movement.get("status") == "Registrado" else "Pendiente"
    total_movements = len(unified_movements)
    total_pages = max(1, (total_movements + page_size - 1) // page_size)
    page = min(page, total_pages)
    visible_movements = unified_movements[(page - 1) * page_size:page * page_size]

    return render_template('banks/detail.html', active_page='banks',
                           account=account, account_types=ACCOUNT_TYPES,
                           transactions=transactions, adjustments=adjustments, ledger_movements=ledger_movements, unified_movements=visible_movements, reconciliation=reconciliation, last_reconciliation=last_reconciliation, type_filter=type_filter, page=page, total_pages=total_pages, total_movements=total_movements, quick_filter=quick_filter,
                           date_from=date_from, date_to=date_to, origin_filter=origin_filter, movement_query=movement_query)

@web_banks_bp.route('/banks/<account_id>/adjustment', methods=['POST'])
def bank_adjustment(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    try:
        amount = float(request.form.get('amount', 0))
        reason = request.form.get('reason', '')
        DatabaseService.save_bank_adjustment(
            session['user']['ownerUID'], account_id, amount, reason,
            sandbox=session.get('is_sandbox_mode', True),
            company_id=session.get('selected_company_id'),
            registered_by=session['user'].get('email', ''),
        )
        flash('Ajuste bancario registrado correctamente.', 'success')
    except (TypeError, ValueError) as exc:
        flash(f'No se pudo registrar el ajuste: {exc}', 'error')
    return redirect(url_for('web_banks.bank_detail', account_id=account_id))


@web_banks_bp.route('/banks/new', methods=['GET', 'POST'])
def new_bank():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        account_id = str(uuid.uuid4())
        account_dict = {
            "name": request.form['name'],
            "type": request.form['type'],
            "accountNumber": request.form.get('accountNumber', ''),
            "initialBalance": float(request.form.get('initialBalance', 0)),
            "balanceDate": request.form.get('balanceDate', ''),
            "description": request.form.get('description', ''),
            "creditLimit": float(request.form.get('creditLimit', 0)) if request.form.get('type') == 'tarjeta' else 0,
            "accountingAccountId": request.form.get('accountingAccountId', ''),
            "isDefaultIncome": request.form.get('isDefaultIncome') == 'on',
            "branchId": g.get('branch_id', 'default-sucursal-principal'),
            "projectId": g.get('project_id'),
        }
        DatabaseService.save_bank_account(owner_uid, account_id, account_dict, sandbox=sandbox, company_id=company_id)
        flash('Cuenta creada exitosamente.', 'success')
        return redirect(url_for('web_banks.list_banks'))

    AccountingService.seed_default_accounts(company_id)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid, company_id=company_id)
    return render_template('banks/form.html', active_page='banks',
                           account=None, account_types=ACCOUNT_TYPES,
                           accounting_accounts=accounting_accounts)

@web_banks_bp.route('/banks/<account_id>/edit', methods=['GET', 'POST'])
def edit_bank(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        account_dict = {
            "name": request.form['name'],
            "type": request.form['type'],
            "accountNumber": request.form.get('accountNumber', ''),
            "initialBalance": float(request.form.get('initialBalance', 0)),
            "balanceDate": request.form.get('balanceDate', ''),
            "description": request.form.get('description', ''),
            "creditLimit": float(request.form.get('creditLimit', 0)) if request.form.get('type') == 'tarjeta' else 0,
            "accountingAccountId": request.form.get('accountingAccountId', ''),
            "isDefaultIncome": request.form.get('isDefaultIncome') == 'on',
            "branchId": g.get('branch_id', 'default-sucursal-principal'),
            "projectId": g.get('project_id'),
        }
        existing = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
        if existing:
            account_dict["currentBalance"] = existing["currentBalance"]
            account_dict["createdAt"] = existing["createdAt"]
            account_dict["branchId"] = existing.get("branchId", account_dict["branchId"])
            account_dict["projectId"] = existing.get("projectId", account_dict["projectId"])
            account_dict["isDefaultIncome"] = account_dict.get("isDefaultIncome", existing.get("isDefaultIncome", False))
        DatabaseService.save_bank_account(owner_uid, account_id, account_dict, sandbox=sandbox, company_id=company_id)
        flash('Cuenta actualizada exitosamente.', 'success')
        return redirect(url_for('web_banks.list_banks'))

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    AccountingService.seed_default_accounts(company_id)
    accounting_accounts = DatabaseService.get_chart_of_accounts(owner_uid, company_id=company_id)
    return render_template('banks/form.html', active_page='banks',
                           account=account, account_types=ACCOUNT_TYPES,
                           accounting_accounts=accounting_accounts)

@web_banks_bp.route('/banks/<account_id>/delete', methods=['POST'])
def delete_bank(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    DatabaseService.delete_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    flash('Cuenta eliminada.', 'success')
    return redirect(url_for('web_banks.list_banks'))

@web_banks_bp.route('/banks/<account_id>/payment/new', methods=['GET', 'POST'])
def new_bank_payment(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not (check_permission('canManageBanks') or check_permission('canExpenses')):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    expenses = [e for e in DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id)
                if e.get('cxpStatus') in ('Pendiente', 'Abonado') and e.get('cxpRemainingBalance', 0) > 0]

    if request.method == 'POST':
        expense_id = request.form.get('expenseId', '')
        amount = float(request.form.get('amount', 0))
        concept = request.form.get('concept', '')
        ref_number = request.form.get('referenceNumber', '')

        if not expense_id or amount <= 0:
            flash('Selecciona un gasto e ingresa un monto válido.', 'error')
            return render_template('banks/payment_form.html', active_page='banks',
                                   account=account, account_types=ACCOUNT_TYPES,
                                   expenses=expenses, mode='expense')

        try:
            success, msg = DatabaseService.save_cxp_payment(owner_uid, expense_id, amount,
                                                            registered_by=session['user']['email'],
                                                            bank_account_id=account_id,
                                                            sandbox=sandbox,
                                                            company_id=company_id,
                                                            requested_by_uid=session['user'].get('uid', ''))
            if success:
                flash(f'✅ Pago registrado: RD$ {amount:,.2f} desde {account["name"]}. {msg}', 'success')
            else:
                flash(f'❌ {msg}', 'error')
                return render_template('banks/payment_form.html', active_page='banks',
                                       account=account, account_types=ACCOUNT_TYPES,
                                       expenses=expenses, mode='expense')
        except Exception as e:
            flash(f'❌ Error al registrar pago: {e}', 'error')
            return render_template('banks/payment_form.html', active_page='banks',
                                   account=account, account_types=ACCOUNT_TYPES,
                                   expenses=expenses, mode='expense')

        return redirect(url_for('web_banks.bank_detail', account_id=account_id))

    return render_template('banks/payment_form.html', active_page='banks',
                           account=account, account_types=ACCOUNT_TYPES,
                           expenses=expenses, mode='expense')


@web_banks_bp.route('/banks/<account_id>/payment/receive', methods=['GET', 'POST'])
def new_bank_receipt(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not (check_permission('canManageBanks') or check_permission('canManageCXC')):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    invoices = [inv for inv in DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
                if inv.get('status') in ('Emitida', 'Parcialmente Cobrada', 'Vencida')
                and inv.get('remainingBalance', 0) > 0
                and not inv.get('isQuotation')
                and inv.get('dgiiStatus') not in ('REJECTED', 'RECHAZADO')]

    if request.method == 'POST':
        invoice_id = request.form.get('invoiceId', '')
        amount = float(request.form.get('amount', 0))
        ref_number = request.form.get('referenceNumber', '')
        payment_method = request.form.get('paymentMethod', 'transferencia')

        if not invoice_id or amount <= 0:
            flash('Selecciona una factura e ingresa un monto válido.', 'error')
            return render_template('banks/payment_form.html', active_page='banks',
                                   account=account, account_types=ACCOUNT_TYPES,
                                   invoices=invoices, mode='income')

        try:
            payment_dict = {
                "paymentMethod": payment_method,
                "bank": account['name'],
                "referenceNumber": ref_number,
                "amount": amount,
                "paymentDate": datetime.now(timezone.utc).isoformat(),
                "registeredBy": session['user']['email'],
                "bankAccountId": account_id
            }
            DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox, company_id=company_id)
            flash(f'✅ Pago recibido: RD$ {amount:,.2f} depositado en {account["name"]}.', 'success')
        except Exception as e:
            flash(f'❌ Error al registrar pago recibido: {e}', 'error')
            return render_template('banks/payment_form.html', active_page='banks',
                                   account=account, account_types=ACCOUNT_TYPES,
                                   invoices=invoices, mode='income')

        return redirect(url_for('web_banks.bank_detail', account_id=account_id))

    return render_template('banks/payment_form.html', active_page='banks',
                           account=account, account_types=ACCOUNT_TYPES,
                           invoices=invoices, mode='income')


@web_banks_bp.route('/banks/transfer', methods=['GET', 'POST'])
def new_transfer():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canManageBanks'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canManageBanks"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox, company_id=company_id)

    if request.method == 'POST':
        from_account_id = request.form['fromAccountId']
        to_account_id = request.form['toAccountId']
        amount = float(request.form.get('amount', 0))

        if from_account_id == to_account_id:
            flash('La cuenta de origen y destino deben ser diferentes.', 'error')
            return render_template('banks/transfer.html', active_page='banks',
                                   accounts=accounts, account_types=ACCOUNT_TYPES)

        if amount <= 0:
            flash('El monto debe ser mayor a cero.', 'error')
            return render_template('banks/transfer.html', active_page='banks',
                                   accounts=accounts, account_types=ACCOUNT_TYPES)

        transfer_id = str(uuid.uuid4())
        transfer_dict = {
            "fromAccountId": from_account_id,
            "toAccountId": to_account_id,
            "amount": amount,
            "date": request.form.get('date', ''),
            "description": request.form.get('description', ''),
            "incomeNumbering": request.form.get('incomeNumbering', ''),
            "expenseNumbering": request.form.get('expenseNumbering', '')
        }
        DatabaseService.save_bank_transfer(owner_uid, transfer_id, transfer_dict, sandbox=sandbox, company_id=company_id)
        flash('Transferencia realizada exitosamente.', 'success')
        return redirect(url_for('web_banks.list_banks'))

    return render_template('banks/transfer.html', active_page='banks',
                           accounts=accounts, account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/data')
def banks_data():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not check_permission('canManageBanks'):
        return jsonify({"error": "Forbidden"}), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    summary = DatabaseService.get_bank_summary(owner_uid, sandbox=sandbox, company_id=company_id)
    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox, company_id=company_id)

    return jsonify({
        "summary": summary,
        "accounts": accounts
    })

@web_banks_bp.route('/banks/reconcile')
def reconcile_list():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canBankReconciliation'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canBankReconciliation"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox, company_id=company_id)
    reconciliations = DatabaseService.get_reconciliations(owner_uid, sandbox=sandbox, company_id=company_id)
    last_by_account = {}
    for reconciliation in reconciliations:
        current = last_by_account.get(reconciliation.get("accountId"))
        if not current or reconciliation.get("createdAt", "") > current.get("createdAt", ""):
            last_by_account[reconciliation.get("accountId")] = reconciliation

    return render_template('banks/reconcile_list.html', active_page='bank_reconcile',
                           accounts=accounts, reconciliations=reconciliations, last_by_account=last_by_account,
                           account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/reconcile/<account_id>/new', methods=['GET', 'POST'])
def reconcile_new(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canBankReconciliation'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canBankReconciliation"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.reconcile_list'))

    if request.method == 'POST':
        start_date = request.form.get('startDate', '')
        end_date = request.form.get('endDate', '')
        end_balance = float(request.form.get('endBalance', 0))

        try:
            from datetime import datetime as _dt
            _dt.strptime(start_date, '%Y-%m-%d')
            _dt.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            flash('Fechas inválidas.', 'error')
            return render_template('banks/reconcile_new.html', active_page='bank_reconcile',
                                   account=account, account_types=ACCOUNT_TYPES)

        initial_balance = float(request.form.get('initialBalance', account['currentBalance']))

        recon_id = str(uuid.uuid4())
        recon_dict = {
            "accountId": account_id,
            "accountName": account['name'],
            "accountType": account['type'],
            "startDate": start_date,
            "endDate": end_date,
            "startBalance": initial_balance,
            "endBalance": end_balance,
            "calculatedBalance": initial_balance,
            "difference": end_balance - initial_balance,
            "status": "en_curso",
            "transactions": [],
            "transactionCount": 0,
            "reconciledCount": 0,
            "status": "pendiente",
        }

        # Auto-poblar transacciones del período (pagos recibidos en esta cuenta)
        try:
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
            for inv in invoices:
                inv_payments = DatabaseService.get_invoice_payments(owner_uid, inv.get('id'), sandbox=sandbox, company_id=company_id)
                for pmt in inv_payments:
                    pmt_date = str(pmt.get('paymentDate', ''))[:10]
                    if pmt.get('bankAccountId') == account_id and start_date <= pmt_date <= end_date:
                        recon_dict["transactions"].append({
                            "id": str(uuid.uuid4()),
                            "type": "income",
                            "description": f"Pago {inv.get('invoiceNumber', '')} — {inv.get('clientName', '')}",
                            "amount": float(pmt.get('amount', 0)),
                            "date": pmt_date,
                            "source": "payment",
                            "referenceId": inv.get('id', ''),
                            "referenceNumber": pmt.get('referenceNumber', ''),
                            "reconciled": False
                        })

            # Transferencias recibidas
            transfers = DatabaseService.get_bank_transfers(owner_uid, sandbox=sandbox, company_id=company_id)
            for t in transfers:
                t_date = str(t.get('date', ''))[:10]
                if start_date <= t_date <= end_date:
                    if t.get('toAccountId') == account_id:
                        recon_dict["transactions"].append({
                            "id": str(uuid.uuid4()),
                            "type": "income",
                            "description": f"Transferencia recibida: {t.get('description', '')}",
                            "amount": float(t.get('amount', 0)),
                            "date": t_date,
                            "source": "transfer_in",
                            "referenceId": t.get('id', ''),
                            "reconciled": False
                        })
                    elif t.get('fromAccountId') == account_id:
                        recon_dict["transactions"].append({
                            "id": str(uuid.uuid4()),
                            "type": "expense",
                            "description": f"Transferencia enviada: {t.get('description', '')}",
                            "amount": float(t.get('amount', 0)),
                            "date": t_date,
                            "source": "transfer_out",
                            "referenceId": t.get('id', ''),
                            "reconciled": False
                        })

            recon_dict["transactions"].sort(key=lambda x: x["date"])
            recon_dict["transactionCount"] = len(recon_dict["transactions"])

            total_income = sum(t["amount"] for t in recon_dict["transactions"] if t["type"] == "income")
            total_expense = sum(t["amount"] for t in recon_dict["transactions"] if t["type"] == "expense")
            recon_dict["calculatedBalance"] = round(initial_balance + total_income - total_expense, 2)
            recon_dict["difference"] = round(end_balance - recon_dict["calculatedBalance"], 2)
        except Exception as e:
            print(f"⚠️ Error al poblar transacciones: {e}")

        DatabaseService.save_reconciliation(owner_uid, recon_id, recon_dict, sandbox=sandbox, company_id=company_id)
        flash('Conciliación creada. Revisa y marca las transacciones que coinciden con tu estado de cuenta.', 'success')
        return redirect(url_for('web_banks.reconcile_detail', recon_id=recon_id))

    return render_template('banks/reconcile_new.html', active_page='bank_reconcile',
                           account=account, account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/reconcile/<recon_id>')
def reconcile_detail(recon_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canBankReconciliation'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canBankReconciliation"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox, company_id=company_id)
    if not recon:
        flash('Conciliación no encontrada.', 'error')
        return redirect(url_for('web_banks.reconcile_list'))

    return render_template('banks/reconcile_detail.html', active_page='bank_reconcile',
                           recon=recon)

@web_banks_bp.route('/banks/reconcile/<recon_id>/toggle', methods=['POST'])
def reconcile_toggle(recon_id):
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if not check_permission('canBankReconciliation'):
        return jsonify({"error": "Forbidden"}), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    tx_id = request.form.get('transactionId', '')
    if not tx_id:
        return jsonify({"error": "transactionId required"}), 400

    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox, company_id=company_id)
    if not recon:
        return jsonify({"error": "Not found"}), 404

    for tx in recon.get("transactions", []):
        if tx.get("id") == tx_id:
            tx["reconciled"] = not tx["reconciled"]
            break

    reconciled_count = sum(1 for t in recon["transactions"] if t.get("reconciled"))
    recon["reconciledCount"] = reconciled_count

    if reconciled_count == recon.get("transactionCount", 0) and recon["transactionCount"] > 0:
        recon["status"] = "conciliada"
    elif reconciled_count > 0:
        recon["status"] = "en_curso"
    else:
        recon["status"] = "pendiente"

    DatabaseService.save_reconciliation(owner_uid, recon_id, recon, sandbox=sandbox, company_id=company_id)
    return jsonify({"success": True, "reconciled": tx_id, "reconciledCount": reconciled_count, "status": recon["status"]})

@web_banks_bp.route('/banks/reconcile/<recon_id>/complete', methods=['POST'])
def reconcile_complete(recon_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canBankReconciliation'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canBankReconciliation"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    user = session.get('user', {})

    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox, company_id=company_id)
    if not recon:
        flash('Conciliación no encontrada.', 'error')
        return redirect(url_for('web_banks.reconcile_list'))

    diff = recon.get("difference", 0.0)

    if diff == 0.0:
        recon["status"] = "conciliada"
        flash('¡Conciliación completada con éxito! El saldo cuadra perfectamente.', 'success')
    else:
        recon["status"] = "con_diferencias"
        flash(f'Conciliación marcada como completada con una diferencia de RD$ {diff:,.2f}. Revisa las discrepancias.', 'warning')

    DatabaseService.save_reconciliation(owner_uid, recon_id, recon, sandbox=sandbox, company_id=company_id)

    if abs(diff) > 0.01:
        try:
            from app.services.accounting_service import AccountingService, _find_account_by_usage, _find_account_by_usages
            from app.services.db_service import DatabaseService as DBS
            DBSr = DatabaseService
            accounts_list = DBSr.get_chart_of_accounts(owner_uid)
            diff_account = next((a for a in accounts_list if a.get("code") == "6.4.03"), None) or \
                           _find_account_by_usage(accounts_list, "ajuste_inventario") or \
                           next((a for a in accounts_list if "ajuste" in (a.get("name") or "").lower()), None)
            bank_account = _find_account_by_usage(accounts_list, "banco") or \
                           _find_account_by_usages(accounts_list, ["banco", "efectivo"])
            if diff_account and bank_account:
                lines = []
                if diff > 0:
                    lines.append({
                        "accountId": bank_account.get("id"), "accountCode": bank_account.get("code", ""),
                        "accountName": bank_account.get("name", "Banco"),
                        "debit": round(diff, 2), "credit": 0.00,
                        "description": f"Ajuste por conciliación bancaria — diferencia positiva"
                    })
                    lines.append({
                        "accountId": diff_account.get("id"), "accountCode": diff_account.get("code", ""),
                        "accountName": diff_account.get("name", "Ajuste conciliación"),
                        "debit": 0.00, "credit": round(diff, 2),
                        "description": f"Conciliación {recon.get('accountName', '')} — {recon_id}"
                    })
                else:
                    lines.append({
                        "accountId": diff_account.get("id"), "accountCode": diff_account.get("code", ""),
                        "accountName": diff_account.get("name", "Ajuste conciliación"),
                        "debit": round(abs(diff), 2), "credit": 0.00,
                        "description": f"Ajuste por conciliación bancaria — diferencia negativa"
                    })
                    lines.append({
                        "accountId": bank_account.get("id"), "accountCode": bank_account.get("code", ""),
                        "accountName": bank_account.get("name", "Banco"),
                        "debit": 0.00, "credit": round(abs(diff), 2),
                        "description": f"Conciliación {recon.get('accountName', '')} — {recon_id}"
                    })
                AccountingService.generate_entry(company_id, {
                    "entryType": "adjustment",
                    "date": recon.get("endDate", ""),
                    "concept": f"Ajuste por conciliación bancaria de {recon.get('accountName', '')} — diferencia RD$ {abs(diff):,.2f}",
                    "referenceType": "bank_reconciliation",
                    "referenceId": recon_id,
                    "referenceNumber": recon.get("accountName", ""),
                    "lines": lines,
                    "createdBy": user.get("email", "system"),
                }, sandbox=sandbox)
                flash('Asiento de ajuste por diferencia de conciliación generado automáticamente.', 'info')
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error generando asiento de conciliación: {e}")

    return redirect(url_for('web_banks.reconcile_detail', recon_id=recon_id))

@web_banks_bp.route('/banks/reconcile/<recon_id>/delete', methods=['POST'])
def reconcile_delete(recon_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canBankReconciliation'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canBankReconciliation"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    DatabaseService.delete_reconciliation(owner_uid, recon_id, sandbox=sandbox, company_id=company_id)
    flash('Conciliación eliminada.', 'success')
    return redirect(url_for('web_banks.reconcile_list'))


@web_banks_bp.route('/banks/reconcile/<account_id>/import-statement', methods=['GET', 'POST'])
def import_bank_statement(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canBankReconciliation'):
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox, company_id=company_id)
    if not account:
        flash('Cuenta bancaria no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    if request.method == 'POST':
        file = request.files.get('statement_file')
        bank = request.form.get('bank', 'generic')
        if not file:
            flash('Selecciona un archivo CSV.', 'error')
            return render_template('banks/import_statement.html', account=account, active_page='bancos')

        from app.services.bank_statement_parser import BankStatementParser
        try:
            content = file.read()
            filename = file.filename or ""
            statement_txns = BankStatementParser.parse_file(content, bank=bank, filename=filename)

            book_txns = []
            try:
                trans_type = request.form.get('transaction_type', 'invoice_payments')
                if trans_type == 'invoice_payments':
                    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
                    for inv in invoices:
                        if inv.get('status') in ['Pagado', 'Parcialmente Cobrada']:
                            payments = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox, company_id=company_id)
                            for p in payments:
                                book_txns.append({
                                    "id": f"invpay_{p['id']}",
                                    "date": p.get('paymentDate', ''),
                                    "description": f"Pago factura {inv.get('invoiceNumber','')} - {inv.get('clientName','')}",
                                    "amount": float(p.get('amount', 0)),
                                    "type": "income",
                                })
                elif trans_type == 'expense_payments':
                    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id)
                    for exp in expenses:
                        cxp_payments = DatabaseService.get_cxp_payments(owner_uid, exp['id'], sandbox=sandbox, company_id=company_id)
                        for p in cxp_payments:
                            book_txns.append({
                                "id": f"cxppay_{p['id']}",
                                "date": p.get('paymentDate', ''),
                                "description": f"Pago gasto - {exp.get('concept','')}",
                                "amount": float(p.get('amount', 0)),
                                "type": "expense",
                            })
            except Exception:
                pass

            results = BankStatementParser.auto_match(statement_txns, book_txns)

            return render_template('banks/import_statement.html', account=account,
                                  active_page='bancos', results=results,
                                  statement_count=len(statement_txns),
                                  matched_count=sum(1 for r in results if r.get('matched')),
                                  bank=bank)
        except Exception as e:
            flash(f'Error al procesar archivo: {str(e)}', 'error')

    return render_template('banks/import_statement.html', account=account, active_page='bancos')


@web_banks_bp.route('/banks/reconcile/<recon_id>/auto-match', methods=['POST'])
def auto_match_reconciliation(recon_id):
    if 'user' not in session:
        return jsonify(success=False, error="No autenticado"), 401
    if not check_permission('canBankReconciliation'):
        return jsonify(success=False, error="Forbidden"), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox, company_id=company_id)
    if not recon:
        return jsonify(success=False, error="Conciliación no encontrada"), 404

    for txn in recon.get("transactions", []):
        txn["reconciled"] = True
    recon["reconciledCount"] = len(recon.get("transactions", []))
    recon["status"] = "conciliada" if abs(recon.get("difference", 0)) < 0.01 else "con_diferencias"

    from app.services.db_service import db_firestore
    recon_path = "sandbox_bank_reconciliations" if sandbox else "bank_reconciliations"
    db_firestore.collection("users").document(owner_uid).collection(recon_path).document(recon_id).set(recon)
    return jsonify(success=True)


@web_banks_bp.route('/banks/payment-calendar')
def payment_calendar():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not (check_permission('canManageBanks') or check_permission('canExpenses') or check_permission('canManageCXC') or check_permission('canManagePurchaseCXP')):
        return render_template('auth/restricted.html', feature_name="Calendario de Pagos", required_permission="canManageBanks"), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    try:
        days = int(request.args.get('days', 60))
    except ValueError:
        days = 60

    try:
        from app.services.payment_scheduler_service import PaymentSchedulerService
        payments = PaymentSchedulerService.get_payment_calendar(owner_uid, sandbox=sandbox, days_ahead=days)
        stats = PaymentSchedulerService.get_calendar_stats(owner_uid, sandbox=sandbox)
        plan = PaymentSchedulerService.suggest_payment_plan(owner_uid, sandbox=sandbox)
    except Exception as e:
        flash(f'Error al generar calendario: {str(e)}', 'error')
        payments = []
        stats = {}
        plan = None

    # Convert dataclasses to dicts for template
    payments_dicts = [
        {"expense_id": p.expense_id, "concept": p.concept, "supplier_name": p.supplier_name,
         "supplier_rnc": p.supplier_rnc, "due_date": p.due_date, "amount": p.amount,
         "remaining": p.remaining, "days_overdue": p.days_overdue, "priority": p.priority,
         "suggested_pay_date": p.suggested_pay_date, "category": p.category, "cxp_status": p.cxp_status}
        for p in payments
    ]

    plan_dict = None
    if plan:
        plan_dict = {
            "total_to_pay": plan.total_to_pay,
            "available_balance": plan.available_balance,
            "remaining_after_plan": plan.remaining_after_plan,
            "coverage_pct": plan.coverage_pct,
            "uncovered_amount": plan.uncovered_amount,
            "uncovered_count": plan.uncovered_count,
            "payments": [
                {"concept": pp.concept, "supplier_name": pp.supplier_name,
                 "amount": pp.amount, "priority": pp.priority, "due_date": pp.due_date}
                for pp in plan.payments
            ]
        }

    return render_template(
        'banks/payment_calendar.html',
        active_page='bank_payment_calendar',
        payments=payments_dicts,
        stats=stats,
        plan=plan_dict,
        days=days,
    )
