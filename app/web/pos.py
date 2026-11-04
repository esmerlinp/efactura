# app/web/pos.py
import re
import uuid
import html
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, g
from app.services.db_service import DatabaseService, _resolve_company_id
from app.services.contingency_sync_service import ContingencySyncService
from app.services.ecf_emission import EcfEmissionService
from app.services.dgii import DGIIService
from app.services.dgii_direct import DgiiDirectService
from app.utils.country_context import get_current_country
from app.utils.decorators import require_permission, check_permission
from app.brand import get_product_name
from app.models.fiscal_document_type import all_types as _all_fiscal_types, Family as _Family, by_code as _by_code
from app.utils.module_gate import module_enabled

web_pos_bp = Blueprint('web_pos', __name__)

# Métodos de pago admitidos por el POS. "Crédito" nunca genera movimiento de caja.
POS_ALLOWED_PAYMENT_METHODS = {
    "Efectivo", "Efectivo USD", "Tarjeta", "Transferencia", "Cheque", "Crédito"
}

_POS_DEMO_PRODUCTS = (
    {
        "id": "demo-arroz-selecto-5lb", "code": "DEMO-001", "barcode": "7460000000011",
        "name": "Arroz selecto 5 lb", "price": 285.00, "costPrice": 210.00,
        "categoryId": "alimentos", "type": "Bien", "unit": "Unidad",
        "itbisRate": 0.18, "totalStock": 48, "minStock": 6, "imageUrl": "",
    },
    {
        "id": "demo-aceite-vegetal-1l", "code": "DEMO-002", "barcode": "7460000000028",
        "name": "Aceite vegetal 1 litro", "price": 195.00, "costPrice": 150.00,
        "categoryId": "alimentos", "type": "Bien", "unit": "Unidad",
        "itbisRate": 0.18, "totalStock": 32, "minStock": 6, "imageUrl": "",
    },
    {
        "id": "demo-refresco-cola-2l", "code": "DEMO-003", "barcode": "7460000000035",
        "name": "Refresco Coca-Cola 2 litros", "price": 165.00, "costPrice": 120.00,
        "categoryId": "bebidas", "type": "Bien", "unit": "Unidad",
        "itbisRate": 0.18, "totalStock": 60, "minStock": 12, "imageUrl": "",
    },
    {
        "id": "demo-leche-entera-1l", "code": "DEMO-004", "barcode": "7460000000042",
        "name": "Leche entera 1 litro", "price": 98.00, "costPrice": 72.00,
        "categoryId": "lacteos", "type": "Bien", "unit": "Unidad",
        "itbisRate": 0.18, "totalStock": 24, "minStock": 8, "imageUrl": "",
    },
    {
        "id": "demo-azucar-crema-2lb", "code": "DEMO-005", "barcode": "7460000000059",
        "name": "Azúcar crema 2 lb", "price": 72.00, "costPrice": 54.00,
        "categoryId": "alimentos", "type": "Bien", "unit": "Unidad",
        "itbisRate": 0.18, "totalStock": 40, "minStock": 6, "imageUrl": "",
    },
    {
        "id": "demo-detergente-500g", "code": "DEMO-006", "barcode": "7460000000066",
        "name": "Detergente 500 g", "price": 135.00, "costPrice": 95.00,
        "categoryId": "limpieza", "type": "Bien", "unit": "Unidad",
        "itbisRate": 0.18, "totalStock": 18, "minStock": 4, "imageUrl": "",
    },
)


def _pos_demo_items():
    """Catálogo ficticio de demostración. Solo se sirve en sandbox y nunca se persiste."""
    items = []
    for raw in _POS_DEMO_PRODUCTS:
        item = dict(raw)
        item.update({
            "branchId": "default-sucursal-principal",
            "projectId": None,
            "rackLocation": "",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "codigoImpuesto": "",
            "tasaImpuestoAdicional": 0.0,
            "gradosAlcohol": 0.0,
            "cantidadReferencia": 0.0,
            "subcantidad": 1.0,
            "precioReferencia": 0.0,
            "isActive": True,
            "supplierName": "Demostración",
            "wholesalePrice": 0.0,
            "brand": "VykOne Demo",
            "maxStock": 0.0,
            "isDemo": True,
        })
        items.append(item)
    return items


def _pos_parse_rate(value, field_name, default=0.0):
    try:
        rate = float(value if value is not None and str(value).strip() != "" else default)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} inválido.")
    if rate < 0 or rate > 1:
        raise ValueError(f"{field_name} debe estar entre 0% y 100%.")
    return rate


def _pos_parse_quantity(value):
    try:
        qty = float(value if value is not None and str(value).strip() != "" else 1)
    except (TypeError, ValueError):
        raise ValueError("Cantidad inválida.")
    if qty <= 0:
        raise ValueError("La cantidad debe ser mayor a cero.")
    if qty > 1_000_000:
        raise ValueError("La cantidad excede el límite permitido.")
    return qty


def _pos_build_items(payload_items, catalog, sandbox):
    """Construye partidas confiables: precios e impuestos salen del catálogo, no del JS."""
    if not isinstance(payload_items, list) or not payload_items:
        raise ValueError("La venta no tiene productos. Recarga el terminal y vuelve a agregar el producto.")

    catalog_by_id = {str(it.get("id")): it for it in (catalog or []) if it.get("id")}
    parsed = []
    for raw in payload_items:
        if not isinstance(raw, dict):
            raise ValueError("Partida de producto inválida.")
        item_id = str(raw.get("id") or "").strip()
        if not item_id:
            raise ValueError("Cada partida debe tener un producto válido.")

        source = catalog_by_id.get(item_id)
        if not source:
            # En producción el producto debe existir en el catálogo. En sandbox se permite
            # compatibilidad con datos de prueba/legacy que no están en el catálogo.
            if not sandbox:
                raise ValueError(f"El producto '{item_id}' no existe en el catálogo activo.")
            source = {
                "id": item_id,
                "name": raw.get("name", ""),
                "price": raw.get("price", 0.0),
                "itbisRate": raw.get("itbisRate", 0.18),
                "type": raw.get("type", "Bien"),
                "unit": raw.get("unit", "Unidad"),
                "code": raw.get("code", ""),
            }

        if not source.get("isActive", True):
            raise ValueError(f"El producto '{source.get('name', item_id)}' está inactivo.")
        if item_id.startswith("demo-") and not sandbox:
            raise ValueError("Los productos de demostración no están permitidos en producción.")

        price = float(source.get("price") or 0.0)
        if price <= 0:
            raise ValueError(f"El producto '{source.get('name', item_id)}' no tiene un precio de venta válido.")

        qty = _pos_parse_quantity(raw.get("quantity"))
        discount_rate = _pos_parse_rate(raw.get("discountRate", 0.0), "Descuento de línea")
        itbis_rate = float(
            source.get("itbisRate")
            if source.get("itbisRate") is not None and str(source.get("itbisRate")).strip() != ""
            else 0.18
        )

        parsed.append({
            "id": item_id,
            "catalogId": item_id,
            "itemId": item_id,
            "code": source.get("code", ""),
            "name": source.get("name", ""),
            "price": price,
            "quantity": qty,
            "itbisRate": itbis_rate,
            "discountRate": discount_rate,
            "type": source.get("type", "Bien"),
            "unit": source.get("unit", "Unidad"),
            "codigoImpuesto": source.get("codigoImpuesto", ""),
            "tasaImpuestoAdicional": float(source.get("tasaImpuestoAdicional", 0.0) or 0.0),
            "gradosAlcohol": float(source.get("gradosAlcohol", 0.0) or 0.0),
            "cantidadReferencia": float(source.get("cantidadReferencia", 0.0) or 0.0),
            "subcantidad": float(source.get("subcantidad", 1.0) or 1.0),
            "precioReferencia": float(source.get("precioReferencia", 0.0) or 0.0),
            "imageUrl": source.get("imageUrl", ""),
        })
    return parsed


def _pos_normalize_payments(data, total, is_consumer_final):
    """Valida y normaliza pagos. Devuelve método predominante y saldo a crédito."""
    total = DGIIService.dgii_round(float(total or 0.0), 2)
    raw_payments = data.get("payments")
    payments = []

    if isinstance(raw_payments, list) and raw_payments:
        for idx, raw in enumerate(raw_payments):
            if not isinstance(raw, dict):
                raise ValueError(f"Pago #{idx + 1} inválido.")
            method = str(raw.get("method") or raw.get("paymentMethod") or "").strip()
            if method.lower() in ("credito", "crédito"):
                method = "Crédito"
            if method not in POS_ALLOWED_PAYMENT_METHODS:
                raise ValueError(f"Forma de pago no permitida: '{method}'.")
            try:
                amount = DGIIService.dgii_round(float(raw.get("amount", 0.0)), 2)
            except (TypeError, ValueError):
                raise ValueError(f"Monto inválido en el pago #{idx + 1}.")
            if amount <= 0:
                raise ValueError(f"El pago #{idx + 1} debe ser mayor a cero.")
            payments.append({
                "method": method,
                "amount": amount,
                "reference": str(raw.get("reference") or "").strip()[:80],
                "bank": str(raw.get("bank") or "").strip()[:80],
                "cashReceived": float(raw.get("cashReceived") or 0.0),
                "usdAmount": float(raw.get("usdAmount") or 0.0),
                "usdExchangeRate": float(raw.get("usdExchangeRate") or 1.0),
            })
    else:
        method = str(data.get("paymentMethod") or "Efectivo").strip()
        if method.lower() in ("credito", "crédito"):
            method = "Crédito"
        if method not in POS_ALLOWED_PAYMENT_METHODS:
            raise ValueError(f"Forma de pago no permitida: '{method}'.")
        payments.append({
            "method": method,
            "amount": total,
            "reference": str(data.get("paymentReference") or "").strip()[:80],
            "bank": str(data.get("bank") or "").strip()[:80],
            "cashReceived": float(data.get("cashReceived") or 0.0),
            "usdAmount": float(data.get("usdAmount") or 0.0),
            "usdExchangeRate": float(data.get("usdExchangeRate") or 1.0),
        })

    paid = DGIIService.dgii_round(sum(p["amount"] for p in payments), 2)
    if abs(paid - total) > 0.01:
        raise ValueError(
            f"La suma de los pagos (RD$ {paid:,.2f}) no coincide con el total (RD$ {total:,.2f})."
        )

    credit_amount = DGIIService.dgii_round(
        sum(p["amount"] for p in payments if p["method"] == "Crédito"), 2
    )
    if credit_amount > 0 and is_consumer_final:
        raise ValueError("Las ventas a crédito requieren un cliente registrado con RNC/Cédula.")

    primary = max(payments, key=lambda p: p["amount"]) if payments else payments[0]
    return {
        "payments": payments,
        "primary_method": primary["method"],
        "payment_type": "02 - Crédito" if credit_amount > 0 else "01 - Contado",
        "credit_amount": credit_amount,
        "paid_amount": DGIIService.dgii_round(total - credit_amount, 2),
    }


