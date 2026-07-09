import uuid
import json
import csv
import io
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file, make_response
from app.services.db_service import DatabaseService
from app.services.accounting_service import AccountingService, ACCOUNT_GROUPS

USAGE_LABELS = {
    "efectivo": "Bancos tipo efectivo",
    "banco": "Bancos tipo bancos",
    "cxc": "Cuentas por cobrar",
    "cxp": "Cuentas por pagar",
    "itbis_pagar": "Impuesto por pagar",
    "itbis_retenido": "Retenciones por pagar",
    "isr_retenido": "Retenciones por pagar",
    "itbis_credito": "Impuesto a favor",
    "inventario": "Inventario",
    "ventas": "Ventas",
    "compras": "Costo de la mercancía vendida",
    "depreciacion": "Depreciación",
    "depreciacion_acumulada": "Depreciación acumulada",
    "capital": "Capital social",
    "ppye": "Propiedad, planta y equipo",
    "impuesto_a_favor": "Impuesto a favor",
    "otro_impuesto_a_favor": "Otro tipo de impuesto a favor",
    "retenciones_a_favor": "Retenciones a favor",
    "otro_retencion_a_favor": "Otro tipo de retención a favor",
    "anticipos_entregados": "Anticipos entregados",
    "devoluciones_proveedores": "Devoluciones a proveedores",
    "anticipos_recibidos": "Anticipos recibidos",
    "devoluciones_clientes": "Devoluciones de clientes",
    "pasivos_nomina": "Pasivos por nómina",
    "tarjeta_credito": "Bancos tipo tarjeta de crédito",
    "impuesto_por_pagar": "Impuesto por pagar",
    "otro_impuesto_por_pagar": "Otro tipo de impuesto por pagar",
    "retenciones_por_pagar": "Retenciones por pagar",
    "otra_retencion_por_pagar": "Otro tipo de retención por pagar",
    "costo_ventas": "Costo de la mercancía vendida",
    "descuentos_financieros": "Descuentos financieros",
    "gastos_nomina": "Gastos de nómina",
    "gastos": "Gastos generales",
    "costo_ventas": "Costo de ventas",
    "cuentas_incobrables": "Cuentas incobrables",
    "impuestos_no_acreditables": "Impuestos no acreditables",
    "retencion_asumida": "Retención asumida sobre renta",
    "transferencias_bancarias": "Transferencias bancarias",
}

def _flatten_tree(tree_nodes, accounts_list):
    result = []
    for node in tree_nodes:
        node_id = node.get("id")
        if not node_id:
            if node.get("children"):
                result.extend(_flatten_tree(node["children"], accounts_list))
            continue
        result.append({
            "id": node_id,
            "code": node.get("code"),
            "name": node.get("name"),
            "level": node.get("level", 0),
            "group": node.get("group"),
            "type": node.get("type"),
            "nature": node.get("nature"),
            "usage": node.get("usage"),
            "usage_label": USAGE_LABELS.get(node.get("usage")),
            "description": node.get("description", ""),
            "isSystem": node.get("isSystem", False),
            "parentId": node.get("parentId"),
            "has_children": node.get("has_children", False),
        })
        if node.get("has_children") and node.get("children"):
            result.extend(_flatten_tree(node["children"], accounts_list))
    return result
from app.services.fixed_asset_service import FixedAssetService, ASSET_CATEGORIES
from app.utils.decorators import check_permission
from app.utils.module_gate import require_module

web_accounting_bp = Blueprint('web_accounting', __name__)


# =========================================================================
# HELPER
# =========================================================================
def _auth():
    if 'user' not in session:
        return None
    return session['user']


def _owner_uid():
    return session['user']['ownerUID']


def _sandbox():
    return session.get('is_sandbox_mode', True)


# =========================================================================
# DASHBOARD CONTABLE
# =========================================================================
@web_accounting_bp.route('/accounting')
@require_module('contabilidad')
def dashboard():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    AccountingService.seed_default_entry_types(owner_uid)
    tree, accounts = AccountingService.get_accounts_tree(owner_uid)
    # Obtener entradas UNA sola vez y pasarlas a todos los reportes
    entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
    active_entries = [e for e in entries if e.get("status") != "voided"]
    balance = AccountingService.get_balance_sheet(owner_uid, accounts=accounts, entries=entries)
    income = AccountingService.get_income_statement(owner_uid, accounts=accounts, entries=entries)
    trial = AccountingService.get_trial_balance(owner_uid, accounts=accounts, entries=entries)
    total_assets = balance["activos"]["total"]
    total_liabilities = balance["pasivos"]["total"]
    total_equity = balance["patrimonio"]["total"]
    net_income = income.get("netIncome", 0)
    return render_template('accounting/dashboard.html',
                           active_page='acc_dashboard',
                           total_assets=total_assets,
                           total_liabilities=total_liabilities,
                           total_equity=total_equity,
                           net_income=net_income,
                           entries_count=len(active_entries),
                           accounts_count=len(accounts),
                           trial=trial)


# =========================================================================
# CATÁLOGO DE CUENTAS
# =========================================================================
@web_accounting_bp.route('/accounting/chart-of-accounts')
@require_module('contabilidad')
def chart_of_accounts():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    tree_data, all_accounts = AccountingService.get_accounts_tree(owner_uid)
    account_groups = ACCOUNT_GROUPS
    flat_list = _flatten_tree(tree_data, all_accounts)
    return render_template('accounting/chart_of_accounts.html',
                           active_page='acc_chart',
                           tree=tree_data,
                           accounts=all_accounts,
                           flat_list=flat_list,
                           account_groups=account_groups,
                           groups_json=json.dumps({k: v["label"] for k, v in ACCOUNT_GROUPS.items()}))


