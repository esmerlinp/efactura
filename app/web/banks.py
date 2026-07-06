import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.utils.decorators import check_permission
from app.utils.module_gate import module_enabled

web_banks_bp = Blueprint('web_banks', __name__)

ACCOUNT_TYPES = {
    "banco": "Banco",
    "efectivo": "Efectivo",
    "tarjeta": "Tarjeta de crédito"
}

@web_banks_bp.route('/banks')
def list_banks():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    summary = DatabaseService.get_bank_summary(owner_uid, sandbox=sandbox)

    return render_template('banks/list.html', active_page='banks',
                           accounts=accounts, summary=summary,
                           account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/<account_id>')
def bank_detail(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    transactions = []
    try:
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
        for inv in invoices:
            inv_payments = DatabaseService.get_invoice_payments(owner_uid, inv.get('id'), sandbox=sandbox)
            for pmt in inv_payments:
                if pmt.get('bankAccountId') == account_id:
                    transactions.append({
                        "date": str(pmt.get('paymentDate', ''))[:10],
                        "type": "income",
                        "concept": f"Pago {inv.get('invoiceNumber', '')} — {inv.get('clientName', '')}",
                        "amount": float(pmt.get('amount', 0)),
                        "reference": pmt.get('referenceNumber', ''),
                        "invoiceId": inv.get('id', '')
                    })
    except Exception as e:
        print(f"⚠️ Error al cargar pagos de facturas: {e}")

    try:
        transfers = DatabaseService.get_bank_transfers(owner_uid, sandbox=sandbox)
        for t in transfers:
            t_date = str(t.get('date', ''))[:10]
            if t.get('fromAccountId') == account_id:
                transactions.append({
                    "date": t_date,
                    "type": "transfer_out",
                    "concept": f"Transferencia enviada: {t.get('description', '')}",
                    "amount": -float(t.get('amount', 0)),
                    "reference": t.get('expenseNumbering', ''),
                    "invoiceId": ''
                })
            elif t.get('toAccountId') == account_id:
                transactions.append({
                    "date": t_date,
                    "type": "transfer_in",
                    "concept": f"Transferencia recibida: {t.get('description', '')}",
                    "amount": float(t.get('amount', 0)),
                    "reference": t.get('incomeNumbering', ''),
                    "invoiceId": ''
                })
    except Exception as e:
        print(f"⚠️ Error al cargar transferencias: {e}")

    transactions.sort(key=lambda x: x.get('date', ''), reverse=True)

    return render_template('banks/detail.html', active_page='banks',
                           account=account, account_types=ACCOUNT_TYPES,
                           transactions=transactions)


@web_banks_bp.route('/banks/new', methods=['GET', 'POST'])
def new_bank():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
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
            "creditLimit": float(request.form.get('creditLimit', 0)) if request.form.get('type') == 'tarjeta' else 0
        }
        DatabaseService.save_bank_account(owner_uid, account_id, account_dict, sandbox=sandbox)
        flash('Cuenta creada exitosamente.', 'success')
        return redirect(url_for('web_banks.list_banks'))

    return render_template('banks/form.html', active_page='banks',
                           account=None, account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/<account_id>/edit', methods=['GET', 'POST'])
def edit_bank(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    if request.method == 'POST':
        account_dict = {
            "name": request.form['name'],
            "type": request.form['type'],
            "accountNumber": request.form.get('accountNumber', ''),
            "initialBalance": float(request.form.get('initialBalance', 0)),
            "balanceDate": request.form.get('balanceDate', ''),
            "description": request.form.get('description', ''),
            "creditLimit": float(request.form.get('creditLimit', 0)) if request.form.get('type') == 'tarjeta' else 0
        }
        existing = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
        if existing:
            account_dict["currentBalance"] = existing["currentBalance"]
            account_dict["createdAt"] = existing["createdAt"]
        DatabaseService.save_bank_account(owner_uid, account_id, account_dict, sandbox=sandbox)
        flash('Cuenta actualizada exitosamente.', 'success')
        return redirect(url_for('web_banks.list_banks'))

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    return render_template('banks/form.html', active_page='banks',
                           account=account, account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/<account_id>/delete', methods=['POST'])
def delete_bank(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    DatabaseService.delete_bank_account(owner_uid, account_id, sandbox=sandbox)
    flash('Cuenta eliminada.', 'success')
    return redirect(url_for('web_banks.list_banks'))

@web_banks_bp.route('/banks/<account_id>/payment/new', methods=['GET', 'POST'])
def new_bank_payment(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    expenses = [e for e in DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
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
                                                            sandbox=sandbox)
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
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
    if not account:
        flash('Cuenta no encontrada.', 'error')
        return redirect(url_for('web_banks.list_banks'))

    invoices = [inv for inv in DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
                if inv.get('status') in ('Emitida', 'Parcialmente Cobrada', 'Vencida')
                and inv.get('remainingBalance', 0) > 0
                and not inv.get('isQuotation')]

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
            DatabaseService.register_invoice_payment(owner_uid, invoice_id, payment_dict, sandbox=sandbox)
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
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Bancos", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)

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
        DatabaseService.save_bank_transfer(owner_uid, transfer_id, transfer_dict, sandbox=sandbox)
        flash('Transferencia realizada exitosamente.', 'success')
        return redirect(url_for('web_banks.list_banks'))

    return render_template('banks/transfer.html', active_page='banks',
                           accounts=accounts, account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/data')
def banks_data():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    summary = DatabaseService.get_bank_summary(owner_uid, sandbox=sandbox)
    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)

    return jsonify({
        "summary": summary,
        "accounts": accounts
    })

@web_banks_bp.route('/banks/reconcile')
def reconcile_list():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    accounts = DatabaseService.get_bank_accounts(owner_uid, sandbox=sandbox)
    reconciliations = DatabaseService.get_reconciliations(owner_uid, sandbox=sandbox)

    return render_template('banks/reconcile_list.html', active_page='bank_reconcile',
                           accounts=accounts, reconciliations=reconciliations,
                           account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/reconcile/<account_id>/new', methods=['GET', 'POST'])
def reconcile_new(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
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
            "reconciledCount": 0
        }

        # Auto-poblar transacciones del período (pagos recibidos en esta cuenta)
        try:
            invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
            for inv in invoices:
                inv_payments = DatabaseService.get_invoice_payments(owner_uid, inv.get('id'), sandbox=sandbox)
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
            transfers = DatabaseService.get_bank_transfers(owner_uid, sandbox=sandbox)
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

        DatabaseService.save_reconciliation(owner_uid, recon_id, recon_dict, sandbox=sandbox)
        flash('Conciliación creada. Revisa y marca las transacciones que coinciden con tu estado de cuenta.', 'success')
        return redirect(url_for('web_banks.reconcile_detail', recon_id=recon_id))

    return render_template('banks/reconcile_new.html', active_page='bank_reconcile',
                           account=account, account_types=ACCOUNT_TYPES)

@web_banks_bp.route('/banks/reconcile/<recon_id>')
def reconcile_detail(recon_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox)
    if not recon:
        flash('Conciliación no encontrada.', 'error')
        return redirect(url_for('web_banks.reconcile_list'))

    return render_template('banks/reconcile_detail.html', active_page='bank_reconcile',
                           recon=recon)

@web_banks_bp.route('/banks/reconcile/<recon_id>/toggle', methods=['POST'])
def reconcile_toggle(recon_id):
    if 'user' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    tx_id = request.form.get('transactionId', '')
    if not tx_id:
        return jsonify({"error": "transactionId required"}), 400

    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox)
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

    DatabaseService.save_reconciliation(owner_uid, recon_id, recon, sandbox=sandbox)
    return jsonify({"success": True, "reconciled": tx_id, "reconciledCount": reconciled_count, "status": recon["status"]})

@web_banks_bp.route('/banks/reconcile/<recon_id>/complete', methods=['POST'])
def reconcile_complete(recon_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox)
    if not recon:
        flash('Conciliación no encontrada.', 'error')
        return redirect(url_for('web_banks.reconcile_list'))

    if recon.get("difference", 0) == 0.0:
        recon["status"] = "conciliada"
        flash('¡Conciliación completada con éxito! El saldo cuadra perfectamente.', 'success')
    else:
        recon["status"] = "con_diferencias"
        flash(f'Conciliación marcada como completada con una diferencia de RD$ {recon["difference"]:,.2f}. Revisa las discrepancias.', 'warning')

    DatabaseService.save_reconciliation(owner_uid, recon_id, recon, sandbox=sandbox)
    return redirect(url_for('web_banks.reconcile_detail', recon_id=recon_id))

@web_banks_bp.route('/banks/reconcile/<recon_id>/delete', methods=['POST'])
def reconcile_delete(recon_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        return render_template('auth/restricted.html', feature_name="Conciliación Bancaria", required_permission="canExpenses")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    DatabaseService.delete_reconciliation(owner_uid, recon_id, sandbox=sandbox)
    flash('Conciliación eliminada.', 'success')
    return redirect(url_for('web_banks.reconcile_list'))


@web_banks_bp.route('/banks/reconcile/<account_id>/import-statement', methods=['GET', 'POST'])
def import_bank_statement(account_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canExpenses'):
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    account = DatabaseService.get_bank_account(owner_uid, account_id, sandbox=sandbox)
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
            statement_txns = BankStatementParser.parse_csv(content, bank=bank)

            book_txns = []
            try:
                trans_type = request.form.get('transaction_type', 'invoice_payments')
                if trans_type == 'invoice_payments':
                    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
                    for inv in invoices:
                        if inv.get('status') in ['Pagado', 'Parcialmente Cobrada']:
                            payments = DatabaseService.get_invoice_payments(owner_uid, inv['id'], sandbox=sandbox)
                            for p in payments:
                                book_txns.append({
                                    "id": f"invpay_{p['id']}",
                                    "date": p.get('paymentDate', ''),
                                    "description": f"Pago factura {inv.get('invoiceNumber','')} - {inv.get('clientName','')}",
                                    "amount": float(p.get('amount', 0)),
                                    "type": "income",
                                })
                elif trans_type == 'expense_payments':
                    expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
                    for exp in expenses:
                        cxp_payments = DatabaseService.get_cxp_payments(owner_uid, exp['id'], sandbox=sandbox)
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
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    recon = DatabaseService.get_reconciliation(owner_uid, recon_id, sandbox=sandbox)
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