def _pos_itbis_breakdown(calculated_items):
    breakdown = {}
    for item in calculated_items:
        rate = float(item.get("itbisRate", 0.0) or 0.0)
        key = f"{rate:.4f}"
        bucket = breakdown.setdefault(key, {"rate": rate, "base": 0.0, "itbis": 0.0})
        bucket["base"] = DGIIService.dgii_round(bucket["base"] + float(item.get("subtotal", 0.0)), 2)
        bucket["itbis"] = DGIIService.dgii_round(bucket["itbis"] + float(item.get("itbisAmount", 0.0)), 2)
    return sorted(breakdown.values(), key=lambda b: b["rate"], reverse=True)


@web_pos_bp.before_request
def _check_pos_module():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    if not module_enabled('pos'):
        if request.is_json or request.headers.get('Accept') == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                "success": False,
                "error": {
                    "code": "MODULE_DISABLED",
                    "message": "El módulo 'POS (Punto de Venta)' no está contratado en tu plan actual."
                }
            }), 403
        return render_template(
            'auth/restricted.html',
            feature_name="POS (Punto de Venta)",
            required_permission="module_pos",
            custom_message="El módulo <strong>POS (Punto de Venta)</strong> no está incluido en tu plan actual. "
                           "Contacta a soporte para información sobre mejoras de plan."
        ), 403