@web_accounting_bp.route('/accounting/api/accounts')
@require_module('contabilidad')
def api_accounts():
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = _owner_uid()
    AccountingService.seed_default_accounts(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    return jsonify(success=True, accounts=accounts)


@web_accounting_bp.route('/accounting/api/accounts/tree')
@require_module('contabilidad')
def api_accounts_tree():
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = _owner_uid()
    AccountingService.seed_default_accounts(owner_uid)
    tree, accounts = AccountingService.get_accounts_tree(owner_uid)
    return jsonify(success=True, tree=tree)


@web_accounting_bp.route('/accounting/account/new', methods=['POST'])
@require_module('contabilidad')
def create_account():
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    account_id = str(uuid.uuid4())
    parent_id = request.form.get('parentId') or None
    group = request.form.get('group', 'activos')
    now = datetime.now(timezone.utc).isoformat()
    account = {
        "id": account_id,
        "code": request.form.get('code', '').strip(),
        "name": request.form.get('name', '').strip(),
        "type": request.form.get('type', 'movimiento'),
        "nature": request.form.get('nature', ACCOUNT_GROUPS.get(group, {}).get('nature', 'deudora')),
        "group": group,
        "parentId": parent_id,
        "level": 1,
        "description": request.form.get('description', '').strip(),
        "usage": request.form.get('usage') or None,
        "showByThirdParty": request.form.get('showByThirdParty') == 'on',
        "isActive": True,
        "isSystem": False,
        "orderIdx": int(request.form.get('orderIdx', 1)),
        "createdAt": now,
        "updatedAt": now,
    }
    # Calcular nivel basado en padre
    if parent_id:
        parent = DatabaseService.get_account(owner_uid, parent_id)
        if parent:
            account["level"] = parent.get("level", 1) + 1
    result = DatabaseService.save_account(owner_uid, account_id, account)
    if result:
        flash('✅ Cuenta contable creada exitosamente.', 'success')
    else:
        flash('❌ Error al crear la cuenta contable.', 'error')
    return redirect(url_for('web_accounting.chart_of_accounts'))


@web_accounting_bp.route('/accounting/account/<account_id>/edit', methods=['POST'])
@require_module('contabilidad')
def edit_account(account_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    account = DatabaseService.get_account(owner_uid, account_id)
    if not account:
        flash('❌ Cuenta contable no encontrada.', 'error')
        return redirect(url_for('web_accounting.chart_of_accounts'))
    if account.get('isSystem'):
        flash('❌ No puedes editar una cuenta regla del sistema.', 'error')
        return redirect(url_for('web_accounting.chart_of_accounts'))
    account['code'] = request.form.get('code', '').strip()
    account['name'] = request.form.get('name', '').strip()
    account['type'] = request.form.get('type', account.get('type', 'movimiento'))
    account['description'] = request.form.get('description', '').strip()
    account['showByThirdParty'] = request.form.get('showByThirdParty') == 'on'
    account['updatedAt'] = datetime.now(timezone.utc).isoformat()
    DatabaseService.save_account(owner_uid, account_id, account)
    flash('✅ Cuenta contable actualizada.', 'success')
    return redirect(url_for('web_accounting.chart_of_accounts'))


@web_accounting_bp.route('/accounting/account/<account_id>/delete', methods=['POST'])
@require_module('contabilidad')
def delete_account(account_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    account = DatabaseService.get_account(owner_uid, account_id)
    if not account:
        return jsonify(success=False, error="Cuenta no encontrada"), 404
    if account.get('isSystem'):
        return jsonify(success=False, error="No puedes eliminar una cuenta regla del sistema"), 400
    reclassify_to = request.form.get('reclassifyTo')
    if reclassify_to:
        entries = DatabaseService.get_accounting_entries(owner_uid)
        for entry in entries:
            modified = False
            for line in entry.get("lines", []):
                if line.get("accountId") == account_id:
                    line["accountId"] = reclassify_to
                    modified = True
            if modified:
                DatabaseService.save_accounting_entry(owner_uid, entry["id"], entry)
    DatabaseService.delete_account(owner_uid, account_id)
    return jsonify(success=True, message="Cuenta eliminada correctamente. Los movimientos han sido reclasificados.")


@web_accounting_bp.route('/accounting/account/<account_id>/movements')
@require_module('contabilidad')
def account_movements(account_id):
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    account = DatabaseService.get_account(owner_uid, account_id)
    if not account:
        flash('❌ Cuenta contable no encontrada.', 'error')
        return redirect(url_for('web_accounting.chart_of_accounts'))
    date_from = request.args.get('dateFrom', '')
    date_to = request.args.get('dateTo', '')
    # Obtener entradas una sola vez para movimientos y balance
    all_entries = DatabaseService.get_accounting_entries(owner_uid)
    movements = AccountingService.get_account_movements(owner_uid, account_id, date_from=date_from, date_to=date_to, entries=all_entries)
    balance = AccountingService.get_account_balance(owner_uid, account_id, date_from=date_from, date_to=date_to, entries=all_entries)
    return render_template('accounting/account_movements.html',
                           active_page='acc_chart',
                           account=account,
                           movements=movements,
                           balance=balance,
                           date_from=date_from,
                           date_to=date_to)


# =========================================================================
# ENTRADAS DE DIARIO (ASIENTOS MANUALES)
# =========================================================================
@web_accounting_bp.route('/accounting/journal-entries')
@require_module('contabilidad')
def journal_entries():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
    entry_types = DatabaseService.get_entry_types(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)

    q = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    type_filter = request.args.get('type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    if q:
        q_lower = q.lower()
        entries = [e for e in entries if
                   q_lower in (e.get('number', '') or '').lower()
                   or q_lower in (e.get('concept', '') or '').lower()
                   or q_lower in (e.get('referenceNumber', '') or '').lower()
                   or q_lower in (e.get('entryType', '') or '').lower()]

    if status_filter:
        entries = [e for e in entries if e.get('status') == status_filter]

    if type_filter:
        entries = [e for e in entries if e.get('entryType') == type_filter]

    if date_from:
        entries = [e for e in entries if str(e.get('date', ''))[:10] >= date_from]
    if date_to:
        entries = [e for e in entries if str(e.get('date', ''))[:10] <= date_to]

    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Número', 'Fecha', 'Concepto', 'Tipo', 'Débito', 'Crédito', 'Estado'])
        for e in entries:
            entry_type_label = {
                'invoice': 'Factura', 'credit_note': 'Nota de Crédito', 'expense': 'Gasto',
                'standard': 'Estándar', 'opening': 'Apertura', 'closing': 'Cierre',
                'initial_balance': 'Saldos Iniciales', 'depreciation': 'Depreciación',
                'disposal': 'Baja',
            }.get(e.get('entryType', ''), e.get('entryType', 'Estándar'))
            writer.writerow([
                e.get('number', ''),
                str(e.get('date', ''))[:10],
                e.get('concept', ''),
                entry_type_label,
                round(float(e.get('totalDebit', 0)), 2),
                round(float(e.get('totalCredit', 0)), 2),
                'Anulada' if e.get('status') == 'voided' else 'Activa',
            ])
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Disposition'] = 'attachment; filename=entradas_diario.csv'
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        return response

    type_labels = {
        'invoice': 'Factura', 'credit_note': 'Nota de Crédito', 'expense': 'Gasto',
        'standard': 'Estándar', 'opening': 'Apertura', 'closing': 'Cierre',
        'initial_balance': 'Saldos Iniciales', 'depreciation': 'Depreciación',
        'disposal': 'Baja',
    }

    today = datetime.now(timezone.utc)
    first_of_month = today.replace(day=1).strftime('%Y-%m-%d')
    qm = (today.month - 1) // 3 * 3 + 1
    quarter_start = today.replace(month=qm, day=1).strftime('%Y-%m-%d')
    year_start = today.replace(month=1, day=1).strftime('%Y-%m-%d')
    today_str = today.strftime('%Y-%m-%d')

    return render_template('accounting/journal_entries.html',
                           active_page='acc_entries',
                           entries=entries,
                           entry_types=entry_types,
                           accounts=accounts,
                           q=q, status_filter=status_filter,
                           type_filter=type_filter,
                           date_from=date_from, date_to=date_to,
                           type_labels=type_labels,
                           today_str=today_str,
                           first_of_month=first_of_month,
                           quarter_start=quarter_start,
                           year_start=year_start)


@web_accounting_bp.route('/accounting/journal-entries/new', methods=['GET', 'POST'])
@require_module('contabilidad')
def new_journal_entry():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    AccountingService.seed_default_entry_types(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    entry_types = DatabaseService.get_entry_types(owner_uid)
    if request.method == 'POST':
        try:
            lines = []
            line_accounts = request.form.getlist('line_account[]')
            line_debits = request.form.getlist('line_debit[]')
            line_credits = request.form.getlist('line_credit[]')
            line_descs = request.form.getlist('line_description[]')
            for i in range(len(line_accounts)):
                if not line_accounts[i]:
                    continue
                acc = DatabaseService.get_account(owner_uid, line_accounts[i])
                lines.append({
                    "accountId": line_accounts[i],
                    "accountCode": acc.get("code", "") if acc else "",
                    "accountName": acc.get("name", "") if acc else "",
                    "contactId": request.form.getlist('line_contact[]')[i] if i < len(request.form.getlist('line_contact[]')) else "",
                    "contactName": "",
                    "description": line_descs[i] if i < len(line_descs) else "",
                    "debit": float(line_debits[i]) if line_debits[i] else 0.0,
                    "credit": float(line_credits[i]) if line_credits[i] else 0.0,
                })
            entry_data = {
                "entryType": "standard",
                "typeId": request.form.get('typeId', ''),
                "date": request.form.get('date', datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "concept": request.form.get('concept', ''),
                "lines": lines,
                "createdBy": session['user'].get('uid', ''),
                "prefix": request.form.get('prefix', 'ED'),
            }
            entry = AccountingService.generate_entry(owner_uid, entry_data, sandbox=sandbox)
            flash(f'✅ Entrada de diario {entry["number"]} creada exitosamente.', 'success')
            return redirect(url_for('web_accounting.journal_entries'))
        except ValueError as e:
            flash(f'❌ {str(e)}', 'error')
        except Exception as e:
            flash(f'❌ Error al crear entrada de diario: {str(e)}', 'error')
    return render_template('accounting/journal_entry_form.html',
                           active_page='acc_entries',
                           accounts=accounts,
                           entry_types=entry_types,
                           is_edit=False)


@web_accounting_bp.route('/accounting/journal-entries/<entry_id>')
@require_module('contabilidad')
def journal_entry_detail(entry_id):
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    entry = DatabaseService.get_accounting_entry(owner_uid, entry_id, sandbox=sandbox)
    if not entry:
        flash('❌ Entrada de diario no encontrada.', 'error')
        return redirect(url_for('web_accounting.journal_entries'))
    return render_template('accounting/journal_entry_detail.html',
                           active_page='acc_entries',
                           entry=entry)


@web_accounting_bp.route('/accounting/journal-entries/<entry_id>/void', methods=['POST'])
@require_module('contabilidad')
def void_journal_entry(entry_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    reason = request.form.get('reason', '')
    AccountingService.void_entry(owner_uid, entry_id, reason=reason, user_id=session['user'].get('uid', ''), sandbox=sandbox)
    flash('✅ Entrada de diario anulada.', 'success')
    return redirect(url_for('web_accounting.journal_entries'))


@web_accounting_bp.route('/accounting/journal-entries/<entry_id>/clone', methods=['POST'])
@require_module('contabilidad')
def clone_journal_entry(entry_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    new_entry = AccountingService.clone_entry(owner_uid, entry_id, sandbox=sandbox)
    if new_entry:
        flash(f'✅ Entrada clonada como {new_entry["number"]}.', 'success')
    else:
        flash('❌ Error al clonar la entrada.', 'error')
    return redirect(url_for('web_accounting.journal_entries'))


# =========================================================================
# LIBRO DIARIO
# =========================================================================
@web_accounting_bp.route('/accounting/general-journal')
@require_module('contabilidad')
def general_journal():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
    date_from = request.args.get('dateFrom', '')
    date_to = request.args.get('dateTo', '')
    entry_type_filter = request.args.get('type', '')
    if date_from:
        entries = [e for e in entries if str(e.get("date", ""))[:10] >= date_from]
    if date_to:
        entries = [e for e in entries if str(e.get("date", ""))[:10] <= date_to]
    if entry_type_filter:
        entries = [e for e in entries if e.get("entryType") == entry_type_filter]
    active_entries = [e for e in entries if e.get("status") != "voided"]
    return render_template('accounting/general_journal.html',
                           active_page='acc_entries',
                           entries=active_entries,
                           date_from=date_from,
                           date_to=date_to,
                           entry_type_filter=entry_type_filter)


# =========================================================================
# REPORTES CONTABLES
# =========================================================================
@web_accounting_bp.route('/accounting/balance-sheet')
@require_module('contabilidad')
def balance_sheet():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    AccountingService.seed_default_accounts(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)

    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            y = int(date_to[:4])
            m = int(date_to[5:7])
            d = int(date_to[8:10])
        except ValueError:
            from datetime import date as _d
            y, m, d = _d.today().year, _d.today().month, _d.today().day
            date_to = f"{y}-{m:02d}-{d:02d}"
    else:
        from datetime import date as _d
        y, m, d = _d.today().year, _d.today().month, _d.today().day
        date_to = f"{y}-{m:02d}-{d:02d}"

    curr_date_to = date_to
    prev_y = y - 1
    prev_date_to = f"{prev_y}-{m:02d}-{d:02d}"

    # Precompute balance maps for BS — single Firestore call
    def _bs_balance_map(entries, date_to):
        bm = {}
        for entry in entries:
            if entry.get("status") == "voided":
                continue
            entry_date = str(entry.get("date", ""))[:10]
            if date_to and entry_date > date_to:
                continue
            for line in entry.get("lines", []):
                aid = line.get("accountId")
                if aid:
                    bm[aid] = bm.get(aid, 0.0) + float(line.get("debit", 0)) - float(line.get("credit", 0))
        return bm

    all_entries_bs = DatabaseService.get_accounting_entries(owner_uid)
    curr_balance_map_bs = _bs_balance_map(all_entries_bs, curr_date_to)
    prev_balance_map_bs = _bs_balance_map(all_entries_bs, prev_date_to)

    def bs_value(code, bm):
        for a in accounts:
            if a.get("code") == code and a.get("type") == "movimiento":
                b = bm.get(a["id"], 0.0)
                if a.get("group") in ("pasivos", "patrimonio"):
                    return -b
                return b
        return 0.0

    def sum_bs(codes, bm):
        t = 0.0
        for c in codes:
            t += bs_value(c, bm)
        return t

    def curr(code): return bs_value(code, curr_balance_map_bs)
    def prev(code): return bs_value(code, prev_balance_map_bs)
    def sum_curr(codes): return sum_bs(codes, curr_balance_map_bs)
    def sum_prev(codes): return sum_bs(codes, prev_balance_map_bs)

    month_abbr = ["","Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

    _from = f"{y}-01-01"
    def _pl_val(code, bm):
        for a in accounts:
            if a.get("code") == code and a.get("type") == "movimiento":
                b = bm.get(a["id"], 0.0)
                if a.get("group") == "ingresos": return -b
                return b
        return 0.0
    costos_ventas_periodo = sum(
        _pl_val(c, curr_balance_map_bs) for c in ["5.1.1.01","5.1.1.02","5.1.1.03","5.1.1.04","5.1.2"]
    )

    # ── Activos ──
    efectivo_codes = ["1.1.1.01","1.1.1.02","1.1.1.03"]
    bancos_codes = ["1.1.2.01"]
    cxc_clientes_codes = ["1.1.3.1.01","1.1.3.1.02"]
    cxc_avances_codes = ["1.1.3.3.01","1.1.3.3.02"]
    cxc_otros_codes = ["1.1.3.4.01","1.1.3.4.02","1.1.3.4.03","1.1.3.4.04","1.1.3.4.05","1.1.3.4.06"]
    cxc_codes = cxc_clientes_codes + cxc_avances_codes + cxc_otros_codes
    inversiones_codes = ["1.1.4.01","1.1.4.02","1.1.4.03"]
    impuestos_codes = ["1.1.5.01.01","1.1.5.01.02","1.1.5.01.03"]
    retenciones_codes = ["1.1.6.01.01","1.1.6.01.02","1.1.6.01.03"]
    inventarios_codes = ["1.1.7.01"]
    anticipado_codes = ["1.1.8"]
    otros_activos_codes = ["1.1.9"]
    # PP&E individual codes
    terrenos_code = "1.2.1.01"
    edificaciones_code = "1.2.1.03"
    dep_edificaciones_code = "1.2.1.04"
    construcciones_code = "1.2.1.05"
    mobiliario_code = "1.2.1.07"
    dep_mobiliario_code = "1.2.1.08"
    vehiculos_code = "1.2.1.09"
    dep_vehiculos_code = "1.2.1.10"
    computacion_code = "1.2.1.11"
    dep_computacion_code = "1.2.1.12"
    deterioro_code = "1.2.1.14"
    ppye_codes = [terrenos_code, edificaciones_code, dep_edificaciones_code,
                  construcciones_code, mobiliario_code, dep_mobiliario_code,
                  vehiculos_code, dep_vehiculos_code, computacion_code,
                  dep_computacion_code, deterioro_code]

    # ── Pasivos ──
    cxp_prov_codes = ["2.1.1.1.01","2.1.1.1.02"]
    cxp_avances_codes = ["2.1.1.2.01","2.1.1.2.02"]
    cxp_otras_codes = ["2.1.1.3.01","2.1.1.3.02","2.1.1.4.01","2.1.1.4.02",
                       "2.1.1.4.03","2.1.1.4.04","2.1.1.5.01"]
    acreedores_codes = cxp_prov_codes + cxp_avances_codes + cxp_otras_codes
    lab_salarios_codes = ["2.1.2.01","2.1.2.02","2.1.2.03","2.1.2.04"]
    lab_tss_codes = ["2.1.2.05","2.1.2.06","2.1.2.07","2.1.2.08","2.1.2.09","2.1.2.10"]
    lab_otras_codes = []
    laborales_codes = lab_salarios_codes + lab_tss_codes + lab_otras_codes
    financieras_cp_codes = ["2.1.3.01","2.1.3.02"]
    pasivos_impuestos_codes = ["2.1.4.01.01","2.1.4.01.02","2.1.4.02.01","2.1.4.02.02"]
    retenciones_pagar_codes = ["2.1.5.01.01","2.1.5.01.02","2.1.5.01.03"]
    otros_pasivos_codes = ["2.1.6.01"]
    financieras_lp_codes = ["2.2.1.01.01"]
    otros_pasivos_nc_codes = ["2.2.2"]

    # ── Patrimonio ──
    capital_suscrito_codes = ["3.1.1.01","3.1.1.02"]
    capital_suscribir_codes = ["3.1.2.01","3.1.2.02"]
    reservas_code = "3.2"
    utilidad_code = "3.3.01"
    perdida_code = "3.3.02"
    ganancias_acum_code = "3.3.03"
    superavit_code = "3.4"
    ajustes_bancos_code = "3.5.01"
    ajustes_inventario_code = "3.5.02"

    # Compute values
    efectivo_curr = sum_curr(efectivo_codes); efectivo_prev = sum_prev(efectivo_codes)
    bancos_curr = sum_curr(bancos_codes); bancos_prev = sum_prev(bancos_codes)
    cxc_curr = sum_curr(cxc_codes); cxc_prev = sum_prev(cxc_codes)
    inversiones_curr = sum_curr(inversiones_codes); inversiones_prev = sum_prev(inversiones_codes)
    impuestos_curr = sum_curr(impuestos_codes); impuestos_prev = sum_prev(impuestos_codes)
    retenciones_curr = sum_curr(retenciones_codes); retenciones_prev = sum_prev(retenciones_codes)
    inventarios_curr = sum_curr(inventarios_codes); inventarios_prev = sum_prev(inventarios_codes)
    anticipado_curr = curr(anticipado_codes[0]); anticipado_prev = prev(anticipado_codes[0])
    otros_activos_curr = curr(otros_activos_codes[0]); otros_activos_prev = prev(otros_activos_codes[0])
    activos_corrientes_curr = sum([efectivo_curr,bancos_curr,cxc_curr,inversiones_curr,
                                    impuestos_curr,retenciones_curr,inventarios_curr,
                                    anticipado_curr,otros_activos_curr])
    activos_corrientes_prev = sum([efectivo_prev,bancos_prev,cxc_prev,inversiones_prev,
                                    impuestos_prev,retenciones_prev,inventarios_prev,
                                    anticipado_prev,otros_activos_prev])
    # PP&E individual values
    terrenos_curr = curr(terrenos_code); terrenos_prev = prev(terrenos_code)
    edificaciones_curr = curr(edificaciones_code); edificaciones_prev = prev(edificaciones_code)
    dep_edif_curr = curr(dep_edificaciones_code); dep_edif_prev = prev(dep_edificaciones_code)
    const_curr = curr(construcciones_code); const_prev = prev(construcciones_code)
    mob_curr = curr(mobiliario_code); mob_prev = prev(mobiliario_code)
    dep_mob_curr = curr(dep_mobiliario_code); dep_mob_prev = prev(dep_mobiliario_code)
    veh_curr = curr(vehiculos_code); veh_prev = prev(vehiculos_code)
    dep_veh_curr = curr(dep_vehiculos_code); dep_veh_prev = prev(dep_vehiculos_code)
    comp_curr = curr(computacion_code); comp_prev = prev(computacion_code)
    dep_comp_curr = curr(dep_computacion_code); dep_comp_prev = prev(dep_computacion_code)
    deterioro_curr = curr(deterioro_code); deterioro_prev = prev(deterioro_code)
    ppye_curr = sum_curr(ppye_codes); ppye_prev = sum_prev(ppye_codes)
    activos_nc_curr = ppye_curr; activos_nc_prev = ppye_prev
    total_activos_curr = activos_corrientes_curr + activos_nc_curr
    total_activos_prev = activos_corrientes_prev + activos_nc_prev

    acreedores_curr = sum_curr(acreedores_codes); acreedores_prev = sum_prev(acreedores_codes)
    laborales_curr = sum_curr(laborales_codes); laborales_prev = sum_prev(laborales_codes)
    financieras_cp_curr = sum_curr(financieras_cp_codes); financieras_cp_prev = sum_prev(financieras_cp_codes)
    pasivos_impuestos_curr = sum_curr(pasivos_impuestos_codes); pasivos_impuestos_prev = sum_prev(pasivos_impuestos_codes)
    retenciones_pagar_curr = sum_curr(retenciones_pagar_codes); retenciones_pagar_prev = sum_prev(retenciones_pagar_codes)
    otros_pasivos_curr = sum_curr(otros_pasivos_codes); otros_pasivos_prev = sum_prev(otros_pasivos_codes)
    pasivos_corrientes_curr = sum([acreedores_curr,laborales_curr,financieras_cp_curr,
                                    pasivos_impuestos_curr,retenciones_pagar_curr,otros_pasivos_curr])
    pasivos_corrientes_prev = sum([acreedores_prev,laborales_prev,financieras_cp_prev,
                                    pasivos_impuestos_prev,retenciones_pagar_prev,otros_pasivos_prev])
    financieras_lp_curr = sum_curr(financieras_lp_codes); financieras_lp_prev = sum_prev(financieras_lp_codes)
    otros_pasivos_nc_curr = curr(otros_pasivos_nc_codes[0]); otros_pasivos_nc_prev = prev(otros_pasivos_nc_codes[0])
    pasivos_nc_curr = financieras_lp_curr + otros_pasivos_nc_curr
    pasivos_nc_prev = financieras_lp_prev + otros_pasivos_nc_prev
    total_pasivos_curr = pasivos_corrientes_curr + pasivos_nc_curr
    total_pasivos_prev = pasivos_corrientes_prev + pasivos_nc_prev

    cap_suscrito_curr = sum_curr(capital_suscrito_codes); cap_suscrito_prev = sum_prev(capital_suscrito_codes)
    cap_suscribir_curr = sum_curr(capital_suscribir_codes); cap_suscribir_prev = sum_prev(capital_suscribir_codes)
    capital_curr = cap_suscrito_curr + cap_suscribir_curr
    capital_prev = cap_suscrito_prev + cap_suscribir_prev
    reservas_curr = curr(reservas_code); reservas_prev = prev(reservas_code)
    utilidad_curr = curr(utilidad_code); utilidad_prev = prev(utilidad_code)
    perdida_curr = curr(perdida_code); perdida_prev = prev(perdida_code)
    ganancias_curr = curr(ganancias_acum_code); ganancias_prev = prev(ganancias_acum_code)
    resultado_curr = utilidad_curr - perdida_curr + ganancias_curr
    resultado_prev = utilidad_prev - perdida_prev + ganancias_prev
    superavit_curr = curr(superavit_code); superavit_prev = prev(superavit_code)
    ajs_bancos_curr = curr(ajustes_bancos_code); ajs_bancos_prev = prev(ajustes_bancos_code)
    ajs_inventario_curr = curr(ajustes_inventario_code); ajs_inventario_prev = prev(ajustes_inventario_code)
    ajustes_curr = ajs_bancos_curr + ajs_inventario_curr
    ajustes_prev = ajs_bancos_prev + ajs_inventario_prev
    total_patrimonio_curr = capital_curr + reservas_curr + resultado_curr + superavit_curr + ajustes_curr
    total_patrimonio_prev = capital_prev + reservas_prev + resultado_prev + superavit_prev + ajustes_prev
    total_pyf_curr = total_pasivos_curr + total_patrimonio_curr
    total_pyf_prev = total_pasivos_prev + total_patrimonio_prev

    base_curr = max(abs(total_activos_curr), abs(total_pyf_curr))
    base_prev = max(abs(total_activos_prev), abs(total_pyf_prev))

    def pct(val, base):
        return round(val / base * 100, 2) if abs(base) >= 0.001 else 0.0

    def line(label, curr_val, prev_val, indent=0, is_section=False, is_subtotal=False, is_calculated=False):
        return {
            "label": label,
            "curr": round(curr_val, 2) if not is_section else 0,
            "prev": round(prev_val, 2) if not is_section else 0,
            "curr_pct": pct(curr_val, base_curr),
            "prev_pct": pct(prev_val, base_prev),
            "abs_var": round(curr_val - prev_val, 2),
            "rel_var": round((curr_val - prev_val) / prev_val * 100, 2) if abs(prev_val) >= 0.001 else 0.0,
            "indent": indent,
            "is_section": is_section,
            "is_subtotal": is_subtotal,
            "is_calculated": is_calculated,
        }

    # ── Helper to build nested sections ──
    def section_items(items):
        for lbl, val_c, val_p, indent_lvl in items:
            lines.append(line(lbl, val_c, val_p, indent=indent_lvl))

    lines = []

    # Activos
    lines.append(line("Activos", 0, 0, is_section=True, indent=0))
    lines.append(line("Activos corrientes", 0, 0, is_section=True, indent=1))

    # Efectivo y equivalentes (section with children)
    lines.append(line("Efectivo y equivalentes de efectivo", 0, 0, is_section=True, indent=2))
    lines.append(line("Caja", efectivo_curr, efectivo_prev, indent=3))
    lines.append(line("Bancos", bancos_curr, bancos_prev, indent=3))
    lines.append(line("Efectivo y equivalentes de efectivo", efectivo_curr + bancos_curr, efectivo_prev + bancos_prev, indent=2, is_subtotal=True))

    # Deudores comerciales (section with children)
    lines.append(line("Deudores comerciales y otras cuentas por cobrar", 0, 0, is_section=True, indent=2))
    lines.append(line("Cuentas por cobrar clientes", sum_curr(cxc_clientes_codes), sum_prev(cxc_clientes_codes), indent=3))
    lines.append(line("Avances y anticipos entregados", sum_curr(cxc_avances_codes), sum_prev(cxc_avances_codes), indent=3))
    lines.append(line("Otros deudores", sum_curr(cxc_otros_codes), sum_prev(cxc_otros_codes), indent=3))
    lines.append(line("Deudores comerciales y otras cuentas por cobrar", cxc_curr, cxc_prev, indent=2, is_subtotal=True))

    lines.append(line("Inversiones financieras a corto plazo", inversiones_curr, inversiones_prev, indent=2))
    lines.append(line("Activos por impuestos corrientes", impuestos_curr, impuestos_prev, indent=2))
    lines.append(line("Activos por retenciones a favor", retenciones_curr, retenciones_prev, indent=2))
    lines.append(line("Inventarios", inventarios_curr, inventarios_prev, indent=2))
    lines.append(line("Activos pagados por anticipado", anticipado_curr, anticipado_prev, indent=2))
    lines.append(line("Otros activos corrientes", otros_activos_curr, otros_activos_prev, indent=2))
    lines.append(line("Activos corrientes", activos_corrientes_curr, activos_corrientes_prev, indent=1, is_subtotal=True))

    # Activos no corrientes → PP&E with individual assets
    lines.append(line("Activos no corrientes", 0, 0, is_section=True, indent=1))
    lines.append(line("Propiedad, planta y equipo (Activos fijos)", 0, 0, is_section=True, indent=2))
    ppye_items = [
        ("Terrenos", terrenos_curr, terrenos_prev, 3),
        ("Edificaciones", edificaciones_curr, edificaciones_prev, 3),
        ("Depreciación acumulada edificaciones", dep_edif_curr, dep_edif_prev, 3),
        ("Construcciones en proceso", const_curr, const_prev, 3),
        ("Mobiliario y equipo de oficina", mob_curr, mob_prev, 3),
        ("Depreciación acumulada mobiliario", dep_mob_curr, dep_mob_prev, 3),
        ("Vehículos y equipos de transporte", veh_curr, veh_prev, 3),
        ("Depreciación acumulada vehículos", dep_veh_curr, dep_veh_prev, 3),
        ("Equipo de computación", comp_curr, comp_prev, 3),
        ("Depreciación acumulada equipo de computación", dep_comp_curr, dep_comp_prev, 3),
        ("Deterioro acumulado de valor", deterioro_curr, deterioro_prev, 3),
    ]
    section_items(ppye_items)
    lines.append(line("Propiedad, planta y equipo (Activos fijos)", ppye_curr, ppye_prev, indent=2, is_subtotal=True))
    lines.append(line("Activos no corrientes", activos_nc_curr, activos_nc_prev, indent=1, is_subtotal=True))
    lines.append(line("Total activos", total_activos_curr, total_activos_prev, indent=0, is_calculated=True))

    # Pasivos
    lines.append(line("Pasivos", 0, 0, is_section=True, indent=0))
    lines.append(line("Pasivos corrientes", 0, 0, is_section=True, indent=1))

    # Acreedores comerciales (section with sub-groups)
    lines.append(line("Acreedores comerciales y otras cuentas por pagar", 0, 0, is_section=True, indent=2))
    lines.append(line("Cuentas por pagar a proveedores", sum_curr(cxp_prov_codes), sum_prev(cxp_prov_codes), indent=3))
    lines.append(line("Avances y anticipos recibidos", sum_curr(cxp_avances_codes), sum_prev(cxp_avances_codes), indent=3))
    lines.append(line("Otras cuentas por pagar", sum_curr(cxp_otras_codes), sum_prev(cxp_otras_codes), indent=3))
    lines.append(line("Acreedores comerciales y otras cuentas por pagar", acreedores_curr, acreedores_prev, indent=2, is_subtotal=True))

    # Obligaciones laborales (section with sub-groups)
    lines.append(line("Obligaciones laborales y de seguridad social", 0, 0, is_section=True, indent=2))
    lines.append(line("Salarios y prestaciones sociales", sum_curr(lab_salarios_codes), sum_prev(lab_salarios_codes), indent=3))
    lines.append(line("Tesorería de la seguridad social", sum_curr(lab_tss_codes), sum_prev(lab_tss_codes), indent=3))
    lines.append(line("Otras obligaciones laborales", sum_curr(lab_otras_codes), sum_prev(lab_otras_codes), indent=3))
    lines.append(line("Obligaciones laborales y de seguridad social", laborales_curr, laborales_prev, indent=2, is_subtotal=True))

    lines.append(line("Obligaciones financieras a corto plazo", financieras_cp_curr, financieras_cp_prev, indent=2))
    lines.append(line("Pasivos por impuestos corrientes", pasivos_impuestos_curr, pasivos_impuestos_prev, indent=2))
    lines.append(line("Pasivos por retenciones corrientes", retenciones_pagar_curr, retenciones_pagar_prev, indent=2))
    lines.append(line("Otros pasivos corrientes", otros_pasivos_curr, otros_pasivos_prev, indent=2))
    lines.append(line("Pasivos corrientes", pasivos_corrientes_curr, pasivos_corrientes_prev, indent=1, is_subtotal=True))
    lines.append(line("Pasivos no corrientes", 0, 0, is_section=True, indent=1))
    lines.append(line("Obligaciones financieras a largo plazo", financieras_lp_curr, financieras_lp_prev, indent=2))
    lines.append(line("Otros pasivos no corrientes", otros_pasivos_nc_curr, otros_pasivos_nc_prev, indent=2))
    lines.append(line("Pasivos no corrientes", pasivos_nc_curr, pasivos_nc_prev, indent=1, is_subtotal=True))
    lines.append(line("Total pasivos", total_pasivos_curr, total_pasivos_prev, indent=0, is_calculated=True))

    # Patrimonio
    lines.append(line("Patrimonio", 0, 0, is_section=True, indent=0))
    lines.append(line("Capital social", 0, 0, is_section=True, indent=1))
    lines.append(line("Capital social suscrito y pagado", cap_suscrito_curr, cap_suscrito_prev, indent=2))
    lines.append(line("Capital por suscribir o Acciones", cap_suscribir_curr, cap_suscribir_prev, indent=2))
    lines.append(line("Capital social", capital_curr, capital_prev, indent=1, is_subtotal=True))
    lines.append(line("Reservas", reservas_curr, reservas_prev, indent=2))
    lines.append(line("Resultado del ejercicio", 0, 0, is_section=True, indent=1))
    lines.append(line("Utilidad del ejercicio", utilidad_curr, utilidad_prev, indent=2))
    lines.append(line("Pérdida del ejercicio", perdida_curr, perdida_prev, indent=2))
    lines.append(line("Ganancias acumuladas", ganancias_curr, ganancias_prev, indent=2))
    lines.append(line("Resultado del ejercicio", resultado_curr, resultado_prev, indent=1, is_subtotal=True))
    lines.append(line("Superávit", superavit_curr, superavit_prev, indent=2))
    lines.append(line("Ajustes por saldos iniciales", 0, 0, is_section=True, indent=1))
    lines.append(line("Ajustes iniciales en bancos", ajs_bancos_curr, ajs_bancos_prev, indent=2))
    lines.append(line("Ajustes iniciales en inventario", ajs_inventario_curr, ajs_inventario_prev, indent=2))
    lines.append(line("Ajustes por saldos iniciales", ajustes_curr, ajustes_prev, indent=1, is_subtotal=True))
    lines.append(line("Total patrimonio", total_patrimonio_curr, total_patrimonio_prev, indent=0, is_calculated=True))
    lines.append(line("Total pasivos + patrimonio", total_pyf_curr, total_pyf_prev, indent=0, is_calculated=True))

    # ── AI Summary ──
    ai_summary = None
    if abs(total_activos_curr) >= 0.001 or abs(total_pyf_curr) >= 0.001:
        parts = []
        parts.append(f"El estado de situación financiera presenta un activo total de RD$ {total_activos_curr:,.2f}")
        if activos_corrientes_curr > 0:
            parts.append(f", de los cuales RD$ {activos_corrientes_curr:,.2f} ({pct(activos_corrientes_curr, total_activos_curr)}%) son activos corrientes")
        if total_pasivos_curr > 0:
            parts.append(f". Los pasivos totales son RD$ {total_pasivos_curr:,.2f} ({pct(total_pasivos_curr, total_pyf_curr)}% del financiamiento)")
        parts.append(f", y el patrimonio total es RD$ {total_patrimonio_curr:,.2f} ({pct(total_patrimonio_curr, total_pyf_curr)}%).")
        ai_summary = "".join(parts)
    else:
        ai_summary = "No hay suficientes movimientos en el período seleccionado para generar un análisis."

    # ── BS Indicators ──
    def ratio(val, base):
        return round(val / base * 100, 2) if abs(base) >= 0.001 else 0.0

    liquidez_curr = ratio(activos_corrientes_curr, pasivos_corrientes_curr) if abs(pasivos_corrientes_curr) >= 0.001 else 999.99
    liquidez_prev = ratio(activos_corrientes_prev, pasivos_corrientes_prev)

    rotacion_inv = ratio(costos_ventas_periodo, inventarios_curr) if abs(inventarios_curr) >= 0.001 else 0.0

    from datetime import datetime as _dt
    return render_template('accounting/balance_sheet.html',
                           active_page='acc_reports',
                           lines=lines,
                           total_activos_curr=round(total_activos_curr, 2),
                           total_activos_prev=round(total_activos_prev, 2),
                           total_pasivos_curr=round(total_pasivos_curr, 2),
                           total_pasivos_prev=round(total_pasivos_prev, 2),
                           total_patrimonio_curr=round(total_patrimonio_curr, 2),
                           total_patrimonio_prev=round(total_patrimonio_prev, 2),
                            total_pyf_curr=round(total_pyf_curr, 2),
                            total_pyf_prev=round(total_pyf_prev, 2),
                            date_to=date_to,
                            date_display=f"{d} {month_abbr[m]}, {y}",
                            date_prev_display=f"{d} {month_abbr[m]}, {prev_y}",
                            prev_year=prev_y,
                            y=y, m=m, d=d,
                            ai_summary=ai_summary,
                            liquidez_curr=liquidez_curr,
                            liquidez_prev=liquidez_prev,
                            datetime=_dt)


@web_accounting_bp.route('/accounting/income-statement')
@require_module('contabilidad')
def income_statement():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    AccountingService.seed_default_accounts(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)

    # Build code_map for O(1) lookups
    code_map = {}
    for a in accounts:
        c = a.get("code")
        if c:
            code_map[c] = {"id": a["id"], "group": a.get("group"), "type": a.get("type"), "label": a.get("name", c)}

    # Date range from query params; default to current month
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    if date_from and date_to:
        curr_date_from = date_from
        curr_date_to = date_to
        try:
            y = int(date_from[:4])
            m = int(date_from[5:7])
        except ValueError:
            y = datetime.now(timezone.utc).year
            m = datetime.now(timezone.utc).month
    else:
        y = datetime.now(timezone.utc).year
        m = datetime.now(timezone.utc).month
        d = datetime.now(timezone.utc).day
        curr_date_from = f"{y}-{m:02d}-01"
        curr_date_to = f"{y}-{m:02d}-{d:02d}"
        date_from = curr_date_from
        date_to = curr_date_to

    prev_y = y - 1
    prev_date_from = f"{prev_y}-{date_from[4:]}"
    prev_date_to = f"{prev_y}-{date_to[4:]}"

    # Precompute balance maps — single Firestore call
    all_entries = DatabaseService.get_accounting_entries(owner_uid)
    curr_balance_map = AccountingService._compute_balances_map(all_entries, date_from=curr_date_from, date_to=curr_date_to)
    prev_balance_map = AccountingService._compute_balances_map(all_entries, date_from=prev_date_from, date_to=prev_date_to)

    def pl_value(code, bm):
        meta = code_map.get(code)
        if meta and meta["type"] == "movimiento":
            b = bm.get(meta["id"], 0.0)
            if meta["group"] == "ingresos":
                return -b
            return b
        return 0.0

    def sum_pl(codes, bm):
        t = 0.0
        for c in codes:
            t += pl_value(c, bm)
        return t

    def account_label(code):
        meta = code_map.get(code)
        return meta["label"] if meta else code

    # P&L hierarchy: each item is {label, _accounts (list of codes), _children (for section indent)}
    # Calculated lines use _calc = (sum_keys, subtract_keys)
    ingresos_codes = ["4.1.01", "4.1.02"]
    ventas_code = "4.1.01"
    devoluciones_code = "4.1.02"

    costos_mercancia_codes = ["5.1.1.01", "5.1.1.02", "5.1.1.03", "5.1.1.04"]
    costos_servicios_code = "5.1.2"

    gastos_venta_personal_codes = [
        "6.1.1.01","6.1.1.02","6.1.1.03","6.1.1.04","6.1.1.05",
        "6.1.1.06","6.1.1.07","6.1.1.08","6.1.1.09","6.1.1.10",
        "6.1.1.11","6.1.1.12"
    ]
    gastos_admin_personal_codes = [
        "6.2.1.01","6.2.1.02","6.2.1.03","6.2.1.04","6.2.1.05",
        "6.2.1.06","6.2.1.07","6.2.1.08","6.2.1.09","6.2.1.10",
        "6.2.1.11","6.2.1.12","6.2.1.13"
    ]
    gastos_generales_codes = [
        "6.2.2.01.01","6.2.2.01.02","6.2.2.02.01","6.2.2.02.02",
        "6.2.2.03.01","6.2.2.03.02","6.2.2.03.03","6.2.2.03.04",
        "6.2.2.03.05","6.2.2.03.06","6.2.2.03.07","6.2.2.04",
        "6.2.2.05.01","6.2.2.05.02","6.2.2.06.01","6.2.2.07",
        "6.2.2.08.01","6.2.2.09","6.2.2.10","6.2.2.11",
        "6.2.2.12.01","6.2.2.12.02","6.2.2.12.03","6.2.2.13",
        "6.2.2.14.01","6.2.2.15","6.2.2.16.01","6.2.2.16.02",
        "6.2.2.16.03","6.2.2.17.01","6.2.2.17.02","6.2.2.17.03",
        "6.2.2.17.04","6.2.2.17.05","6.2.2.18","6.2.2.19"
    ]
    depreciaciones_codes = [
        "6.2.3.01","6.2.3.02","6.2.3.03","6.2.3.04","6.2.3.05","6.2.3.06"
    ]

    otros_ingresos_codes = ["4.2.1.01","4.2.2","4.2.3","4.2.4"]

    gastos_financieros_codes = ["6.3.01","6.3.02"]
    otros_gastos_codes = ["6.4.01","6.4.02","6.4.03","6.4.04"]
    impuestos_codes = ["6.5.01","6.5.02","6.5.03"]

    def curr(code):
        return pl_value(code, curr_balance_map)
    def prev(code):
        return pl_value(code, prev_balance_map)
    def sum_curr(codes):
        return sum_pl(codes, curr_balance_map)
    def sum_prev(codes):
        return sum_pl(codes, prev_balance_map)

    ventas_curr = curr(ventas_code)
    ventas_prev = prev(ventas_code)
    devoluciones_curr = curr(devoluciones_code)
    devoluciones_prev = prev(devoluciones_code)
    ingresos_ordinarios_curr = sum_curr(ingresos_codes)
    ingresos_ordinarios_prev = sum_prev(ingresos_codes)

    costo_mercancia_curr = sum_curr(costos_mercancia_codes)
    costo_mercancia_prev = sum_prev(costos_mercancia_codes)
    costo_servicios_curr = curr(costos_servicios_code)
    costo_servicios_prev = prev(costos_servicios_code)
    costos_ventas_curr = costo_mercancia_curr + costo_servicios_curr
    costos_ventas_prev = costo_mercancia_prev + costo_servicios_prev

    utilidad_bruta_curr = ingresos_ordinarios_curr - costos_ventas_curr
    utilidad_bruta_prev = ingresos_ordinarios_prev - costos_ventas_prev

    gastos_venta_personal_curr = sum_curr(gastos_venta_personal_codes)
    gastos_venta_personal_prev = sum_prev(gastos_venta_personal_codes)
    gastos_venta_curr = gastos_venta_personal_curr
    gastos_venta_prev = gastos_venta_personal_prev

    gastos_admin_personal_curr = sum_curr(gastos_admin_personal_codes)
    gastos_admin_personal_prev = sum_prev(gastos_admin_personal_codes)
    gastos_generales_curr = sum_curr(gastos_generales_codes)
    gastos_generales_prev = sum_prev(gastos_generales_codes)
    depreciaciones_curr = sum_curr(depreciaciones_codes)
    depreciaciones_prev = sum_prev(depreciaciones_codes)
    gastos_admin_curr = gastos_admin_personal_curr + gastos_generales_curr + depreciaciones_curr
    gastos_admin_prev = gastos_admin_personal_prev + gastos_generales_prev + depreciaciones_prev

    total_gastos_curr = gastos_venta_curr + gastos_admin_curr
    total_gastos_prev = gastos_venta_prev + gastos_admin_prev

    utilidad_operativa_curr = utilidad_bruta_curr - total_gastos_curr
    utilidad_operativa_prev = utilidad_bruta_prev - total_gastos_prev

    otros_ingresos_curr = sum_curr(otros_ingresos_codes)
    otros_ingresos_prev = sum_prev(otros_ingresos_codes)

    gastos_financieros_curr = sum_curr(gastos_financieros_codes)
    gastos_financieros_prev = sum_prev(gastos_financieros_codes)

    otros_gastos_curr = sum_curr(otros_gastos_codes)
    otros_gastos_prev = sum_prev(otros_gastos_codes)

    utilidad_antes_impuestos_curr = utilidad_operativa_curr + otros_ingresos_curr - gastos_financieros_curr - otros_gastos_curr
    utilidad_antes_impuestos_prev = utilidad_operativa_prev + otros_ingresos_prev - gastos_financieros_prev - otros_gastos_prev

    impuestos_curr = sum_curr(impuestos_codes)
    impuestos_prev = sum_prev(impuestos_codes)

    utilidad_neta_curr = utilidad_antes_impuestos_curr - impuestos_curr
    utilidad_neta_prev = utilidad_antes_impuestos_prev - impuestos_prev

    def pct(val, revenue):
        if abs(revenue) < 0.001:
            return 0.0
        return round(val / revenue * 100, 2)

    def var_abs(curr_val, prev_val):
        return curr_val - prev_val

    def var_rel(curr_val, prev_val):
        if abs(prev_val) < 0.001:
            return 0.0
        return round((curr_val - prev_val) / prev_val * 100, 2)

    def line(label, curr_val, prev_val, indent=0, is_subtotal=False, is_calculated=False, is_section=False):
        return {
            "label": label,
            "curr": round(curr_val, 2) if not is_section else 0,
            "prev": round(prev_val, 2) if not is_section else 0,
            "curr_pct": pct(curr_val, ventas_curr),
            "prev_pct": pct(prev_val, ventas_prev),
            "abs_var": round(var_abs(curr_val, prev_val), 2),
            "rel_var": var_rel(curr_val, prev_val),
            "indent": indent,
            "is_subtotal": is_subtotal,
            "is_calculated": is_calculated,
            "is_section": is_section,
        }

    lines = []

    # Section: Ingresos de actividades ordinarias
    lines.append(line("Ingresos de actividades ordinarias", 0, 0, is_section=True, indent=0))
    lines.append(line("Ventas", ventas_curr, ventas_prev, indent=1))
    lines.append(line("Devoluciones en ventas", devoluciones_curr, devoluciones_prev, indent=1))
    lines.append(line("Ingresos de actividades ordinarias", ingresos_ordinarios_curr, ingresos_ordinarios_prev, indent=0, is_subtotal=True))

    # Section: Costos de ventas y operación
    lines.append(line("Costos de ventas y operación", 0, 0, is_section=True, indent=0))
    lines.append(line("Costos de la mercancía vendida", costo_mercancia_curr, costo_mercancia_prev, indent=1))
    for code in costos_mercancia_codes:
        lines.append(line(account_label(code), curr(code), prev(code), indent=2))
    lines.append(line("Costo de los servicios vendidos", costo_servicios_curr, costo_servicios_prev, indent=1))
    lines.append(line("Costos de ventas y operación", costos_ventas_curr, costos_ventas_prev, indent=0, is_subtotal=True))

    # Utilidad bruta (calculated)
    lines.append(line("Utilidad bruta", utilidad_bruta_curr, utilidad_bruta_prev, indent=0, is_calculated=True))

    # Section: Gastos de venta
    lines.append(line("Gastos de venta", 0, 0, is_section=True, indent=0))
    lines.append(line("Gastos de personal de ventas", gastos_venta_personal_curr, gastos_venta_personal_prev, indent=1))
    for code in gastos_venta_personal_codes:
        lines.append(line(account_label(code), curr(code), prev(code), indent=2))
    lines.append(line("Gastos de venta", gastos_venta_curr, gastos_venta_prev, indent=0, is_subtotal=True))

    # Section: Gastos de administración
    lines.append(line("Gastos de administración", 0, 0, is_section=True, indent=0))
    lines.append(line("Gastos de personal", gastos_admin_personal_curr, gastos_admin_personal_prev, indent=1))
    for code in gastos_admin_personal_codes:
        lines.append(line(account_label(code), curr(code), prev(code), indent=2))
    lines.append(line("Gastos generales", gastos_generales_curr, gastos_generales_prev, indent=1))

    lines.append(line("Propaganda y publicidad", curr("6.2.2.10"), prev("6.2.2.10"), indent=2))

    # Depreciaciones: total + individual accounts
    lines.append(line("Depreciaciones, amortizaciones y desvalorizaciones", depreciaciones_curr, depreciaciones_prev, indent=2))
    for code in depreciaciones_codes:
        lines.append(line(account_label(code), curr(code), prev(code), indent=3))

    # Sub-items of Gastos generales (level 2 indent, children at level 3)
    generales_sub = [
        ("6.2.2.18", "Cuotas y suscripciones"),
        ("6.2.2.17", "Mantenimiento y conservación"),
        ("6.2.2.16", "Gastos legales"),
        ("6.2.2.15", "Gastos constitución"),
        ("6.2.2.14.01", "Servicios Online"),
        ("6.2.2.13", "Patentes y marcas"),
        ("6.2.2.12", "Seguros"),
        ("6.2.2.11", "Capacitación al personal"),
        ("6.2.2.01", "Servicios profesionales"),
        ("6.2.2.09", "Estacionamiento"),
        ("6.2.2.08.01", "Fletes y gastos de envios"),
        ("6.2.2.07", "Combustibles y lubricantes"),
        ("6.2.2.06.01", "Artículos de oficina"),
        ("6.2.2.05.02", "Viáticos y gastos de viaje"),
        ("6.2.2.05.01", "Comidas y entretenimiento"),
        ("6.2.2.05", "Gastos de representación"),
        ("6.2.2.04", "Vigilancia y seguridad"),
        ("6.2.2.03", "Servicios públicos"),
        ("6.2.2.02", "Arrendamientos"),
        ("6.2.2.19", "Otros gastos generales"),
    ]
    _sum_generales_sub = 0.0
    _sum_generales_sub_prev = 0.0
    for g_code, g_label in generales_sub:
        children = [a for a in accounts if a.get("code","").startswith(g_code) and a.get("type") == "movimiento" and a.get("code") != g_code]
        if children:
            s_curr = 0.0
            s_prev = 0.0
            child_codes = []
            for ch in children:
                chc = ch["code"]
                if chc not in child_codes:
                    child_codes.append(chc)
            for chc in child_codes:
                cv = pl_value(chc, curr_balance_map)
                pv = pl_value(chc, prev_balance_map)
                s_curr += cv
                s_prev += pv
                lines.append(line(account_label(chc), cv, pv, indent=3))
        else:
            s_curr = sum_pl([g_code], curr_balance_map)
            s_prev = sum_pl([g_code], prev_balance_map)
        _sum_generales_sub += s_curr
        _sum_generales_sub_prev += s_prev
        lines.append(line(g_label, s_curr, s_prev, indent=2))

    lines.append(line("Total Gastos generales", gastos_generales_curr, gastos_generales_prev, indent=1, is_subtotal=True))

    lines.append(line("Gastos de administración", gastos_admin_curr, gastos_admin_prev, indent=0, is_subtotal=True))

    # Utilidad operativa
    lines.append(line("Utilidad operativa", utilidad_operativa_curr, utilidad_operativa_prev, indent=0, is_calculated=True))

    # Section: Otros Ingresos
    lines.append(line("Otros Ingresos", 0, 0, is_section=True, indent=0))
    lines.append(line("Ingresos financieros", curr("4.2.1.01"), prev("4.2.1.01"), indent=1))
    lines.append(line("Otros ingresos diversos", curr("4.2.2"), prev("4.2.2"), indent=1))
    lines.append(line("Ganancia por diferencia en cambio", curr("4.2.3"), prev("4.2.3"), indent=1))
    lines.append(line("Ajustes por aproximaciones en cálculos", curr("4.2.4"), prev("4.2.4"), indent=1))
    lines.append(line("Otros Ingresos", otros_ingresos_curr, otros_ingresos_prev, indent=0, is_subtotal=True))

    # Section: Gastos financieros
    lines.append(line("Gastos financieros", 0, 0, is_section=True, indent=0))
    lines.append(line("Gastos por Intereses financieros", curr("6.3.01"), prev("6.3.01"), indent=1))
    lines.append(line("Gastos por Intereses de mora", curr("6.3.02"), prev("6.3.02"), indent=1))
    lines.append(line("Gastos financieros", gastos_financieros_curr, gastos_financieros_prev, indent=0, is_subtotal=True))

    # Section: Otros gastos
    lines.append(line("Otros gastos", 0, 0, is_section=True, indent=0))
    lines.append(line("Comisiones bancarias", curr("6.4.01"), prev("6.4.01"), indent=1))
    lines.append(line("Pérdida por diferencia en cambio", curr("6.4.02"), prev("6.4.02"), indent=1))
    lines.append(line("Ajustes por aproximaciones en cálculos", curr("6.4.03"), prev("6.4.03"), indent=1))
    lines.append(line("Pérdida por disposición de activos", curr("6.4.04"), prev("6.4.04"), indent=1))
    lines.append(line("Otros gastos", otros_gastos_curr, otros_gastos_prev, indent=0, is_subtotal=True))

    # Utilidad antes de impuestos
    lines.append(line("Utilidad antes de impuestos", utilidad_antes_impuestos_curr, utilidad_antes_impuestos_prev, indent=0, is_calculated=True))

    # Section: Gastos por impuestos
    lines.append(line("Gastos por impuestos", 0, 0, is_section=True, indent=0))
    lines.append(line("Impuestos de renta", curr("6.5.01"), prev("6.5.01"), indent=1))
    lines.append(line("Gastos por impuestos no acreditables", curr("6.5.02"), prev("6.5.02"), indent=1))
    lines.append(line("Retenciones asumidas", curr("6.5.03"), prev("6.5.03"), indent=1))
    lines.append(line("Gastos por impuestos", impuestos_curr, impuestos_prev, indent=0, is_subtotal=True))

    # Utilidad neta
    lines.append(line("Utilidad neta", utilidad_neta_curr, utilidad_neta_prev, indent=0, is_calculated=True))

    # ── AI Summary ──
    ai_summary = None
    if abs(ventas_curr) < 0.001 and abs(total_gastos_curr) < 0.001:
        ai_summary = "No hay suficientes movimientos en el período seleccionado para generar un análisis."
    else:
        parts = []
        if utilidad_neta_curr > 0:
            parts.append(f"tu empresa generó una utilidad neta de RD$ {utilidad_neta_curr:,.2f}, lo que representa un {pct(utilidad_neta_curr, ventas_curr)}% de margen neto sobre los ingresos.")
        elif utilidad_neta_curr < 0:
            parts.append(f"tu empresa registró una pérdida neta de RD$ {abs(utilidad_neta_curr):,.2f} en el período.")
        else:
            parts.append("tu empresa cerró el período con un resultado neto de cero.")
        if ingresos_ordinarios_curr > 0:
            parts.append(f"Los ingresos de actividades ordinarias fueron de RD$ {ingresos_ordinarios_curr:,.2f}")
            if costos_ventas_curr > 0:
                parts.append(f"con un costo de ventas de RD$ {costos_ventas_curr:,.2f} ({pct(costos_ventas_curr, ingresos_ordinarios_curr)}% de los ingresos)")
            if abs(utilidad_bruta_curr) > 0:
                parts.append(f"generando una utilidad bruta de RD$ {utilidad_bruta_curr:,.2f} (margen bruto: {pct(utilidad_bruta_curr, ingresos_ordinarios_curr)}%)")
        if total_gastos_curr > 0:
            parts.append(f"Los gastos operativos totalizaron RD$ {total_gastos_curr:,.2f}")
        ai_summary = " ".join(parts)

    # ── Profitability Indicators ──
    def ratio(val, base):
        return round(val / base * 100, 2) if abs(base) >= 0.001 else 0.0

    margen_bruto_curr = ratio(utilidad_bruta_curr, ingresos_ordinarios_curr)
    margen_bruto_prev = ratio(utilidad_bruta_prev, ingresos_ordinarios_prev)

    margen_operativo_curr = ratio(utilidad_operativa_curr, ingresos_ordinarios_curr)
    margen_operativo_prev = ratio(utilidad_operativa_prev, ingresos_ordinarios_prev)

    margen_neto_curr = ratio(utilidad_neta_curr, ingresos_ordinarios_curr)
    margen_neto_prev = ratio(utilidad_neta_prev, ingresos_ordinarios_prev)

    # ROA = Utilidad neta / Total Activos, ROE = Utilidad neta / Total Patrimonio
    def _group_sum(group_name, bm):
        s = 0.0
        for a in accounts:
            if a.get("type") == "movimiento" and a.get("group") == group_name:
                b = bm.get(a["id"], 0.0)
                if a.get("nature") == "deudora":
                    s += b
                else:
                    s -= b
        return round(s, 2)

    total_assets_curr = _group_sum("activos", curr_balance_map)
    total_assets_prev = _group_sum("activos", prev_balance_map)
    total_equity_curr = _group_sum("patrimonio", curr_balance_map)
    total_equity_prev = _group_sum("patrimonio", prev_balance_map)

    roa_curr = ratio(utilidad_neta_curr, total_assets_curr)
    roa_prev = ratio(utilidad_neta_prev, total_assets_prev)
    roe_curr = ratio(utilidad_neta_curr, total_equity_curr)
    roe_prev = ratio(utilidad_neta_prev, total_equity_prev)

    # ── Chart data ──
    chart_series = [
        {"label": "Utilidad bruta", "curr": round(utilidad_bruta_curr, 2), "prev": round(utilidad_bruta_prev, 2)},
        {"label": "Utilidad operativa", "curr": round(utilidad_operativa_curr, 2), "prev": round(utilidad_operativa_prev, 2)},
        {"label": "Utilidad neta", "curr": round(utilidad_neta_curr, 2), "prev": round(utilidad_neta_prev, 2)},
    ]

    from datetime import datetime as _dt
    month_abbr = ["","Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    return render_template('accounting/income_statement.html',
                           active_page='acc_reports',
                           datetime=_dt,
                           lines=lines,
                           ventas_curr=ventas_curr,
                           ventas_prev=ventas_prev,
                           ingresos_ordinarios_curr=round(ingresos_ordinarios_curr, 2),
                           costos_ventas_curr=round(costos_ventas_curr, 2),
                           total_gastos_curr=round(total_gastos_curr, 2),
                           utilidad_bruta_curr=round(utilidad_bruta_curr, 2),
                           utilidad_operativa_curr=round(utilidad_operativa_curr, 2),
                           utilidad_neta_curr=round(utilidad_neta_curr, 2),
                           date_from=date_from, date_to=date_to,
                           date_from_display=f"{month_abbr[m]} {y}",
                           date_prev_display=f"{month_abbr[m]} {prev_y}",
                           prev_year=prev_y,
                           ai_summary=ai_summary,
                           y=y, m=m,
                           margen_bruto_curr=margen_bruto_curr,
                           margen_bruto_prev=margen_bruto_prev,
                           margen_operativo_curr=margen_operativo_curr,
                           margen_operativo_prev=margen_operativo_prev,
                           margen_neto_curr=margen_neto_curr,
                           margen_neto_prev=margen_neto_prev,
                           roa_curr=roa_curr, roa_prev=roa_prev,
                           roe_curr=roe_curr, roe_prev=roe_prev,
                           chart_series=chart_series)


@web_accounting_bp.route('/accounting/trial-balance')
@require_module('contabilidad')
def trial_balance():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    date = request.args.get('date', '')
    result = AccountingService.get_trial_balance(owner_uid, date=date or None)
    return render_template('accounting/trial_balance.html',
                           active_page='acc_reports',
                           rows=result["rows"],
                           total_debit=result["totalDebit"],
                           total_credit=result["totalCredit"],
                           date=date)


# =========================================================================
# MAYOR GENERAL
# =========================================================================
@web_accounting_bp.route('/accounting/general-ledger')
@require_module('contabilidad')
def general_ledger():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    entries = DatabaseService.get_accounting_entries(owner_uid, sandbox=sandbox)
    all_accounts = DatabaseService.get_chart_of_accounts(owner_uid)

    # Build account lookup: id -> {code, name, type, group, nature}
    account_map = {}
    for a in all_accounts:
        account_map[a["id"]] = {
            "code": a.get("code", ""),
            "name": a.get("name", ""),
            "type": a.get("type", ""),
            "group": a.get("group", ""),
            "nature": a.get("nature", "deudora"),
            "id": a["id"],
        }

    date_from = request.args.get('dateFrom', '')
    date_to = request.args.get('dateTo', '')
    account_filter = request.args.get('account', '')  # accountId

    # Filter active entries by date
    active = [e for e in entries if e.get("status") != "voided"]
    if date_from:
        active = [e for e in active if str(e.get("date", ""))[:10] >= date_from]
    if date_to:
        active = [e for e in active if str(e.get("date", ""))[:10] <= date_to]

    # Process line items
    account_lines = {}  # accountId -> list of line dicts
    for entry in active:
        entry_date = str(entry.get("date", ""))[:10]
        for line in entry.get("lines", []):
            aid = line.get("accountId")
            if not aid:
                continue
            if account_filter and aid != account_filter:
                continue
            account_lines.setdefault(aid, []).append({
                "date": entry_date,
                "number": entry.get("number", ""),
                "concept": entry.get("concept", ""),
                "entryType": entry.get("entryType", ""),
                "debit": float(line.get("debit", 0) or 0),
                "credit": float(line.get("credit", 0) or 0),
            })

    # Sort accounts and calculate balances
    ledger_accounts = []
    total_debit = 0.0
    total_credit = 0.0

    for aid, lines in account_lines.items():
        acct = account_map.get(aid)
        if not acct:
            continue
        # Sort lines by date
        lines.sort(key=lambda l: l["date"])

        # Calculate running balance
        balance = 0.0
        sum_debit = 0.0
        sum_credit = 0.0
        for line in lines:
            sum_debit += line["debit"]
            sum_credit += line["credit"]
            if acct["nature"] == "deudora":
                balance += line["debit"] - line["credit"]
            else:
                balance += line["credit"] - line["debit"]
            line["balance"] = round(balance, 2)

        total_debit += sum_debit
        total_credit += sum_credit

        ledger_accounts.append({
            "account": acct,
            "lines": lines,
            "sum_debit": round(sum_debit, 2),
            "sum_credit": round(sum_credit, 2),
            "final_balance": round(balance, 2),
        })

    # Sort by account code
    ledger_accounts.sort(key=lambda a: a["account"]["code"])

    # Build account list for filter dropdown (only movimiento accounts)
    filter_accounts = sorted(
        [a for a in all_accounts if a.get("type") == "movimiento"],
        key=lambda a: a.get("code", "")
    )

    return render_template('accounting/general_ledger.html',
                           active_page='acc_reports',
                           ledger_accounts=ledger_accounts,
                           filter_accounts=filter_accounts,
                           account_filter=account_filter,
                           date_from=date_from,
                           date_to=date_to,
                           total_debit=round(total_debit, 2),
                           total_credit=round(total_credit, 2))


# =========================================================================
# ACTIVOS FIJOS
# =========================================================================
@web_accounting_bp.route('/accounting/fixed-assets')
@require_module('contabilidad')
def fixed_assets():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    assets = DatabaseService.get_fixed_assets(owner_uid, sandbox=sandbox)
    summary = FixedAssetService.get_assets_summary(owner_uid, sandbox=sandbox)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    return render_template('accounting/fixed_assets.html',
                           active_page='acc_assets',
                           assets=assets,
                           summary=summary,
                           accounts=accounts,
                           asset_categories=ASSET_CATEGORIES)


@web_accounting_bp.route('/accounting/fixed-assets/new', methods=['GET', 'POST'])
@require_module('contabilidad')
def new_fixed_asset():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    if request.method == 'POST':
        try:
            asset_data = {
                "name": request.form.get('name', ''),
                "assetType": request.form.get('assetType', 'tangible'),
                "category": request.form.get('category', 'equipos_computo'),
                "accountId": request.form.get('accountId'),
                "depreciationAccountId": request.form.get('depreciationAccountId'),
                "depreciationExpenseAccountId": request.form.get('depreciationExpenseAccountId'),
                "description": request.form.get('description', ''),
                "purchaseDate": request.form.get('purchaseDate', ''),
                "purchaseAmount": float(request.form.get('purchaseAmount', 0)),
                "supplierName": request.form.get('supplierName', ''),
                "location": request.form.get('location', ''),
                "responsible": request.form.get('responsible', ''),
                "usefulLife": int(request.form.get('usefulLife', 36)),
                "residualValue": float(request.form.get('residualValue', 0)),
                "depreciationPeriod": request.form.get('depreciationPeriod', 'mensual'),
            }
            asset = FixedAssetService.register_asset(owner_uid, asset_data, sandbox=sandbox)
            flash(f'✅ Activo fijo "{asset["name"]}" registrado exitosamente.', 'success')
            return redirect(url_for('web_accounting.fixed_assets'))
        except Exception as e:
            flash(f'❌ Error al registrar activo: {str(e)}', 'error')
    return render_template('accounting/fixed_asset_form.html',
                           active_page='acc_assets',
                           accounts=accounts,
                           asset_categories=ASSET_CATEGORIES,
                           is_edit=False)


@web_accounting_bp.route('/accounting/fixed-assets/<asset_id>')
@require_module('contabilidad')
def fixed_asset_detail(asset_id):
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    asset = DatabaseService.get_fixed_asset(owner_uid, asset_id, sandbox=sandbox)
    if not asset:
        flash('❌ Activo fijo no encontrado.', 'error')
        return redirect(url_for('web_accounting.fixed_assets'))
    return render_template('accounting/fixed_asset_detail.html',
                           active_page='acc_assets',
                           asset=asset)


@web_accounting_bp.route('/accounting/fixed-assets/<asset_id>/depreciate', methods=['POST'])
@require_module('contabilidad')
def depreciate_asset(asset_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    try:
        periods = int(request.form.get('periods', 1))
        result = FixedAssetService.register_depreciation(owner_uid, asset_id, periods=periods, sandbox=sandbox)
        flash(f'✅ Depreciación registrada: {result["amount"]}.', 'success')
    except ValueError as e:
        flash(f'❌ {str(e)}', 'error')
    except Exception as e:
        flash(f'❌ Error al registrar depreciación: {str(e)}', 'error')
    return redirect(url_for('web_accounting.fixed_asset_detail', asset_id=asset_id))


@web_accounting_bp.route('/accounting/fixed-assets/<asset_id>/dispose', methods=['POST'])
@require_module('contabilidad')
def dispose_asset(asset_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    try:
        disposal_data = {
            "disposalDate": request.form.get('disposalDate', ''),
            "disposalAmount": float(request.form.get('disposalAmount', 0)),
            "disposalReason": request.form.get('disposalReason', 'Venta'),
        }
        result = FixedAssetService.dispose_asset(owner_uid, asset_id, disposal_data, sandbox=sandbox)
        flash(f'✅ Activo dado de baja exitosamente.', 'success')
    except Exception as e:
        flash(f'❌ Error al dar de baja: {str(e)}', 'error')
    return redirect(url_for('web_accounting.fixed_asset_detail', asset_id=asset_id))


# =========================================================================
# CONFIGURACIÓN — TIPOS DE ENTRADA DE DIARIO
# =========================================================================
@web_accounting_bp.route('/accounting/settings/entry-types', methods=['GET', 'POST'])
@require_module('contabilidad')
def entry_types_settings():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    AccountingService.seed_default_entry_types(owner_uid)
    if request.method == 'POST':
        type_id = str(uuid.uuid4())
        type_data = {
            "id": type_id,
            "code": request.form.get('code', 'ED').strip(),
            "name": request.form.get('name', '').strip(),
            "description": request.form.get('description', '').strip(),
            "nextNumber": 1,
            "isSystem": False,
            "isActive": True,
        }
        DatabaseService.save_entry_type(owner_uid, type_id, type_data)
        flash('✅ Tipo de entrada de diario creado.', 'success')
        return redirect(url_for('web_accounting.entry_types_settings'))
    entry_types = DatabaseService.get_entry_types(owner_uid)
    return render_template('accounting/entry_types.html',
                           active_page='acc_settings',
                           entry_types=entry_types)


@web_accounting_bp.route('/accounting/settings/entry-types/<type_id>/delete', methods=['POST'])
@require_module('contabilidad')
def delete_entry_type(type_id):
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = _owner_uid()
    DatabaseService.delete_entry_type(owner_uid, type_id)
    return jsonify(success=True, message="Tipo de entrada eliminado.")


# =========================================================================
# SALDOS INICIALES
# =========================================================================
@web_accounting_bp.route('/accounting/initial-balances', methods=['GET', 'POST'])
@require_module('contabilidad')
def initial_balances():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)
    if request.method == 'POST':
        try:
            lines = []
            line_accounts = request.form.getlist('line_account[]')
            line_debits = request.form.getlist('line_debit[]')
            line_credits = request.form.getlist('line_credit[]')
            for i in range(len(line_accounts)):
                if not line_accounts[i]:
                    continue
                acc = DatabaseService.get_account(owner_uid, line_accounts[i])
                lines.append({
                    "accountId": line_accounts[i],
                    "accountCode": acc.get("code", "") if acc else "",
                    "accountName": acc.get("name", "") if acc else "",
                    "debit": float(line_debits[i]) if line_debits[i] else 0.0,
                    "credit": float(line_credits[i]) if line_credits[i] else 0.0,
                    "description": "Saldo inicial",
                })
            entry_data = {
                "entryType": "initial_balance",
                "date": request.form.get('date', datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "concept": "Saldos iniciales",
                "lines": lines,
                "createdBy": session['user'].get('uid', ''),
                "prefix": "SI",
            }
            entry = AccountingService.generate_entry(owner_uid, entry_data, sandbox=sandbox)
            flash(f'✅ Saldos iniciales registrados como {entry["number"]}.', 'success')
            return redirect(url_for('web_accounting.initial_balances'))
        except ValueError as e:
            flash(f'❌ {str(e)}', 'error')
        except Exception as e:
            flash(f'❌ Error: {str(e)}', 'error')
    return render_template('accounting/initial_balances.html',
                           active_page='acc_chart',
                           accounts=accounts)


# =========================================================================
# IMPORTAR SALDOS INICIALES DESDE EXCEL
# =========================================================================
@web_accounting_bp.route('/accounting/import-initial-balances', methods=['GET', 'POST'])
@require_module('contabilidad')
def import_initial_balances():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    AccountingService.seed_default_accounts(owner_uid)
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)

    if request.method == 'POST' and 'file' in request.files:
        try:
            f = request.files['file']
            if not f.filename.endswith(('.xlsx', '.xls')):
                flash('❌ El archivo debe ser un Excel (.xlsx o .xls).', 'error')
                return render_template('accounting/import_initial_balances.html', active_page='acc_chart', accounts=accounts)

            wb = openpyxl.load_workbook(f)
            ws = wb.active

            lines = []
            errors = []
            code_col = None
            name_col = None
            debit_col = None
            credit_col = None

            header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))] if ws.max_row else []
            for i, h in enumerate(header):
                h_str = str(h).strip().lower() if h else ''
                if h_str in ('codigo', 'código', 'code', 'cuenta'):
                    code_col = i
                elif h_str in ('nombre', 'name', 'descripcion', 'descripción'):
                    name_col = i
                elif h_str in ('debito', 'débito', 'debe', 'debit'):
                    debit_col = i
                elif h_str in ('credito', 'crédito', 'haber', 'credit'):
                    credit_col = i

            if code_col is None:
                flash('❌ No se encontró la columna "Código" en el archivo. Usa la plantilla descargable.', 'error')
                return render_template('accounting/import_initial_balances.html', active_page='acc_chart', accounts=accounts)

            row_num = 1
            for row in ws.iter_rows(min_row=2, values_only=True):
                row_num += 1
                if all(v is None or (isinstance(v, str) and v.strip() == '') for v in row):
                    continue
                code = str(row[code_col]).strip() if row[code_col] is not None else ''
                if not code:
                    errors.append(f'Fila {row_num}: código vacío')
                    continue
                debit_val = float(row[debit_col]) if row[debit_col] is not None else 0.0
                credit_val = float(row[credit_col]) if row[credit_col] is not None else 0.0
                if debit_val == 0 and credit_val == 0:
                    errors.append(f'Fila {row_num}: débito y crédito son 0')
                    continue

                account = None
                for a in accounts:
                    if a.get('code') == code:
                        account = a
                        break
                if not account:
                    errors.append(f'Fila {row_num}: cuenta "{code}" no encontrada en el catálogo')
                    continue

                lines.append({
                    "accountId": account["id"],
                    "accountCode": account.get("code", ""),
                    "accountName": account.get("name", ""),
                    "debit": debit_val,
                    "credit": credit_val,
                    "description": "Saldo inicial (importado)",
                })

            if not lines:
                flash('❌ No se pudieron leer líneas válidas del archivo.' + (' Errores: ' + '; '.join(errors[:5]) if errors else ''), 'error')
                return render_template('accounting/import_initial_balances.html', active_page='acc_chart', accounts=accounts)

            entry_data = {
                "entryType": "initial_balance",
                "date": request.form.get('date', datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "concept": "Saldos iniciales (importado por Excel)",
                "lines": lines,
                "createdBy": session['user'].get('uid', ''),
                "prefix": "SI",
            }
            entry = AccountingService.generate_entry(owner_uid, entry_data, sandbox=sandbox)
            msg = f'✅ {len(lines)} línea(s) importadas como {entry["number"]}.'
            if errors:
                msg += f' {len(errors)} advertencia(s): ' + '; '.join(errors[:3])
            flash(msg, 'success')
            return redirect(url_for('web_accounting.initial_balances'))

        except Exception as e:
            flash(f'❌ Error al procesar el archivo: {str(e)}', 'error')

    return render_template('accounting/import_initial_balances.html',
                           active_page='acc_chart',
                           accounts=accounts)


@web_accounting_bp.route('/accounting/import-initial-balances/template')
@require_module('contabilidad')
def download_initial_balances_template():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    owner_uid = _owner_uid()
    accounts = DatabaseService.get_chart_of_accounts(owner_uid)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Saldos Iniciales"

    ws.append(["Código", "Nombre", "Débito", "Crédito"])
    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 50
    ws.column_dimensions['C'].width = 16
    ws.column_dimensions['D'].width = 16

    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)
        cell.alignment = openpyxl.styles.Alignment(horizontal='center')

    for acc in accounts:
        if acc.get('type') == 'movimiento':
            ws.append([acc.get('code', ''), acc.get('name', ''), None, None])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='plantilla_saldos_iniciales.xlsx'
    )


# =========================================================================
# API — IMPORTAR ENTRADAS DE DIARIO DESDE EXCEL
# =========================================================================
@web_accounting_bp.route('/accounting/api/import-entries', methods=['POST'])
@require_module('contabilidad')
def api_import_entries():
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    try:
        data = request.get_json()
        if not data or "entries" not in data:
            return jsonify(success=False, error="No hay entradas para importar"), 400
        results = []
        for entry_data in data["entries"]:
            entry = AccountingService.generate_entry(owner_uid, {
                "entryType": entry_data.get("entryType", "standard"),
                "date": entry_data.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                "concept": entry_data.get("concept", "Importado"),
                "lines": entry_data.get("lines", []),
                "createdBy": session['user'].get('uid', 'system'),
                "prefix": entry_data.get("prefix", "ED"),
            }, sandbox=sandbox)
            results.append(entry["number"])
        return jsonify(success=True, entries_created=results)
    except ValueError as e:
        return jsonify(success=False, error=str(e)), 400
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


# =========================================================================
# CENTROS DE COSTO
# =========================================================================
@web_accounting_bp.route('/accounting/cost-centers')
@require_module('contabilidad')
def list_cost_centers():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    cost_centers = DatabaseService.get_cost_centers(owner_uid, sandbox=sandbox)
    return render_template('accounting/cost_centers.html',
                           active_page='acc_settings',
                           cost_centers=cost_centers)


@web_accounting_bp.route('/accounting/cost-centers/new', methods=['POST'])
@require_module('contabilidad')
def new_cost_center():
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    center_id = str(uuid.uuid4())
    center_dict = {
        "name": request.form.get('name', '').strip(),
        "code": request.form.get('code', '').strip(),
        "description": request.form.get('description', '').strip(),
        "isActive": True,
    }
    if not center_dict["name"]:
        flash('❌ El nombre del centro de costo es obligatorio.', 'error')
        return redirect(url_for('web_accounting.list_cost_centers'))
    DatabaseService.save_cost_center(owner_uid, center_id, center_dict, sandbox=sandbox)
    flash('✅ Centro de costo creado exitosamente.', 'success')
    return redirect(url_for('web_accounting.list_cost_centers'))


@web_accounting_bp.route('/accounting/cost-centers/<center_id>/edit', methods=['POST'])
@require_module('contabilidad')
def edit_cost_center(center_id):
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    existing = DatabaseService.get_cost_center(owner_uid, center_id, sandbox=sandbox)
    if not existing:
        flash('❌ Centro de costo no encontrado.', 'error')
        return redirect(url_for('web_accounting.list_cost_centers'))
    center_dict = {
        "name": request.form.get('name', '').strip(),
        "code": request.form.get('code', '').strip(),
        "description": request.form.get('description', '').strip(),
        "isActive": 'isActive' in request.form,
        "createdAt": existing.get("createdAt"),
    }
    if not center_dict["name"]:
        flash('❌ El nombre del centro de costo es obligatorio.', 'error')
        return redirect(url_for('web_accounting.list_cost_centers'))
    DatabaseService.save_cost_center(owner_uid, center_id, center_dict, sandbox=sandbox)
    flash('✅ Centro de costo actualizado.', 'success')
    return redirect(url_for('web_accounting.list_cost_centers'))


@web_accounting_bp.route('/accounting/cost-centers/<center_id>/delete', methods=['POST'])
@require_module('contabilidad')
def delete_cost_center_route(center_id):
    user = _auth()
    if not user:
        return redirect(url_for('web_auth.login'))
    if not check_permission('canAccounting'):
        return render_template('auth/restricted.html', required_permission="canAccounting")
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    DatabaseService.delete_cost_center(owner_uid, center_id, sandbox=sandbox)
    flash('✅ Centro de costo eliminado.', 'success')
    return redirect(url_for('web_accounting.list_cost_centers'))


@web_accounting_bp.route('/accounting/ajax/cost-centers', methods=['POST'])
@require_module('contabilidad')
def ajax_create_cost_center():
    """Endpoint AJAX para crear un centro de costo desde el formulario de documento."""
    user = _auth()
    if not user:
        return jsonify(success=False, error="No autorizado"), 401
    owner_uid = _owner_uid()
    sandbox = _sandbox()
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify(success=False, error="El nombre es obligatorio"), 400
    center_id = str(uuid.uuid4())
    center_dict = {
        "name": name,
        "code": (data.get('code') or '').strip(),
        "description": (data.get('description') or '').strip(),
        "isActive": True,
    }
    DatabaseService.save_cost_center(owner_uid, center_id, center_dict, sandbox=sandbox)
    return jsonify(success=True, id=center_id, name=name, code=center_dict["code"])


@web_accounting_bp.route('/accounting/fiscal-periods')
@require_module('contabilidad')
def fiscal_periods():
    if not check_permission('canAccounting'):
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
    owner_uid = session['user']['ownerUID']
    year = request.args.get('year', type=int, default=datetime.now(timezone.utc).year)
    from app.services.fiscal_period_service import FiscalPeriodService
    periods = FiscalPeriodService.list_periods(owner_uid, year)
    return render_template('accounting/fiscal_periods.html', active_page='acc_fiscal',
                          periods=periods, selected_year=year, product_name=_product_name())


@web_accounting_bp.route('/accounting/fiscal-periods/close', methods=['POST'])
@require_module('contabilidad')
def close_fiscal_period():
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    if not year or not month:
        return jsonify(success=False, error="Año y mes requeridos"), 400
    try:
        from app.services.fiscal_period_service import FiscalPeriodService
        user_name = session.get('user', {}).get('name', '')
        FiscalPeriodService.close_period(owner_uid, year, month, closed_by=user_name)
        from app.services.cache_service import CacheService
        CacheService.invalidate_accounting(owner_uid)
        return jsonify(success=True)
    except ValueError as e:
        return jsonify(success=False, error=str(e)), 400


@web_accounting_bp.route('/accounting/fiscal-periods/open', methods=['POST'])
@require_module('contabilidad')
def open_fiscal_period():
    if not check_permission('canAccounting') or session.get('user', {}).get('role') != 'owner':
        return jsonify(success=False, error="Solo el propietario puede reabrir períodos"), 403
    owner_uid = session['user']['ownerUID']
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    if not year or not month:
        return jsonify(success=False, error="Año y mes requeridos"), 400
    try:
        from app.services.fiscal_period_service import FiscalPeriodService
        period = FiscalPeriodService.get_period(owner_uid, year, month)
        if not period:
            return jsonify(success=False, error="Período no encontrado"), 404
        period['status'] = 'open'
        period['closedAt'] = None
        period['closedBy'] = None
        from app.services.db_service import db_firestore
        db_firestore.document(f"users/{owner_uid}/fiscal_periods/{year}-{month:02d}").set(period)
        from app.services.cache_service import CacheService
        CacheService.invalidate_accounting(owner_uid)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 400


@web_accounting_bp.route('/accounting/year-end-close')
@require_module('contabilidad')
def year_end_close():
    if not check_permission('canAccounting'):
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
    owner_uid = session['user']['ownerUID']
    sandbox = _sandbox()
    year = request.args.get('year', type=int, default=datetime.now(timezone.utc).year)
    from app.services.fiscal_closing_service import FiscalClosingService
    preview = FiscalClosingService.generate_closing_preview(owner_uid, year, sandbox=sandbox)
    return render_template('accounting/year_end_close.html', active_page='acc_fiscal',
                          preview=preview, selected_year=year, product_name=_product_name())


@web_accounting_bp.route('/accounting/year-end-close/execute', methods=['POST'])
@require_module('contabilidad')
def execute_year_end_close():
    if not check_permission('canAccounting') or session.get('user', {}).get('role') != 'owner':
        return jsonify(success=False, error="Solo el propietario puede ejecutar el cierre anual"), 403
    owner_uid = session['user']['ownerUID']
    sandbox = _sandbox()
    year = request.form.get('year', type=int)
    if not year:
        return jsonify(success=False, error="Año requerido"), 400
    try:
        from app.services.fiscal_closing_service import FiscalClosingService
        user_name = session.get('user', {}).get('name', '')
        result = FiscalClosingService.execute_year_close(owner_uid, year, performed_by=user_name, sandbox=sandbox)
        from app.services.cache_service import CacheService
        CacheService.invalidate_accounting(owner_uid)
        return jsonify(result)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 400


def _product_name():
    from app.brand import get_product_name
    return get_product_name()


@web_accounting_bp.route('/accounting/closing-checklist')
@require_module('contabilidad')
def closing_checklist():
    if not check_permission('canAccounting'):
        flash('No tienes permiso para acceder a esta sección.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
    owner_uid = session['user']['ownerUID']
    now = datetime.now(timezone.utc)
    year = request.args.get('year', type=int, default=now.year)
    month = request.args.get('month', type=int, default=now.month)
    from app.services.closing_checklist_service import ClosingChecklistService
    checklist = ClosingChecklistService.get_or_create_checklist(owner_uid, year, month)
    months_full = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                   "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    return render_template('accounting/closing_checklist.html', active_page='acc_fiscal',
                          checklist=checklist, selected_year=year, selected_month=month,
                          months=months_full, product_name=_product_name())


@web_accounting_bp.route('/accounting/closing-checklist/toggle', methods=['POST'])
@require_module('contabilidad')
def toggle_checklist_task():
    if not check_permission('canAccounting'):
        return jsonify(success=False, error="Permiso denegado"), 403
    owner_uid = session['user']['ownerUID']
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    task_id = request.form.get('task_id', '')
    if not year or not month or not task_id:
        return jsonify(success=False, error="Parámetros requeridos"), 400
    from app.services.closing_checklist_service import ClosingChecklistService
    user_name = session.get('user', {}).get('name', '')
    checklist = ClosingChecklistService.toggle_task(owner_uid, year, month, task_id, completed_by=user_name)
    return jsonify(success=True, progress=checklist['progress'])