@web_pos_bp.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def require_open_shift(f):
    """Decorador para asegurar que el cajero tiene una caja abierta antes de vender."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('web_auth.login'))
        if not check_permission('canManagePOS'):
            return render_template('auth/restricted.html', feature_name="Punto de Venta", required_permission="canManagePOS"), 403
        
        owner_uid = session['user']['ownerUID']
        company_id = session.get('selected_company_id')
        user_uid = session['user']['uid']
        sandbox = session.get('is_sandbox_mode', True)
        
        open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
        if not open_shift:
            flash('Debe abrir un turno de caja para operar el Punto de Venta. Si estaba operando, es posible que un supervisor haya tomado el control.', 'warning')
            return redirect(url_for('web_pos.pos_dashboard'))
        
        if open_shift.get('status') == 'CLOSING':
            flash('Su caja está en proceso de cierre (Arqueo en curso). No puede realizar ventas.', 'warning')
            return redirect(url_for('web_pos.pos_dashboard'))
            
        return f(*args, **kwargs)
    return decorated_function


@web_pos_bp.route('/pos')
@require_permission('canManagePOS', 'Punto de Venta')
def pos_dashboard():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener cajas registradoras
    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    
    # Verificar si el usuario ya tiene un turno abierto
    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
    
    current_register = None
    transactions = []
    pending_consolidation_count = 0
    if open_shift:
        current_register = next((r for r in registers if r['id'] == open_shift['registerId']), None)
        transactions = DatabaseService.get_cash_transactions(owner_uid, open_shift['id'], company_id=company_id, sandbox=sandbox)
        company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        if company and company.get('consolidationEnabled'):
            pending = DatabaseService.get_pending_consolidation_invoices(owner_uid, open_shift['id'], company_id=company_id, sandbox=sandbox)
            pending_consolidation_count = len(pending)

    return render_template(
        'pos/dashboard.html',
        active_page='pos',
        registers=registers,
        open_shift=open_shift,
        current_register=current_register,
        transactions=transactions,
        pending_consolidation_count=pending_consolidation_count
    )



@web_pos_bp.route('/pos/shift/open', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def open_shift():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    register_id = request.form.get('registerId')
    try:
        opening_amount = float(request.form.get('openingAmount', 0.0))
    except ValueError:
        opening_amount = 0.0
        
    if not register_id:
        flash('Seleccione una caja registradora válida.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))
        
    # Verificar si ya tiene un turno abierto
    existing_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
    if existing_shift:
        flash('Ya tiene un turno de caja activo.', 'warning')
        return redirect(url_for('web_pos.pos_terminal'))
        
    shift_dict = {
        "registerId": register_id,
        "openedByUserId": user_uid,
        "openedByUserEmail": session['user']['email'],
        "openingAmount": opening_amount
    }
    
    res = DatabaseService.open_cash_shift(owner_uid, shift_dict, company_id=company_id, sandbox=sandbox)
    if res:
        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_POS,
            entity_id=res,
            entity_label=f"Apertura de turno de caja (Monto inicial: RD$ {opening_amount:.2f})",
            user_session=session.get('user', {}),
            after=shift_dict,
            sandbox=sandbox
        )
        flash('Caja abierta correctamente. ¡Buen turno!', 'success')
        return redirect(url_for('web_pos.pos_terminal'))
    else:
        flash('Error al abrir la caja registradora.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))


@web_pos_bp.route('/pos/shift/initiate_close', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def initiate_close_shift():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
    if not open_shift:
        return jsonify({"success": False, "error": "No tiene ningún turno de caja activo."}), 400

    if open_shift.get('status') == 'CLOSING':
        return jsonify({"success": True, "message": "Ya estaba en proceso de cierre."})

    res = DatabaseService.initiate_close_cash_shift(owner_uid, open_shift['id'], company_id=company_id, sandbox=sandbox)
    if res:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo iniciar el proceso de cierre."}), 500


@web_pos_bp.route('/pos/shift/close', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def close_shift():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
    if not open_shift:
        if request.is_json:
            return jsonify({"success": False, "error": "No tiene ningún turno de caja activo para cerrar."}), 400
        flash('No tiene ningún turno de caja activo para cerrar.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))

    # --- CONSOLIDACIÓN AUTOMÁTICA AL CIERRE ---
    pending = DatabaseService.get_pending_consolidation_invoices(owner_uid, open_shift['id'], company_id=company_id, sandbox=sandbox)
    if pending:
        try:
            _emit_consolidated_ecf(owner_uid, open_shift['id'], pending, sandbox)
        except Exception as cons_err:
            print(f"⚠️ Error al emitir comprobante consolidado al cierre: {cons_err}")
    # -----------------------------------------

    declared_data = None
    if request.is_json:
        data = request.json or {}
        declared_amount = float(data.get('declaredAmount', 0.0))
        declared_data = {
            "declaredCash": float(data.get('declaredCash', 0.0)),
            "declaredCard": float(data.get('declaredCard', 0.0)),
            "declaredTransfer": float(data.get('declaredTransfer', 0.0)),
            "declaredUSD": float(data.get('declaredUSD', 0.0)),
            "usdExchangeRate": float(data.get('usdExchangeRate', 58.50)),
            "cashDenominations": data.get('cashDenominations', {}),
            "usdDenominations": data.get('usdDenominations', {}),
            "cardLoteNumber": str(data.get('cardLoteNumber', '')).strip()
        }
    else:
        try:
            declared_amount = float(request.form.get('declaredAmount', 0.0))
        except ValueError:
            declared_amount = 0.0

    is_supervisor = (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor'))
    status = "CLOSED" if is_supervisor else "PENDING_AUDIT"

    res = DatabaseService.close_cash_shift(
        owner_uid, open_shift['id'], declared_amount, company_id=company_id, sandbox=sandbox,
        status=status,
        supervisor_uid=user_uid if is_supervisor else None,
        supervisor_email=session['user']['email'] if is_supervisor else None,
        declared_data=declared_data
    )
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_UPDATE,
            module=MODULE_POS,
            entity_id=open_shift['id'],
            entity_label=f"Cierre de turno de caja (Declarado: RD$ {declared_amount:.2f})",
            user_session=session.get('user', {}),
            before=open_shift,
            after=res,
            sandbox=sandbox
        )
        
        if request.is_json:
            return jsonify({
                "success": True,
                "shiftId": open_shift['id'],
                "status": status,
                "difference": res["difference"]
            })
            
        if status == "CLOSED":
            diff = res["difference"]
            if abs(diff) < 0.01:
                flash('Caja cerrada exitosamente. ¡Cuadre perfecto!', 'success')
            elif diff > 0:
                flash(f'Caja cerrada con SOBRANTE de RD$ {diff:,.2f}.', 'warning')
            else:
                flash(f'Caja cerrada con FALTANTE de RD$ {abs(diff):,.2f}.', 'error')
        else:
            flash('Turno finalizado y enviado a revisión. Pendiente de auditoría por un supervisor.', 'info')
    else:
        if request.is_json:
            return jsonify({"success": False, "error": "Ocurrió un error al procesar el cierre de caja."}), 500
        flash('Ocurrió un error al procesar el cierre de caja.', 'error')

    return redirect(url_for('web_pos.pos_dashboard'))


def _emit_consolidated_ecf(owner_uid, shift_id, pending_invoices, sandbox):
    """Función interna: agrupa las facturas pendientes y emite un único E32 consolidado."""
    from datetime import date as dt_date, timezone

    today_str = dt_date.today().strftime('%d/%m/%Y')
    total_sum = sum(inv['total'] for inv in pending_invoices)
    subtotal_sum = sum(inv['subtotal'] for inv in pending_invoices)
    itbis_sum = sum(inv['totalITBIS'] for inv in pending_invoices)
    invoice_ids = [inv['id'] for inv in pending_invoices]

    consolidado_id = str(uuid.uuid4())
    consolidado_number = f"CONS-{datetime.now(timezone.utc).strftime('%y%m%d%H%M%S')}"

    # Item único según norma DGII: descripción genérica de ventas menores del día
    consolidated_item = {
        "id": str(uuid.uuid4()),
        "name": f"Ventas Globales del Día {today_str}",
        "type": "Servicio",
        "price": subtotal_sum,
        "quantity": 1,
        "itbisRate": 0.18,
        "discountRate": 0.0,
        "subtotal": subtotal_sum,
        "itbisAmount": itbis_sum,
        "total": total_sum,
        "codigoImpuesto": "",
        "tasaImpuestoAdicional": 0.0,
        "gradosAlcohol": 0.0,
        "cantidadReferencia": 0.0,
        "subcantidad": 1.0,
        "precioReferencia": 0.0,
        "isc_especifico_amount": 0.0,
        "isc_advalorem_amount": 0.0,
        "otros_impuestos_amount": 0.0,
    }

    consolidado_dict = {
        "invoiceNumber": consolidado_number,
        "date": datetime.now(timezone.utc).isoformat(),
        "dueDate": datetime.now(timezone.utc).isoformat(),
        "clientId": "default",
        "clientName": "Consumidor Final",
        "clientRNC": "000000000",
        "status": "Cobrada",
        "ecfType": "Factura de Consumo (E32)",
        "currency": "DOP",
        "paymentType": "01 - Contado",
        "paymentMethod": "Mixto",
        "incomeType": "01 - Ingresos por operaciones",
        "subtotal": subtotal_sum,
        "totalITBIS": itbis_sum,
        "total": total_sum,
        "netPayable": total_sum,
        "isQuotation": False,
        "isConvertedToInvoice": False,
        "items": [consolidated_item],
        "stockReduced": True,  # Stock ya fue descontado en las ventas individuales
        "posShiftId": shift_id,
        "isConsolidado": True,
        "consolidatedInvoiceIds": invoice_ids,
        "isSyncedWithDGII": False,
        "invoiceCount": len(pending_invoices),
    }

    DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, company_id=company_id, sandbox=sandbox)

    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    encf_consolidado = consolidado_number  # fallback
    is_synced = False
    dgii_status = None
    emision_mode = None
    try:
        res = EcfEmissionService.emit_electronic_comprobante(company, consolidado_dict, sandbox=sandbox)
        if res and res.get('success'):
            encf_consolidado = res.get('encf', consolidado_number)
            consolidado_dict["encf"] = encf_consolidado
            consolidado_dict["xmlSignature"] = res.get('xmlSignature', '')
            consolidado_dict["qrCodeURL"] = res.get('qrCodeURL', '')
            consolidado_dict["trackId"] = res.get("trackId") or res.get("track_id") or ""
            consolidado_dict["codigoSeguridad"] = res.get("codigoSeguridad") or ""
            pending_dgii = res.get("status") == "PENDING" or res.get("mode") == "FALLBACK"
            is_synced = (res.get("mode") in ("API", "RFCE_API") and res.get("status") != "PENDING")
            emision_mode = res.get("mode", "API")
            dgii_status = res.get("dgiiStatus") or ("PENDING" if pending_dgii else "ACCEPTED")
            consolidado_dict["isSyncedWithDGII"] = is_synced
            consolidado_dict["emisionMode"] = emision_mode
            consolidado_dict["dgiiStatus"] = dgii_status
            consolidado_dict["contingencyEmittedAt"] = datetime.now(timezone.utc).isoformat() if emision_mode == "FALLBACK" else None
            consolidado_dict["status"] = "Pendiente DGII" if pending_dgii else "Cobrada"
            DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, company_id=company_id, sandbox=sandbox)
        else:
            emision_mode = "FALLBACK"
            dgii_status = "CONTINGENCY"
            consolidado_dict["emisionMode"] = "FALLBACK"
            consolidado_dict["dgiiStatus"] = "CONTINGENCY"
            consolidado_dict["isSyncedWithDGII"] = False
            consolidado_dict["contingencyEmittedAt"] = datetime.now(timezone.utc).isoformat()
            consolidado_dict["status"] = "Pendiente DGII"
            DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, company_id=company_id, sandbox=sandbox)
    except Exception as ecf_err:
        print(f"⚠️ Error al emitir e-CF consolidado: {ecf_err}")
        emision_mode = "FALLBACK"
        dgii_status = "CONTINGENCY"
        consolidado_dict["emisionMode"] = "FALLBACK"
        consolidado_dict["dgiiStatus"] = "CONTINGENCY"
        consolidado_dict["isSyncedWithDGII"] = False
        consolidado_dict["contingencyEmittedAt"] = datetime.now(timezone.utc).isoformat()
        consolidado_dict["status"] = "Pendiente DGII"
        DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, company_id=company_id, sandbox=sandbox)

    # Marcar todas las facturas individuales como Consolidadas
    DatabaseService.mark_invoices_consolidated(
        owner_uid,
        invoice_ids,
        encf_consolidado,
        consolidado_number, company_id=company_id,
        pending_invoices=pending_invoices,
        is_synced=is_synced,
        dgii_status=dgii_status,
        emision_mode=emision_mode,
        sandbox=sandbox
    )

    print(f"✅ [Consolidado] Emitido {consolidado_number} cubriendo {len(invoice_ids)} ventas. ENCF: {encf_consolidado}")
    return encf_consolidado



@web_pos_bp.route('/pos/shift/transaction', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def add_manual_transaction():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
    if not open_shift:
        return jsonify({"success": False, "error": "No hay un turno de caja abierto."}), 400
        
    tx_type = request.form.get('type')  # IN o OUT
    try:
        amount = float(request.form.get('amount', 0.0))
    except ValueError:
        amount = 0.0
    notes = request.form.get('notes', '')
    
    if amount <= 0:
        return jsonify({"success": False, "error": "El monto debe ser mayor a cero."}), 400
        
    tx_dict = {
        "shiftId": open_shift['id'],
        "type": tx_type,
        "amount": amount,
        "paymentMethod": "Efectivo",
        "notes": notes
    }
    
    res = DatabaseService.register_cash_transaction(owner_uid, tx_dict, company_id=company_id, sandbox=sandbox)
    if res:
        flash('Movimiento de caja registrado.', 'success')
        return redirect(url_for('web_pos.pos_dashboard'))
    else:
        flash('Fallo al registrar el movimiento de caja.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))

# =========================================================================
# ACCIONES DE SUPERVISIÓN
# =========================================================================

def _get_supervisor_data():
    return session['user']['uid'], session['user']['name']

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/take_control', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_take_control(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.take_control_shift(owner_uid, shift_id, sup_uid, sup_name, reason, comments, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Supervisor tomó control de caja (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo tomar control del turno."})

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/force_close', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_force_close(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.force_close_shift(owner_uid, shift_id, sup_uid, sup_name, reason, comments, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Cierre forzado de caja (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments, "status": "FORCED_CLOSED"}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo forzar el cierre del turno."})

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/close_under_review', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_close_under_review(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    declared_amount = float(data.get('declaredAmount', 0.0))
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.close_shift_under_review(owner_uid, shift_id, sup_uid, sup_name, reason, comments, declared_amount, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Cierre de caja bajo investigación (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments, "status": "CLOSED_UNDER_REVIEW"}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo cerrar el turno bajo investigación."})

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/reopen', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_reopen(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.reopen_shift(owner_uid, shift_id, sup_uid, sup_name, reason, comments, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Reapertura de turno (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments, "status": "REOPENED"}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Solo se pueden reabrir turnos cerrados en el día de hoy y que no hayan sido auditados."})

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/transfer', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_transfer(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    new_cashier_uid = data.get('newCashierUid')
    new_cashier_email = data.get('newCashierEmail')
    
    if not new_cashier_uid:
         return jsonify({"success": False, "error": "Cajero destino requerido."}), 400
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.transfer_shift(owner_uid, shift_id, sup_uid, sup_name, new_cashier_uid, new_cashier_email, reason, comments, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Transferencia de turno a {new_cashier_email} (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo transferir el turno."})

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/log_incident', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_log_incident(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.log_shift_incident(owner_uid, shift_id, sup_uid, sup_name, reason, comments, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Incidencia registrada en turno (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo registrar la incidencia."})

@web_pos_bp.route('/pos/shift/<shift_id>/supervisor/extend', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def sup_extend(shift_id):
    if not (session['user'].get('role') == 'owner' or check_permission('isPosSupervisor')):
        return jsonify({"success": False, "error": "No tienes permisos de supervisor."}), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.json or {}
    reason = data.get('reason', '')
    comments = data.get('comments', '')
    
    sup_uid, sup_name = _get_supervisor_data()
    
    res = DatabaseService.authorize_shift_extension(owner_uid, shift_id, sup_uid, sup_name, reason, comments, sandbox, company_id=company_id)
    if res:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid, action=ACTION_UPDATE, module=MODULE_POS, entity_id=shift_id,
            entity_label=f"Extensión de turno autorizada (Motivo: {reason})",
            user_session=session.get('user', {}), after={"reason": reason, "comments": comments}, sandbox=sandbox
        )
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "No se pudo autorizar la extensión."})


@web_pos_bp.route('/pos/terminal')
@require_open_shift
def pos_terminal():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener catálogo de productos para la venta rápida
    items = DatabaseService.get_items(owner_uid, company_id=company_id, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id')) or []
    
    # Filtrar solo bienes físicos o servicios del catálogo activos
    active_items = [it for it in items if it.get('price', 0.0) > 0 and it.get('isActive', True)]
    demo_mode = False
    if not active_items and sandbox:
        active_items = _pos_demo_items()
        demo_mode = True

    categories = DatabaseService.get_categories(
        owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'),
        project_id=g.get('project_id'), company_id=company_id
    ) or []
    if demo_mode:
        existing_category_ids = {c.get('id') for c in categories}
        for demo_cat in (
            {"id": "alimentos", "name": "Alimentos"},
            {"id": "bebidas", "name": "Bebidas"},
            {"id": "lacteos", "name": "Lácteos"},
            {"id": "limpieza", "name": "Limpieza"},
        ):
            if demo_cat["id"] not in existing_category_ids:
                categories.append(demo_cat)

    branches = DatabaseService.get_branches(owner_uid, company_id=company_id, sandbox=sandbox) or []
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
    
    # Obtener supervisores (propietario + colaboradores con permiso)
    supervisors = []
    owner_profile = DatabaseService.get_user_profile(owner_uid, company_id=company_id)
    if owner_profile:
        supervisors.append({
            "uid": owner_uid,
            "name": f"{owner_profile.get('name', 'Propietario')} (Propietario)"
        })
    team = DatabaseService.get_team_members(owner_uid, company_id=company_id)
    for member in team:
        if member.get('permissions', {}).get('isPosSupervisor', False):
            supervisors.append({
                "uid": member['uid'],
                "name": member.get('name', 'Supervisor')
            })
            
    _ecf_types = [t for t in _all_fiscal_types() if t.family == _Family.ECF]
    pos_ecf_types = [
        {"code": t.code, "label": t.label, "label_with_code": t.label_with_code}
        for t in _ecf_types if t.code in ("E31", "E32")
    ]
    
    # Resolver caja y almacén activo del turno
    user_uid = session['user']['uid']
    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)
    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    register = next((r for r in registers if r['id'] == open_shift.get('registerId')), None) if open_shift else None
    
    warehouses = DatabaseService.get_warehouses(owner_uid, company_id=company_id, sandbox=sandbox) or []
    pos_branch_id = register.get('branchId') if register else (session.get('selected_branch_id') or 'default-sucursal-principal')
    default_wh_id = (register.get('warehouseId') if register else '') or DatabaseService.get_default_warehouse(
        owner_uid, company_id=company_id, sandbox=sandbox, branch_id=pos_branch_id
    )
    current_warehouse = next((w for w in warehouses if w['id'] == default_wh_id), None)

    return render_template(
        'pos/terminal.html',
        active_page='pos',
        items=active_items,
        categories=categories,
        branches=branches,
        company=company,
        supervisors=supervisors,
        ecf_types=_ecf_types,
        pos_ecf_types=pos_ecf_types,
        open_shift=open_shift,
        register=register,
        warehouses=warehouses,
        current_warehouse=current_warehouse,
        pos_warehouse_id=default_wh_id,
        pos_branch_id=pos_branch_id,
        demo_mode=demo_mode,
        sandbox=sandbox,
    )


@web_pos_bp.route('/pos/client/lookup', methods=['POST'])
def pos_client_lookup():
    """Busca primero el cliente local y luego valida el RNC/cédula en DGII.

    La consulta no requiere turno abierto porque solo obtiene datos y no
    modifica caja ni emite una factura.
    """
    if 'user' not in session:
        return jsonify({"success": False, "error": "Sesión requerida."}), 401
    if not check_permission('canManagePOS'):
        return jsonify({"success": False, "error": "No autorizado para operar el POS."}), 403
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json(silent=True) or {}
    raw_rnc = data.get('rnc') or data.get('rncCedula') or data.get('taxId') or data.get('query') or request.form.get('rnc', '')
    rnc = re.sub(r'\D', '', str(raw_rnc or ''))
    if not rnc:
        return jsonify({"success": False, "error": "El RNC/Cédula es requerido."}), 400
    if len(rnc) not in (9, 11):
        return jsonify({"success": False, "error": "El RNC debe tener 9 dígitos o la cédula 11 dígitos."}), 400
        
    # 1. Buscar localmente en Firestore
    client = DatabaseService.get_client_by_rnc(owner_uid, rnc, company_id=company_id, sandbox=sandbox)
    if client:
        return jsonify({
            "success": True,
            "source": "local",
            "client": client
        })
        
    # 2. Buscar en el directorio de la DGII (Megaplus)
    try:
        res = DGIIService.validate_and_fetch_rnc(rnc) or {}
    except Exception as exc:
        return jsonify({"success": False, "error": f"No se pudo consultar la DGII: {exc}"}), 502
    
    if not res.get('error') and (res.get('razon_social') or res.get('name') or res.get('razonSocial')):
        razon_social = res.get('razon_social') or res.get('razonSocial') or res.get('name')
        
        return jsonify({
            "success": True,
            "source": "dgii",
            "client": {
                "id": "dgii-lookup",
                "rnc": rnc,
                "razonSocial": razon_social,
                "name": razon_social,
                "email": (res.get('email') or '').strip(),
                "telefono": (res.get('telefono') or '').strip(),
                "direccion": (res.get('direccion') or res.get('address') or '').strip(),
                "source": "dgii",
                "isDgiiLookup": True,
            },
            "requiresRegistration": True,
        })
    else:
        return jsonify({
            "success": False,
            "error": "Cliente no encontrado localmente ni en la DGII."
        })


@web_pos_bp.route('/pos/cart/quote', methods=['POST'])
@require_open_shift
def pos_cart_quote():
    """Calcula totales autoritativos del carrito con la misma lógica fiscal de la factura."""
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    data = request.get_json(silent=True) or {}

    branch_id = data.get('branchId') or session.get('selected_branch_id') or g.get('branch_id')
    catalog = DatabaseService.get_items(
        owner_uid, company_id=company_id, sandbox=sandbox,
        branch_id=branch_id, project_id=g.get('project_id')
    ) or []
    if not catalog and sandbox:
        catalog = _pos_demo_items()

    try:
        parsed_items = _pos_build_items(data.get('items'), catalog, sandbox)
        global_rate = _pos_parse_rate(data.get('discountRate', 0.0), "Descuento global")
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    calcs = DGIIService.calculate_invoice_totals(parsed_items, discount_rate=global_rate)
    return jsonify({
        "success": True,
        "subtotal": calcs["subtotal"],
        "subtotalRaw": calcs["subtotal_raw"],
        "discountAmount": calcs["total_discount"],
        "globalDiscount": calcs["global_discount"],
        "totalITBIS": calcs["total_itbis"],
        "total": calcs["total"],
        "netPayable": calcs["net_payable"],
        "itbisBreakdown": _pos_itbis_breakdown(calcs["items"]),
        "items": [
            {
                "id": it.get("id"),
                "quantity": it.get("quantity"),
                "price": it.get("price"),
                "discountRate": it.get("discountRate"),
                "subtotal": it.get("subtotal"),
                "itbisAmount": it.get("itbisAmount"),
                "total": it.get("total"),
            }
            for it in calcs["items"]
        ],
    })


@web_pos_bp.route('/pos/invoice/new', methods=['POST'])
@require_open_shift
def create_pos_sale():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, company_id=company_id, sandbox=sandbox)

    data = request.get_json(silent=True) or {}
    idempotency_key = request.headers.get('Idempotency-Key') or data.get('idempotencyKey') or data.get('idempotency_key')
    if idempotency_key:
        record = DatabaseService.get_idempotency_record(owner_uid, idempotency_key, company_id=company_id, sandbox=sandbox)
        if record and record.get("response"):
            status_code = int(record.get("statusCode", 200))
            return jsonify(record["response"]), status_code

    ecf_type = data.get('ecfType', _by_code("E32").label_with_code)
    if ecf_type not in ['Factura de Consumo (E32)', 'Factura de Crédito Fiscal (E31)']:
        return jsonify({"success": False, "error": f"El Punto de Venta solo permite emitir Factura de Consumo (E32) o Crédito Fiscal (E31). El tipo '{ecf_type}' está restringido."}), 400

    # Sucursal: se valida contra las sucursales reales de la empresa cuando existan.
    explicit_branch_id = data.get('branchId') or session.get('selected_branch_id') or g.get('branch_id')
    branch_id = explicit_branch_id or 'default-sucursal-principal'
    branches = DatabaseService.get_branches(owner_uid, company_id=company_id, sandbox=sandbox) or []
    if explicit_branch_id and branches:
        valid_branch_ids = {b.get('id') for b in branches}
        if explicit_branch_id not in valid_branch_ids:
            return jsonify({"success": False, "error": "La sucursal seleccionada no es válida."}), 400

    # Catálogo autoritativo: precios, impuestos y estado salen de la base de datos.
    catalog = DatabaseService.get_items(
        owner_uid, company_id=company_id, sandbox=sandbox,
        branch_id=branch_id, project_id=g.get('project_id')
    ) or []
    if not catalog and sandbox:
        catalog = _pos_demo_items()

    try:
        parsed_items = _pos_build_items(data.get('items'), catalog, sandbox)
        global_discount_rate = _pos_parse_rate(data.get('discountRate', 0.0), "Descuento global")
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    calcs = DGIIService.calculate_invoice_totals(parsed_items, discount_rate=global_discount_rate)
    if float(calcs.get('total') or 0.0) <= 0:
        return jsonify({"success": False, "error": "El total de la venta debe ser mayor a cero."}), 400

    # Cliente: nombre y RNC se toman del registro, nunca del navegador.
    client_id = data.get('clientId') or 'default'
    client_name = 'Consumidor Final'
    client_rnc = '000000000'
    client_email = ''
    client_project_id = None
    if client_id and client_id != 'default':
        client = DatabaseService.get_client(owner_uid, client_id, company_id=company_id, sandbox=sandbox)
        if not client:
            return jsonify({"success": False, "error": "El cliente seleccionado no existe."}), 400
        client_name = client.get('razonSocial') or client.get('name') or 'Cliente'
        client_rnc = re.sub(r'\D', '', str(client.get('rnc') or client.get('identification') or ''))
        client_email = (client.get('email') or '').strip()
        client_project_id = client.get('projectId')

    is_consumer_final = (
        client_id == 'default' or not client_rnc or client_rnc == '000000000'
    )
    if ecf_type == 'Factura de Crédito Fiscal (E31)' and (is_consumer_final or len(client_rnc) < 9):
        return jsonify({
            "success": False,
            "error": "La Factura de Crédito Fiscal (E31) requiere un cliente registrado con RNC o Cédula válida."
        }), 400

    try:
        payment_info = _pos_normalize_payments(data, calcs['total'], is_consumer_final)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    invoice_id = str(uuid.uuid4())
    invoice_number = f"POS-{datetime.now(timezone.utc).strftime('%y%m%d%H%M%S')}"

    # --- Determinar si aplica modo consolidado ---
    # Condiciones DGII: E32, Consumidor Final (RNC 000000000), total < monto configurable de la empresa
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
    consolidation_enabled = bool(company.get('consolidationEnabled', False))
    consolidation_threshold = float(company.get('consolidationThreshold') or 250000.0)
    qualifies_for_consolidation = (
        consolidation_enabled
        and ecf_type == 'Factura de Consumo (E32)'
        and is_consumer_final
        and calcs['total'] < consolidation_threshold
    )
    # --- Determinar si aplica para RUI ---
    # Elegible para RUI = consumidor final, E32, no tiene RNC de cliente
    include_in_rui = (
        ecf_type == 'Factura de Consumo (E32)'
        and is_consumer_final
    )
    # -------------------------------------------


    # --- Cobro en USD (informativo; la factura siempre se contabiliza en DOP) ---
    usd_payments = [p for p in payment_info['payments'] if float(p.get('usdAmount') or 0.0) > 0]
    usd_amount = DGIIService.dgii_round(sum(float(p['usdAmount']) for p in usd_payments), 2) if usd_payments else 0.0
    usd_rate = float(usd_payments[0].get('usdExchangeRate') or 1.0) if usd_payments else 1.0

    # Determinar y validar almacén de despacho para control de inventario
    warehouses = DatabaseService.get_warehouses(owner_uid, company_id=company_id, sandbox=sandbox) or []
    warehouse_id = data.get('warehouseId')
    if warehouse_id:
        if warehouses:
            warehouse = next((w for w in warehouses if w.get('id') == warehouse_id), None)
            if not warehouse:
                return jsonify({"success": False, "error": "El almacén seleccionado no es válido."}), 400
            warehouse_branch = warehouse.get('branchId')
            if warehouse_branch and branch_id and warehouse_branch != branch_id:
                return jsonify({"success": False, "error": "El almacén no pertenece a la sucursal seleccionada."}), 400
    else:
        reg_id = open_shift.get('registerId') if open_shift else None
        reg = None
        if reg_id:
            regs = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
            reg = next((r for r in regs if r['id'] == reg_id), None)
            if reg and reg.get('warehouseId'):
                warehouse_id = reg['warehouseId']
        if not warehouse_id:
            warehouse_id = DatabaseService.get_default_warehouse(
                owner_uid, company_id=company_id, sandbox=sandbox, branch_id=branch_id
            )

    if payment_info['credit_amount'] > 0:
        settlement_status = 'Emitida' if payment_info['paid_amount'] <= 0 else 'Parcialmente Cobrada'
    else:
        settlement_status = 'Cobrada'

    invoice_dict = {
        "invoiceNumber": invoice_number,
        "date": datetime.now(timezone.utc).isoformat(),
        "dueDate": datetime.now(timezone.utc).isoformat(),
        "clientId": client_id,
        "clientName": client_name,
        "clientRNC": client_rnc,
        "status": "PENDING_CONSOLIDATION" if qualifies_for_consolidation else settlement_status,
        "ecfType": ecf_type,
        "currency": "DOP",
        "paymentType": payment_info['payment_type'],
        "paymentMethod": payment_info['primary_method'],
        "incomeType": "01 - Ingresos por operaciones",
        "subtotal": calcs["subtotal"],
        "subtotalRaw": calcs["subtotal_raw"],
        "discountRate": global_discount_rate,
        "discountAmount": calcs["total_discount"],
        "globalDiscount": calcs["global_discount"],
        "totalITBIS": calcs["total_itbis"],
        "total": calcs["total"],
        "netPayable": calcs["net_payable"],
        "itbisBreakdown": _pos_itbis_breakdown(calcs["items"]),
        "payments": payment_info['payments'],
        "paidAmount": payment_info['paid_amount'],
        "creditAmount": payment_info['credit_amount'],
        "totalPaid": payment_info['paid_amount'],
        "remainingBalance": payment_info['credit_amount'],
        "notes": str(data.get('notes') or '').strip()[:500],
        "isQuotation": False,
        "isConvertedToInvoice": False,
        "items": calcs["items"],
        "stockReduced": False,  # DatabaseService lo reducirá al guardar
        "warehouseId": warehouse_id,
        "posShiftId": open_shift['id'],  # Necesario para consultas de consolidación
        "isSyncedWithDGII": False,
        "includeInRui": include_in_rui,
        "branchId": branch_id,
        "projectId": client_project_id or session.get('selected_project_id') or None
    }
    
    if usd_amount > 0:
        invoice_dict["usdAmount"] = usd_amount
        invoice_dict["usdExchangeRate"] = usd_rate

    # 1. Guardar factura en base de datos con manejo controlado de stock.
    #    La caja se registra DESPUÉS para que una factura fallida no deje movimientos huérfanos.
    from app.services.inventory_transaction_service import InsufficientStockError, InventoryTransactionError
    try:
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, company_id=company_id, sandbox=sandbox)
    except (InsufficientStockError, InventoryTransactionError) as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Error guardando venta POS %s", invoice_id)
        return jsonify({
            "success": False,
            "error": "No se pudo guardar la venta. No se registró ningún movimiento de caja."
        }), 500

    # 2. Registrar una transacción de caja por cada pago no-crédito.
    #    "Crédito" no genera entrada de efectivo; su saldo se refleja en CxC.
    import logging
    for idx, pay in enumerate(payment_info['payments']):
        if pay['method'] == 'Crédito':
            continue
        tx_dict = {
            "id": f"{invoice_id}-pay-{idx + 1}",
            "shiftId": open_shift['id'],
            "type": "SALE",
            "amount": pay['amount'],
            "paymentMethod": pay['method'],
            "referenceId": invoice_id,
            "notes": (
                f"{'[CONSOLIDADO] ' if qualifies_for_consolidation else ''}"
                f"Venta POS: {invoice_number} (pago {idx + 1}/{len(payment_info['payments'])})"
            ),
        }
        if pay.get('reference'):
            tx_dict["reference"] = pay['reference']
        if pay.get('bank'):
            tx_dict["bank"] = pay['bank']
        if float(pay.get('usdAmount') or 0.0) > 0:
            tx_dict["usdAmount"] = pay['usdAmount']
            tx_dict["usdExchangeRate"] = pay.get('usdExchangeRate') or usd_rate
        try:
            DatabaseService.register_cash_transaction(
                owner_uid, tx_dict, company_id=company_id, sandbox=sandbox
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "No se pudo registrar el pago %s de la factura POS %s", idx + 1, invoice_id
            )

    # 3. Si aplica modo consolidado → no emitir e-CF individual, retornar con indicador
    if qualifies_for_consolidation:
        from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_POS
        AuditService.log_from_request(
            owner_uid=owner_uid,
            action=ACTION_CREATE,
            module=MODULE_POS,
            entity_id=invoice_id,
            entity_label=f"Venta POS {invoice_number} (Consolidadas - Monto: RD$ {calcs['total']:.2f})",
            user_session=session.get('user', {}),
            after=invoice_dict,
            sandbox=sandbox
        )
        response_body = {
            "success": True,
            "invoiceId": invoice_id,
            "invoiceNumber": invoice_number,
            "total": calcs["total"],
            "encf": "(Consolidado al Cierre)",
            "consolidated": True
        }
        if idempotency_key:
            DatabaseService.save_idempotency_record(owner_uid, idempotency_key, {
                "response": response_body,
                "statusCode": 200,
                "invoiceId": invoice_id
            }, company_id=company_id, sandbox=sandbox)
        return jsonify(response_body)

    # 4. Intentar emisión electrónica (e-CF) individual
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    try:
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice_dict, sandbox=sandbox)
        if res and res.get('success'):
            # Actualizar campos de e-CF
            invoice_dict["encf"] = res.get('encf', '')
            invoice_dict["xmlSignature"] = res.get('xmlSignature', '')
            invoice_dict["qrCodeURL"] = res.get('qrCodeURL', '')
            pending_dgii = res.get("status") == "PENDING" or res.get("mode") == "FALLBACK"
            invoice_dict["isSyncedWithDGII"] = (res.get("mode") in ("API", "RFCE_API") and res.get("status") != "PENDING")
            invoice_dict["emisionMode"] = res.get("mode", "API")
            invoice_dict["dgiiStatus"] = res.get("dgiiStatus") or ("PENDING" if pending_dgii else "ACCEPTED")
            invoice_dict["trackId"] = res.get("trackId", "")
            invoice_dict["contingencyEmittedAt"] = datetime.now(timezone.utc).isoformat() if res.get("mode") == "FALLBACK" else None
            invoice_dict["status"] = "Pendiente DGII" if pending_dgii else settlement_status
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, company_id=company_id, sandbox=sandbox)

            # Auto-notificar e-CF al cliente si fue aceptada por DGII y posee correo
            try:
                from app.web.invoices import auto_notify_invoice_if_accepted
                invoice_dict["id"] = invoice_id
                auto_notify_invoice_if_accepted(owner_uid, invoice_dict, company_id=company_id, sandbox=sandbox)
            except Exception as auto_email_err:
                import logging
                logging.getLogger(__name__).warning(f"Error auto enviando email POS {invoice_id}: {auto_email_err}")

            # Generar asiento contable automático para POS
            try:
                from app.services.accounting_service import AccountingService
                AccountingService.auto_generate_invoice_entry(company_id, invoice_dict, sandbox=sandbox)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(f"Asiento contable POS no generado: {exc}")

            # Event Bus: notificar emisión de factura
            try:
                from app.events import get_event_bus, InvoiceEmitted
                get_event_bus().publish(InvoiceEmitted(
                    owner_uid=owner_uid,
                    invoice_id=invoice_id,
                    invoice_number=invoice_number,
                    invoice_data=invoice_dict,
                    sandbox=sandbox,
                    country=get_current_country(),
                ))
            except Exception:
                pass
        elif res:
            error_msg = res.get('message', res.get('error', 'Error desconocido de DGII'))
            invoice_dict["status"] = "Rechazado DGII"
            invoice_dict["dgiiError"] = str(error_msg)[:200]
            invoice_dict["enviadoADGII"] = True
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, company_id=company_id, sandbox=sandbox)
    except Exception as e:
        # Si falla, operamos en contingencia local
        print(f"⚠️ Error al emitir e-CF en POS: {e}")
        invoice_dict["emisionMode"] = "FALLBACK"
        invoice_dict["isSyncedWithDGII"] = False
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, company_id=company_id, sandbox=sandbox)

        # Generar asiento contable incluso en contingencia
        try:
            from app.services.accounting_service import AccountingService
            AccountingService.auto_generate_invoice_entry(company_id, invoice_dict, sandbox=sandbox)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Asiento contable POS (contingencia) no generado: {exc}")

        # Event Bus: notificar emisión en contingencia
        try:
            from app.events import get_event_bus, InvoiceEmitted
            get_event_bus().publish(InvoiceEmitted(
                owner_uid=owner_uid,
                invoice_id=invoice_id,
                invoice_number=invoice_number,
                invoice_data=invoice_dict,
                sandbox=sandbox,
                country=get_current_country(),
            ))
        except Exception:
            pass

    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_POS
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_CREATE,
        module=MODULE_POS,
        entity_id=invoice_id,
        entity_label=f"Venta POS {invoice_number} (Monto: RD$ {calcs['total']:.2f})",
        user_session=session.get('user', {}),
        after=invoice_dict,
        sandbox=sandbox
    )
    # 4. Enviar factura y XML por correo SOLO si es Crédito Fiscal (E31) con cliente registrado.
    #    Las Facturas de Consumo (E32) son para consumidores finales y NO se envían por email.
    if ecf_type == 'Factura de Crédito Fiscal (E31)' and client_id and client_id != 'default':
        try:
            client = DatabaseService.get_client(owner_uid, client_id, company_id=company_id, sandbox=sandbox)
            if client and client.get('email'):
                recipient_email = client['email'].strip()
                if recipient_email:
                    from flask import current_app
                    flask_app = current_app._get_current_object()
                    import threading
                    
                    def send_invoice_email_bg(app_instance, o_uid, inv, email_to, sb, base, cid=None):
                        with app_instance.app_context():
                            try:
                                from app.web.invoices import send_invoice_email
                                send_invoice_email(o_uid, inv, email_to, sandbox=sb, base_url=base, company_id=cid)
                            except Exception as th_err:
                                print(f"❌ Error en hilo de envío de correo POS: {th_err}")
                                
                    host_url = request.host_url
                    threading.Thread(
                        target=send_invoice_email_bg,
                        args=(flask_app, owner_uid, invoice_dict, recipient_email, sandbox, host_url, company_id)
                    ).start()
                    print(f"📧 [POS] Correo de e-CF programado para {recipient_email} para factura {invoice_number}", flush=True)
        except Exception as email_err:
            print(f"⚠️ Error al iniciar hilo de envío de correo en POS: {email_err}")
            
    response_body = {
        "success": True,
        "invoiceId": invoice_id,
        "invoiceNumber": invoice_number,
        "total": calcs["total"],
        "encf": invoice_dict.get("encf", "Contingencia")
    }
    if idempotency_key:
        DatabaseService.save_idempotency_record(owner_uid, idempotency_key, {
            "response": response_body,
            "statusCode": 200,
            "invoiceId": invoice_id
        }, company_id=company_id, sandbox=sandbox)
    return jsonify(response_body)


@web_pos_bp.route('/pos/invoice/<invoice_id>/print')
@require_permission('canManagePOS', 'Impresión POS')
def print_receipt(invoice_id):
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, company_id=company_id, sandbox=sandbox)
    if not invoice:
        return "Factura no encontrada.", 404
        
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    
    import io
    import base64
    import qrcode
    import urllib.parse
    
    qr_url = invoice.get("qrCodeURL")
    fecha_firma_str = ""
    qr_base64 = ""
    
    if invoice.get("encf") and invoice.get("xmlSignature"):
        try:
            fecha_emision_dt = datetime.strptime(invoice.get("date", "")[:10], "%Y-%m-%d")
            fecha_emision_str = fecha_emision_dt.strftime("%d-%m-%Y")
        except:
            fecha_emision_str = ""
            
        if invoice.get("paymentDate"):
            try:
                dt = datetime.fromisoformat(invoice["paymentDate"].replace('Z', '+00:00'))
                fecha_firma_str = dt.strftime("%d-%m-%Y %H:%M:%S")
            except:
                fecha_firma_str = fecha_emision_str + " 12:00:00"
        else:
            fecha_firma_str = fecha_emision_str + " 12:00:00"
            
        codigo_seg = invoice.get("xmlSignature", "")[:6]
        try:
            qr_url = DgiiDirectService.build_qr_url(company, invoice, codigo_seg) or qr_url
        except Exception:
            pass
            
    if qr_url:
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=0)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            stream = io.BytesIO()
            img.save(stream, format="PNG")
            qr_base64 = base64.b64encode(stream.getvalue()).decode('utf-8')
        except Exception as e:
            print(f"Error generating QR code for POS receipt: {e}")
            
    branches = DatabaseService.get_branches(owner_uid, company_id=company_id, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
    if not branch and branches:
        branch = branches[0]
        
    formatted_date = ""
    formatted_time = ""
    if invoice.get("date"):
        try:
            dt = datetime.fromisoformat(invoice["date"].replace('Z', '+00:00'))
            formatted_date = dt.strftime("%Y-%m-%d")
            formatted_time = dt.strftime("%H:%M:%S")
        except Exception as e:
            print(f"Error parsing invoice date for POS receipt: {e}")
            formatted_date = str(invoice["date"])[:10]
            formatted_time = str(invoice["date"])[11:19]
        
    return render_template(
        'pos/receipt.html',
        invoice=invoice,
        company=company,
        branch=branch,
        qr_base64=qr_base64,
        fecha_firma_str=fecha_firma_str,
        sandbox=sandbox,
        formatted_date=formatted_date,
        formatted_time=formatted_time
    )


@web_pos_bp.route('/pos/shift/<shift_id>/print-z')
@require_permission('canManagePOS', 'Impresión POS')
def print_z_report(shift_id):
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener el turno de caja
    shifts = DatabaseService.get_cash_shifts(owner_uid, company_id=company_id, sandbox=sandbox)
    shift = next((s for s in shifts if s['id'] == shift_id), None)
    if not shift:
        return "Turno no encontrado.", 404
        
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    
    # Obtener nombre de la caja
    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    register = next((r for r in registers if r['id'] == shift['registerId']), None)
    register_name = register['name'] if register else 'Caja Desconocida'
    
    return render_template(
        'pos/receipt_z.html',
        shift=shift,
        company=company,
        register_name=register_name,
        sandbox=sandbox
    )


@web_pos_bp.route('/pos/register/new', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def create_cash_register():
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="isPosSupervisor o Propietario"), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    # Validar límite de cajas en el plan de la empresa
    profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    box_limit = int(profile.get('boxLimit', 0)) if profile else 0
    additional_box_cost = float(profile.get('additionalBoxCost', 0.0) or 0.0) if profile else 0.0
    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    is_exceeding_box_limit = (box_limit > 0 and len(registers) >= box_limit)

    from app.utils.plan_limits import is_resource_excess_blocked
    if is_resource_excess_blocked(profile, 'boxes') and is_exceeding_box_limit:
        flash(f'No se puede crear la caja registradora. Has alcanzado el límite de {box_limit} cajas contratadas en tu plan y tienes bloqueada la creación de cajas adicionales en tu suscripción. Puedes habilitar adicionales en Suscripción.', 'error')
        return redirect(url_for('web_pos.pos_admin_dashboard'))
        
    name = request.form.get('name', '').strip()
    if not name:
        flash('El nombre de la caja es obligatorio.', 'error')
        return redirect(url_for('web_pos.pos_admin_dashboard'))
        
    warehouse_id = request.form.get('warehouseId', '').strip()
    register_id = f"caja-{uuid.uuid4().hex[:8]}"
    register_dict = {
        "name": name,
        "status": "CLOSED",
        "warehouseId": warehouse_id,
        "createdAt": datetime.now(timezone.utc).isoformat()
    }
    
    DatabaseService.save_cash_register(owner_uid, register_id, register_dict, company_id=company_id, sandbox=sandbox)
    if is_exceeding_box_limit and additional_box_cost > 0:
        flash(f'Caja registradora "{name}" creada correctamente. Has superado el límite de {box_limit} cajas contratadas; se aplicará un cargo adicional de USD ${additional_box_cost:,.2f}/mes por caja adicional en tu próxima facturación.', 'warning')
    elif is_exceeding_box_limit:
        flash(f'Caja registradora "{name}" creada correctamente. Has superado el límite de {box_limit} cajas contratadas en tu plan.', 'info')
    else:
        flash(f'Caja registradora "{name}" creada correctamente.', 'success')
    return redirect(url_for('web_pos.pos_admin_dashboard'))


@web_pos_bp.route('/pos/admin')
@require_permission('canManagePOS', 'Administración de Caja')
def pos_admin_dashboard():
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="isPosSupervisor o Propietario"), 403
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    shifts = DatabaseService.get_cash_shifts(owner_uid, company_id=company_id, sandbox=sandbox)
    warehouses = DatabaseService.get_warehouses(owner_uid, company_id=company_id, sandbox=sandbox)
    wh_map = {w['id']: w['name'] for w in warehouses}
    
    for r in registers:
        r['warehouseName'] = wh_map.get(r.get('warehouseId'), 'Predeterminado')

    # Map registers name to shifts
    regs_map = {r['id']: r['name'] for r in registers}
    for s in shifts:
        s['registerName'] = regs_map.get(s['registerId'], 'Caja Desconocida')
        
    return render_template(
        'pos/admin.html',
        active_page='pos_admin',
        registers=registers,
        shifts=shifts,
        warehouses=warehouses
    )


@web_pos_bp.route('/pos/contingencia')
@require_permission('canManagePOS', 'Contingencia DGII')
def pos_contingencia():
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return render_template('auth/restricted.html', feature_name="Contingencia DGII", required_permission="isPosSupervisor o Propietario"), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    invoices = DatabaseService.get_contingency_invoices(owner_uid, company_id=company_id, sandbox=sandbox)
    now_utc = datetime.now(timezone.utc)

    contingency_invoices = []
    for inv in invoices:
        emitted_at_str = inv.get('contingencyEmittedAt') or inv.get('date', now_utc.isoformat())
        try:
            emitted_at = datetime.fromisoformat(emitted_at_str.replace('Z', '+00:00'))
            if emitted_at.tzinfo is None:
                emitted_at = emitted_at.replace(tzinfo=timezone.utc)
        except Exception:
            emitted_at = now_utc
        hours_elapsed = (now_utc - emitted_at).total_seconds() / 3600
        hours_remaining = max(0.0, 72.0 - hours_elapsed)
        sync_attempts = int(inv.get('syncAttempts', 0))
        last_attempt = inv.get('lastSyncAttempt', '')
        next_retry = ContingencySyncService._should_retry(sync_attempts, last_attempt)

        contingency_invoices.append({
            'id': inv['id'],
            'invoiceNumber': inv.get('invoiceNumber', ''),
            'encf': inv.get('encf', ''),
            'total': inv.get('total', 0.0),
            'client': inv.get('clientName', inv.get('buyer', 'Consumidor Final')),
            'status': inv.get('status', ''),
            'paymentMethod': inv.get('paymentMethod', ''),
            'date': inv.get('date', ''),
            'contingencyEmittedAt': inv.get('contingencyEmittedAt', ''),
            'hours_elapsed': round(hours_elapsed, 1),
            'hours_remaining': round(hours_remaining, 1),
            'is_critical': hours_remaining < 12,
            'is_expired': hours_remaining <= 0,
            'sync_attempts': sync_attempts,
            'next_retry_ready': next_retry,
        })

    contingency_invoices.sort(key=lambda x: (x['is_expired'], x['hours_remaining']))

    total_pending = len(contingency_invoices)
    critical_count = sum(1 for inv in contingency_invoices if inv['is_critical'] and not inv['is_expired'])
    expired_count = sum(1 for inv in contingency_invoices if inv['is_expired'])
    total_amount = sum(inv['total'] for inv in contingency_invoices)

    expired_list = ContingencySyncService.check_expired_contingency(owner_uid, sandbox=sandbox)

    return render_template(
        'pos/contingencia.html',
        active_page='pos_contingencia',
        contingency_invoices=contingency_invoices,
        total_pending=total_pending,
        critical_count=critical_count,
        expired_count=expired_count,
        total_amount=total_amount,
        expired_list=expired_list,
        sandbox=sandbox,
    )


import re
from app.web.invoices import format_mentions

def process_shift_comment_mentions(owner_uid, content, shift_id, shift_label, sandbox):
    company_id = _resolve_company_id(owner_uid)
    taggable_users = []
    owner_prof = DatabaseService.get_user_profile(owner_uid, company_id=company_id)
    if owner_prof:
        taggable_users.append({
            "uid": owner_uid,
            "name": owner_prof.get("name", "Propietario"),
            "email": owner_prof.get("email", ""),
            "role": "owner"
        })
    team = DatabaseService.get_team_members(owner_uid, company_id=company_id) or []
    for member in team:
        taggable_users.append({
            "uid": member.get("uid"),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
            "role": member.get("role", "collaborator")
        })
        
    for u in taggable_users:
        name = u.get("name", "")
        email = u.get("email", "")
        uid = u.get("uid")
        if not uid or not email:
            continue
            
        if 'user' in session and session['user'].get('uid') == uid:
            continue
            
        escaped_name = re.escape(name)
        escaped_email = re.escape(email)
        pattern = rf"@({escaped_name}|{escaped_email})\b"
        if re.search(pattern, content, re.IGNORECASE):
            notif_id = str(uuid.uuid4())
            notif_dict = {
                "id": notif_id,
                "title": "Nueva mención en un turno de caja",
                "message": f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del {shift_label}.",
                "documentId": shift_id,
                "documentNumber": shift_label,
                "link": f"/pos/admin/shift/{shift_id}",
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "read": False,
                "type": "mention",
                "sandbox": bool(sandbox)
            }
            DatabaseService.create_user_notification(uid, notif_dict)
            
            from flask import request
            try:
                base_url = request.host_url.rstrip('/')
            except Exception:
                import os
                base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
            doc_url = f"{base_url}/pos/admin/shift/{shift_id}"
            
            from app.services.notifications import NotificationService
            
            # Obtener el nombre comercial de la empresa
            company = DatabaseService.get_company(owner_uid, company_id=company_id) or {}
            issuer_company_name = company.get("tradeName") or company.get("companyName") or get_product_name()
            
            NotificationService.send_mention_notification(
                recipient_email=email,
                recipient_name=name,
                commenter_name=session['user'].get('name', session['user']['email']),
                comment_snippet=content[:150] + ("..." if len(content) > 150 else ""),
                doc_number=shift_label,
                doc_url=doc_url,
                issuer_company_name=issuer_company_name,
                sandbox=sandbox
            )

@web_pos_bp.route('/pos/admin/shift/<shift_id>')
@require_permission('canManagePOS', 'Administración de Caja')
def pos_admin_shift_detail(shift_id):
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="isPosSupervisor o Propietario"), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    shifts = DatabaseService.get_cash_shifts(owner_uid, company_id=company_id, sandbox=sandbox)
    shift = next((s for s in shifts if s['id'] == shift_id), None)
    if not shift:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('web_pos.pos_admin_dashboard'))

    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    register = next((r for r in registers if r['id'] == shift['registerId']), None)
    shift['registerName'] = register['name'] if register else 'Caja Desconocida'

    transactions = DatabaseService.get_cash_transactions(owner_uid, shift_id, company_id=company_id, sandbox=sandbox)
    company = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    comments = DatabaseService.get_resource_comments(owner_uid, "shifts", shift_id, company_id=company_id, sandbox=sandbox)

    # Load taggable users
    taggable_users = []
    owner_prof = DatabaseService.get_user_profile(owner_uid, company_id=company_id)
    if owner_prof:
        taggable_users.append({
            "uid": owner_uid,
            "name": owner_prof.get("name", "Propietario"),
            "email": owner_prof.get("email", ""),
            "role": "owner"
        })
    team = DatabaseService.get_team_members(owner_uid, company_id=company_id) or []
    for member in team:
        taggable_users.append({
            "uid": member.get("uid"),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
            "role": member.get("role", "collaborator")
        })

    return render_template(
        'pos/shift_detail.html',
        active_page='pos_admin',
        shift=shift,
        transactions=transactions,
        company=company,
        comments=comments,
        taggable_users=taggable_users,
        format_mentions=format_mentions
    )

@web_pos_bp.route('/pos/admin/shift/<shift_id>/comments/new', methods=['POST'])
def add_shift_comment(shift_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))
        
    attachment_url = ""
    attachment_name = ""
    
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_shift_{shift_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            
            attachment_url = DatabaseService.upload_file_to_storage(
                file_data=file_data,
                destination_path=destination_path,
                mime_type=mime_type
            )
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    comment_id = str(uuid.uuid4())
    comment_dict = {
        "content": content,
        "createdBy": session['user']['email'],
        "createdByName": session['user'].get('name', session['user']['email']),
        "createdByUid": session['user']['uid'],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name,
        "edited": False
    }
    
    DatabaseService.save_resource_comment(owner_uid, "shifts", shift_id, comment_id, comment_dict, company_id=company_id, sandbox=sandbox)
    
    # Process mentions
    try:
        shift_label = f"Turno de Caja ({shift_id[:8]})"
        process_shift_comment_mentions(owner_uid, content, shift_id, shift_label, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en add_shift_comment: {ex}")
        
    flash('Comentario agregado exitosamente.', 'success')
    return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))

@web_pos_bp.route('/pos/admin/shift/<shift_id>/comments/<comment_id>/edit', methods=['POST'])
def edit_shift_comment(shift_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_resource_comments(owner_uid, "shifts", shift_id, company_id=company_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))
        
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para editar este comentario.', 'error')
        return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))
        
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))
        
    comment['content'] = content
    comment['edited'] = True
    comment['editedAt'] = datetime.now(timezone.utc).isoformat()
    
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_shift_{shift_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            
            attachment_url = DatabaseService.upload_file_to_storage(
                file_data=file_data,
                destination_path=destination_path,
                mime_type=mime_type
            )
            comment['attachmentUrl'] = attachment_url
            comment['attachmentName'] = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    DatabaseService.save_resource_comment(owner_uid, "shifts", shift_id, comment_id, comment, company_id=company_id, sandbox=sandbox)
    
    try:
        shift_label = f"Turno de Caja ({shift_id[:8]})"
        process_shift_comment_mentions(owner_uid, content, shift_id, shift_label, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en edit_shift_comment: {ex}")
        
    flash('Comentario editado exitosamente.', 'success')
    return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))

@web_pos_bp.route('/pos/admin/shift/<shift_id>/comments/<comment_id>/delete', methods=['POST'])
def delete_shift_comment(shift_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_resource_comments(owner_uid, "shifts", shift_id, company_id=company_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))
        
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para eliminar este comentario.', 'error')
        return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))
        
    DatabaseService.delete_resource_comment(owner_uid, "shifts", shift_id, comment_id, company_id=company_id, sandbox=sandbox)
    flash('Comentario eliminado exitosamente.', 'success')
    return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))



@web_pos_bp.route('/pos/admin/shift/<shift_id>/audit', methods=['POST'])
@require_permission('canManagePOS', 'Administración de Caja')
def audit_shift(shift_id):
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return render_template('auth/restricted.html', feature_name="Auditoría de Caja", required_permission="isPosSupervisor o Propietario"), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    user_email = session['user']['email']
    sandbox = session.get('is_sandbox_mode', True)

    try:
        audited_amount = float(request.form.get('auditedAmount', 0.0))
    except ValueError:
        audited_amount = 0.0
    notes = request.form.get('notes', '')
    resolution_type = request.form.get('resolutionType')

    res = DatabaseService.audit_cash_shift(
        owner_uid, shift_id, audited_amount, user_uid, user_email, company_id=company_id, notes=notes, resolution_type=resolution_type, sandbox=sandbox
    )
    if res:
        diff = res["difference"]
        if abs(diff) < 0.01:
            flash('Turno auditado y cerrado correctamente. ¡Cuadre perfecto!', 'success')
        elif diff > 0:
            flash(f'Turno auditado y cerrado con SOBRANTE de RD$ {diff:,.2f}.', 'warning')
        else:
            flash(f'Turno auditado y cerrado con FALTANTE de RD$ {abs(diff):,.2f}.', 'error')
    else:
        flash('Error al procesar la auditoría del turno.', 'error')

    return redirect(url_for('web_pos.pos_admin_shift_detail', shift_id=shift_id))


@web_pos_bp.route('/pos/register/<register_id>/toggle-consolidation', methods=['POST'])
@require_permission('canManagePOS', 'Administración de Caja')
def toggle_consolidation_mode(register_id):
    """Activa o desactiva el modo comprobante consolidado para una caja registradora."""
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return jsonify({"success": False, "error": "Solo el propietario o supervisor puede cambiar esta configuración."}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or {}
    enabled = bool(data.get('enabled', False))

    DatabaseService.update_cash_register_settings(
        owner_uid, register_id, {"consolidationMode": enabled}, company_id=company_id, sandbox=sandbox
    )
    mode_str = "activado" if enabled else "desactivado"
    return jsonify({"success": True, "consolidationMode": enabled, "message": f"Modo consolidado {mode_str}."})


@web_pos_bp.route('/pos/supervisor/authorize', methods=['POST'])
def authorize_supervisor_operation():
    """Valida si un PIN es válido para un supervisor o propietario de la empresa."""
    if 'user' not in session:
        return jsonify({"success": False, "error": "No autenticado"}), 401
        
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    data = request.json or {}
    pin = (data.get('pin') or '').strip()
    action_name = (data.get('action') or 'Operación POS').strip()
    supervisor_uid = data.get('supervisorUid')
    
    if not pin:
        return jsonify({"success": False, "error": "El PIN es requerido."}), 400
    if not supervisor_uid:
        return jsonify({"success": False, "error": "El supervisor es requerido."}), 400
        
    try:
        from app.services.audit_service import AuditService, ACTION_UPDATE, MODULE_POS
        sandbox = session.get('is_sandbox_mode', True)

        # 1. Si es el propietario (owner) de la cuenta
        if supervisor_uid == owner_uid:
            owner_user = DatabaseService.get_user_profile(owner_uid, company_id=company_id)
            if owner_user and owner_user.get('posSupervisorPin') == pin:
                supervisor_name = owner_user.get('name', 'Propietario')
                supervisor_email = owner_user.get('email', '')
                
                AuditService.log_from_request(
                    owner_uid=owner_uid,
                    action=ACTION_UPDATE,
                    module=MODULE_POS,
                    entity_id=owner_user.get('uid', owner_uid),
                    entity_label=f"Operación POS '{action_name}' autorizada por Propietario: {supervisor_name} ({supervisor_email})",
                    user_session=session.get('user', {}),
                    sandbox=sandbox
                )
                return jsonify({"success": True, "supervisorName": supervisor_name})
            else:
                return jsonify({"success": False, "error": "PIN incorrecto para el Propietario."}), 403

        # 2. Si es un colaborador con rol de supervisor
        team = DatabaseService.get_team_members(owner_uid, company_id=company_id)
        member = next((m for m in team if m['uid'] == supervisor_uid), None)
        if member and member.get('permissions', {}).get('isPosSupervisor', False):
            member_profile = DatabaseService.get_user_profile(supervisor_uid)
            if member_profile and member_profile.get('posSupervisorPin') == pin:
                supervisor_name = member_profile.get('name', 'Supervisor')
                supervisor_email = member_profile.get('email', '')
                
                AuditService.log_from_request(
                    owner_uid=owner_uid,
                    action=ACTION_UPDATE,
                    module=MODULE_POS,
                    entity_id=member_profile.get('uid', ''),
                    entity_label=f"Operación POS '{action_name}' autorizada por Supervisor: {supervisor_name} ({supervisor_email})",
                    user_session=session.get('user', {}),
                    sandbox=sandbox
                )
                return jsonify({"success": True, "supervisorName": supervisor_name})
            else:
                return jsonify({"success": False, "error": "PIN incorrecto para el Supervisor."}), 403
        
        return jsonify({"success": False, "error": "El usuario seleccionado no tiene permisos de supervisor de caja."}), 403
                    
    except Exception as e:
        print(f"⚠️ Error al validar PIN de supervisor: {e}")
        return jsonify({"success": False, "error": "Error interno al validar PIN"}), 500


@web_pos_bp.route('/pos/usd-rate')
def get_usd_rate():
    """Retorna la tasa de cambio USD a DOP del día (Banco Popular)."""
    from app.utils.currency import CurrencyService
    try:
        rate = CurrencyService.get_bpd_rate()
        return jsonify({"success": True, "rate": rate})
    except Exception as e:
        print(f"⚠️ Error al obtener tasa USD: {e}")
        return jsonify({"success": False, "rate": 58.50})


@web_pos_bp.route('/pos/admin/reports')
@require_permission('canManagePOS', 'Administración de Caja')
def pos_admin_reports_dashboard():
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="isPosSupervisor o Propietario"), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    registers = DatabaseService.get_cash_registers(owner_uid, company_id=company_id, sandbox=sandbox)
    shifts = DatabaseService.get_cash_shifts(owner_uid, company_id=company_id, sandbox=sandbox)
    
    # Get distinct list of cashiers
    cashiers = sorted(list(set(s['openedByUserEmail'] for s in shifts if s.get('openedByUserEmail'))))

    return render_template(
        'pos/reports_dashboard.html',
        active_page='pos_admin',
        registers=registers,
        cashiers=cashiers
    )


@web_pos_bp.route('/pos/admin/reports/data')
@require_permission('canManagePOS', 'Administración de Caja')
def pos_admin_reports_data():
    if session['user'].get('role') != 'owner' and not check_permission('isPosSupervisor'):
        return jsonify({"success": False, "error": "No autorizado"}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    start_date = request.args.get('startDate')
    end_date = request.args.get('endDate')
    register_id = request.args.get('registerId')
    cashier = request.args.get('cashier')

    shifts = DatabaseService.get_cash_shifts(owner_uid, company_id=company_id, sandbox=sandbox)

    # Filter shifts
    filtered_shifts = []
    for s in shifts:
        s_date = s.get('openingTime', '')[:10]
        if start_date and s_date < start_date:
            continue
        if end_date and s_date > end_date:
            continue
        if register_id and s.get('registerId') != register_id:
            continue
        if cashier and s.get('openedByUserEmail') != cashier:
            continue
        filtered_shifts.append(s)

    # Calculate metrics
    total_expected = 0.0
    total_declared = 0.0
    total_difference = 0.0
    total_opening = 0.0

    # Sales by payment method
    pm_totals = {
        "Efectivo DOP": 0.0,
        "Efectivo USD": 0.0,
        "Tarjeta": 0.0,
        "Transferencia": 0.0
    }

    all_txs = []
    for s in filtered_shifts:
        total_expected += float(s.get('closingAmountExpected') or 0.0)
        total_declared += float(s.get('closingAmountDeclared') or 0.0)
        total_difference += float(s.get('difference') or 0.0)
        total_opening += float(s.get('openingAmount') or 0.0)

        # Sum payment channels
        pm_totals["Efectivo DOP"] += float(s.get('expectedCash', 0.0)) - float(s.get('openingAmount', 0.0))
        pm_totals["Efectivo USD"] += float(s.get('expectedUSD', 0.0))
        pm_totals["Tarjeta"] += float(s.get('expectedCard', 0.0))
        pm_totals["Transferencia"] += float(s.get('expectedTransfer', 0.0))

        # Query cash transactions for details
        txs = DatabaseService.get_cash_transactions(owner_uid, s['id'], company_id=company_id, sandbox=sandbox)
        for t in txs:
            t['registerName'] = s.get('registerName', 'Caja')
            t['openedByUserEmail'] = s.get('openedByUserEmail', '')
            t['shiftId'] = s.get('id')
            all_txs.append(t)

    # 1. Aperturas y cierres
    reports_shifts = []
    for s in filtered_shifts:
        reports_shifts.append({
            "id": s.get('id'),
            "registerName": s.get('registerName'),
            "openedByUserEmail": s.get('openedByUserEmail'),
            "openingTime": s.get('openingTime'),
            "closingTime": s.get('closingTime'),
            "openingAmount": s.get('openingAmount'),
            "closingAmountExpected": s.get('closingAmountExpected'),
            "closingAmountDeclared": s.get('closingAmountDeclared'),
            "difference": s.get('difference'),
            "status": s.get('status'),
            "auditResolutionType": s.get('auditResolutionType'),
            "auditedByUserEmail": s.get('auditedByUserEmail')
        })

    # 2. Entradas y salidas de efectivo
    cash_movements = []
    for t in all_txs:
        if t.get('type') in ['IN', 'OUT'] and t.get('status') != 'VOIDED':
            cash_movements.append({
                "date": t.get('date'),
                "type": t.get('type'),
                "paymentMethod": t.get('paymentMethod'),
                "amount": t.get('amount'),
                "usdAmount": t.get('usdAmount', 0.0),
                "notes": t.get('notes'),
                "registerName": t.get('registerName'),
                "openedByUserEmail": t.get('openedByUserEmail')
            })

    # 3. Anulaciones y cancelaciones
    voided_transactions = []
    for t in all_txs:
        if t.get('status') == 'VOIDED':
            voided_transactions.append({
                "date": t.get('date'),
                "type": t.get('type'),
                "paymentMethod": t.get('paymentMethod'),
                "amount": t.get('amount'),
                "usdAmount": t.get('usdAmount', 0.0),
                "notes": t.get('notes'),
                "registerName": t.get('registerName'),
                "openedByUserEmail": t.get('openedByUserEmail')
            })

    # 4. Diferencias de caja
    discrepancies = []
    for s in filtered_shifts:
        diff_val = s.get('difference') or 0.0
        if abs(diff_val) > 0.01:
            discrepancies.append({
                "id": s.get('id'),
                "registerName": s.get('registerName'),
                "openedByUserEmail": s.get('openedByUserEmail'),
                "closingTime": s.get('closingTime'),
                "difference": diff_val,
                "differenceCash": s.get('differenceCash', 0.0),
                "differenceUSD": s.get('differenceUSD', 0.0),
                "differenceCard": s.get('differenceCard', 0.0),
                "differenceTransfer": s.get('differenceTransfer', 0.0),
                "status": s.get('status'),
                "auditResolutionType": s.get('auditResolutionType'),
                "auditedByUserEmail": s.get('auditedByUserEmail')
            })

    # 5. Conciliación bancaria (lotes de tarjetas)
    card_lotes = []
    for s in filtered_shifts:
        if s.get('expectedCard', 0.0) > 0.0 or s.get('declaredCard', 0.0) > 0.0:
            card_lotes.append({
                "id": s.get('id'),
                "registerName": s.get('registerName'),
                "openedByUserEmail": s.get('openedByUserEmail'),
                "closingTime": s.get('closingTime'),
                "loteNumber": s.get('cardLoteNumber') or 'N/A',
                "expectedCard": s.get('expectedCard', 0.0),
                "declaredCard": s.get('declaredCard', 0.0),
                "differenceCard": s.get('differenceCard', 0.0),
                "status": s.get('status')
            })

    return jsonify({
        "success": True,
        "metrics": {
            "totalExpected": total_expected,
            "totalDeclared": total_declared,
            "totalDifference": total_difference,
            "totalOpening": total_opening,
            "shiftCount": len(filtered_shifts),
            "discrepancyCount": len(discrepancies)
        },
        "paymentsDistribution": pm_totals,
        "shifts": reports_shifts,
        "cashMovements": cash_movements,
        "voidedTransactions": voided_transactions,
        "discrepancies": discrepancies,
        "cardLotes": card_lotes
    })
