# app/web/pos.py
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.services.ecf_emission import EcfEmissionService
from app.services.dgii import DGIIService
from app.utils.decorators import require_permission, check_permission

web_pos_bp = Blueprint('web_pos', __name__)

def require_open_shift(f):
    """Decorador para asegurar que el cajero tiene una caja abierta antes de vender."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        if not check_permission('canManagePOS'):
            return render_template('auth/restricted.html', feature_name="Punto de Venta", required_permission="canManagePOS")
        
        owner_uid = session['user']['ownerUID']
        user_uid = session['user']['uid']
        sandbox = session.get('is_sandbox_mode', True)
        
        open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, sandbox=sandbox)
        if not open_shift:
            flash('Debe abrir un turno de caja para operar el Punto de Venta.', 'warning')
            return redirect(url_for('web_pos.pos_dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@web_pos_bp.route('/pos')
@require_permission('canManagePOS', 'Punto de Venta')
def pos_dashboard():
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener cajas registradoras
    registers = DatabaseService.get_cash_registers(owner_uid, sandbox=sandbox)
    
    # Verificar si el usuario ya tiene un turno abierto
    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, sandbox=sandbox)
    
    current_register = None
    transactions = []
    pending_consolidation_count = 0
    if open_shift:
        current_register = next((r for r in registers if r['id'] == open_shift['registerId']), None)
        transactions = DatabaseService.get_cash_transactions(owner_uid, open_shift['id'], sandbox=sandbox)
        company = DatabaseService.get_company_profile(owner_uid)
        if company and company.get('consolidationEnabled'):
            pending = DatabaseService.get_pending_consolidation_invoices(owner_uid, open_shift['id'], sandbox=sandbox)
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
    existing_shift = DatabaseService.get_open_shift(owner_uid, user_uid, sandbox=sandbox)
    if existing_shift:
        flash('Ya tiene un turno de caja activo.', 'warning')
        return redirect(url_for('web_pos.pos_terminal'))
        
    shift_dict = {
        "registerId": register_id,
        "openedByUserId": user_uid,
        "openedByUserEmail": session['user']['email'],
        "openingAmount": opening_amount
    }
    
    res = DatabaseService.open_cash_shift(owner_uid, shift_dict, sandbox=sandbox)
    if res:
        flash('Caja abierta correctamente. ¡Buen turno!', 'success')
        return redirect(url_for('web_pos.pos_terminal'))
    else:
        flash('Error al abrir la caja registradora.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))


@web_pos_bp.route('/pos/shift/close', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def close_shift():
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, sandbox=sandbox)
    if not open_shift:
        flash('No tiene ningún turno de caja activo para cerrar.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))

    # --- CONSOLIDACIÓN AUTOMÁTICA AL CIERRE ---
    pending = DatabaseService.get_pending_consolidation_invoices(owner_uid, open_shift['id'], sandbox=sandbox)
    if pending:
        try:
            _emit_consolidated_ecf(owner_uid, open_shift['id'], pending, sandbox)
        except Exception as cons_err:
            print(f"⚠️ Error al emitir comprobante consolidado al cierre: {cons_err}")
            flash(f'Advertencia: No se pudo emitir el comprobante consolidado ({len(pending)} ventas pendientes). Revise el log.', 'warning')
    # -----------------------------------------

    try:
        declared_amount = float(request.form.get('declaredAmount', 0.0))
    except ValueError:
        declared_amount = 0.0

    res = DatabaseService.close_cash_shift(owner_uid, open_shift['id'], declared_amount, sandbox=sandbox)
    if res:
        diff = res["difference"]
        if abs(diff) < 0.01:
            flash('Caja cerrada exitosamente. ¡Cuadre perfecto!', 'success')
        elif diff > 0:
            flash(f'Caja cerrada con SOBRANTE de RD$ {diff:,.2f}.', 'warning')
        else:
            flash(f'Caja cerrada con FALTANTE de RD$ {abs(diff):,.2f}.', 'error')
    else:
        flash('Ocurrió un error al procesar el cierre de caja.', 'error')

    return redirect(url_for('web_pos.pos_dashboard'))


def _emit_consolidated_ecf(owner_uid, shift_id, pending_invoices, sandbox):
    """Función interna: agrupa las facturas pendientes y emite un único E32 consolidado."""
    from datetime import date as dt_date

    today_str = dt_date.today().strftime('%d/%m/%Y')
    total_sum = sum(inv['total'] for inv in pending_invoices)
    subtotal_sum = sum(inv['subtotal'] for inv in pending_invoices)
    itbis_sum = sum(inv['totalITBIS'] for inv in pending_invoices)
    invoice_ids = [inv['id'] for inv in pending_invoices]

    consolidado_id = str(uuid.uuid4())
    consolidado_number = f"CONS-{datetime.utcnow().strftime('%y%m%d%H%M%S')}"

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
        "date": datetime.utcnow().isoformat(),
        "dueDate": datetime.utcnow().isoformat(),
        "clientId": "default",
        "clientName": "Consumidor Final",
        "clientRNC": "999999999",
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

    DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, sandbox=sandbox)

    company = DatabaseService.get_company_profile(owner_uid)
    encf_consolidado = consolidado_number  # fallback
    try:
        res = EcfEmissionService.emit_electronic_comprobante(company, consolidado_dict, sandbox=sandbox)
        if res and res.get('success'):
            encf_consolidado = res.get('encf', consolidado_number)
            consolidado_dict["encf"] = encf_consolidado
            consolidado_dict["xmlSignature"] = res.get('xmlSignature', '')
            consolidado_dict["qrCodeURL"] = res.get('qrCodeURL', '')
            consolidado_dict["isSyncedWithDGII"] = True
            consolidado_dict["status"] = "Cobrada"
            DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, sandbox=sandbox)
    except Exception as ecf_err:
        print(f"⚠️ Error al emitir e-CF consolidado: {ecf_err}")
        consolidado_dict["emisionMode"] = "FALLBACK"
        DatabaseService.save_invoice(owner_uid, consolidado_id, consolidado_dict, sandbox=sandbox)

    # Marcar todas las facturas individuales como Consolidadas
    DatabaseService.mark_invoices_consolidated(
        owner_uid, invoice_ids, encf_consolidado, consolidado_number, sandbox=sandbox
    )

    print(f"✅ [Consolidado] Emitido {consolidado_number} cubriendo {len(invoice_ids)} ventas. ENCF: {encf_consolidado}")
    return encf_consolidado



@web_pos_bp.route('/pos/shift/transaction', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def add_manual_transaction():
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, sandbox=sandbox)
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
    
    res = DatabaseService.register_cash_transaction(owner_uid, tx_dict, sandbox=sandbox)
    if res:
        flash('Movimiento de caja registrado.', 'success')
        return redirect(url_for('web_pos.pos_dashboard'))
    else:
        flash('Fallo al registrar el movimiento de caja.', 'error')
        return redirect(url_for('web_pos.pos_dashboard'))


@web_pos_bp.route('/pos/terminal')
@require_open_shift
def pos_terminal():
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    # Obtener catálogo de productos para la venta rápida
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    
    # Filtrar solo bienes físicos o servicios del catálogo
    active_items = [it for it in items if it.get('price', 0.0) > 0]
    
    return render_template(
        'pos/terminal.html',
        active_page='pos',
        items=active_items
    )


@web_pos_bp.route('/pos/client/lookup', methods=['POST'])
@require_open_shift
def pos_client_lookup():
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json or {}
    rnc = (data.get('rnc') or '').strip().replace('-', '')
    if not rnc:
        return jsonify({"success": False, "error": "El RNC/Cédula es requerido."}), 400
        
    # 1. Buscar localmente en Firestore
    client = DatabaseService.get_client_by_rnc(owner_uid, rnc, sandbox=sandbox)
    if client:
        return jsonify({
            "success": True,
            "source": "local",
            "client": client
        })
        
    # 2. Buscar en el directorio de la DGII (Alanube)
    company = DatabaseService.get_company_profile(owner_uid)
    from app.services.alanube import AlanubeService
    res = AlanubeService.check_directory(company, rnc, sandbox=sandbox)
    
    if res.get('success'):
        # Encontrado en DGII
        real_data = res.get('data') or res
        razon_social = real_data.get('razonSocial') or real_data.get('companyName') or 'Empresa Homologada Electrónica SRL'
        
        # Registrar el cliente automáticamente para futuras transacciones
        import uuid
        client_id = str(uuid.uuid4())
        client_dict = {
            "rnc": rnc,
            "razonSocial": razon_social,
            "email": real_data.get('email', '').strip() or "contacto@cliente.com",
            "telefono": real_data.get('telefono', '').strip(),
            "direccion": real_data.get('address', '').strip() or "República Dominicana",
            "crmNotes": "Registrado automáticamente desde consulta RNC en POS",
            "nextContactDate": "",
            "createdAt": datetime.utcnow().isoformat()
        }
        DatabaseService.save_client(owner_uid, client_id, client_dict, sandbox=sandbox)
        
        return jsonify({
            "success": True,
            "source": "dgii",
            "client": {
                "id": client_id,
                "rnc": rnc,
                "razonSocial": razon_social,
                "email": client_dict["email"],
                "telefono": client_dict["telefono"],
                "direccion": client_dict["direccion"]
            }
        })
    else:
        return jsonify({
            "success": False,
            "error": "Cliente no encontrado localmente ni en la DGII."
        })


@web_pos_bp.route('/pos/invoice/new', methods=['POST'])
@require_open_shift
def create_pos_sale():
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    open_shift = DatabaseService.get_open_shift(owner_uid, user_uid, sandbox=sandbox)

    data = request.json
    client_id = data.get('clientId', '')
    client_name = data.get('clientName', 'Consumidor Final')
    client_rnc = data.get('clientRNC', '999999999')
    payment_method = data.get('paymentMethod', 'Efectivo')
    items_list = data.get('items', [])
    ecf_type = data.get('ecfType', 'Factura de Consumo (E32)')

    if ecf_type not in ['Factura de Consumo (E32)', 'Factura de Crédito Fiscal (E31)']:
        return jsonify({"success": False, "error": f"El Punto de Venta solo permite emitir Factura de Consumo (E32) o Crédito Fiscal (E31). El tipo '{ecf_type}' está restringido."}), 400

    if not items_list:
        return jsonify({"success": False, "error": "La venta no tiene productos."}), 400

    # Calcular totales
    parsed_items = []
    for it in items_list:
        parsed_items.append({
            "id": it["id"],
            "name": it["name"],
            "price": float(it["price"]),
            "quantity": int(it["quantity"]),
            "itbisRate": float(it.get("itbisRate", 0.18)),
            "discountRate": 0.0,
            "type": it.get("type", "Bien")
        })

    calcs = DGIIService.calculate_invoice_totals(parsed_items, discount_rate=0.0)

    invoice_id = str(uuid.uuid4())
    invoice_number = f"POS-{datetime.utcnow().strftime('%y%m%d%H%M%S')}"

    # --- Determinar si aplica modo consolidado ---
    # Condiciones DGII: E32, Consumidor Final (RNC 999999999), total < monto configurable de la empresa
    company = DatabaseService.get_company_profile(owner_uid)
    consolidation_enabled = company.get('consolidationEnabled', False)
    consolidation_threshold = float(company.get('consolidationThreshold') or 250000.0)
    is_consumer_final = (client_id == 'default' or client_rnc == '999999999')
    qualifies_for_consolidation = (
        consolidation_enabled
        and ecf_type == 'Factura de Consumo (E32)'
        and is_consumer_final
        and calcs['total'] < consolidation_threshold
    )
    # -------------------------------------------


    invoice_dict = {
        "invoiceNumber": invoice_number,
        "date": datetime.utcnow().isoformat(),
        "dueDate": datetime.utcnow().isoformat(),
        "clientId": client_id,
        "clientName": client_name,
        "clientRNC": client_rnc,
        "status": "PENDING_CONSOLIDATION" if qualifies_for_consolidation else "Cobrada",
        "ecfType": ecf_type,
        "currency": "DOP",
        "paymentType": "01 - Contado",
        "paymentMethod": payment_method,
        "incomeType": "01 - Ingresos por operaciones",
        "subtotal": calcs["subtotal"],
        "totalITBIS": calcs["total_itbis"],
        "total": calcs["total"],
        "netPayable": calcs["net_payable"],
        "isQuotation": False,
        "isConvertedToInvoice": False,
        "items": calcs["items"],
        "stockReduced": False,  # DatabaseService lo reducirá al guardar
        "posShiftId": open_shift['id'],  # Necesario para consultas de consolidación
        "isSyncedWithDGII": False
    }

    # 1. Guardar factura en base de datos
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, sandbox=sandbox)

    # 2. Registrar transacción financiera de caja
    tx_dict = {
        "shiftId": open_shift['id'],
        "type": "SALE",
        "amount": calcs["total"],
        "paymentMethod": payment_method,
        "referenceId": invoice_id,
        "notes": f"{'[CONSOLIDADO] ' if qualifies_for_consolidation else ''}Venta POS: {invoice_number}"
    }
    DatabaseService.register_cash_transaction(owner_uid, tx_dict, sandbox=sandbox)

    # 3. Si aplica modo consolidado → no emitir e-CF individual, retornar con indicador
    if qualifies_for_consolidation:
        return jsonify({
            "success": True,
            "invoiceId": invoice_id,
            "invoiceNumber": invoice_number,
            "total": calcs["total"],
            "encf": "(Consolidado al Cierre)",
            "consolidated": True
        })

    # 4. Intentar emisión electrónica (e-CF) individual
    company = DatabaseService.get_company_profile(owner_uid)
    try:
        res = EcfEmissionService.emit_electronic_comprobante(company, invoice_dict, sandbox=sandbox)
        if res and res.get('success'):
            # Actualizar campos de e-CF
            invoice_dict["encf"] = res.get('encf', '')
            invoice_dict["xmlSignature"] = res.get('xmlSignature', '')
            invoice_dict["qrCodeURL"] = res.get('qrCodeURL', '')
            invoice_dict["isSyncedWithDGII"] = True
            invoice_dict["status"] = "Cobrada"
            DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, sandbox=sandbox)
    except Exception as e:
        # Si falla, operamos en contingencia local
        print(f"⚠️ Error al emitir e-CF en POS: {e}")
        invoice_dict["emisionMode"] = "FALLBACK"
        invoice_dict["isSyncedWithDGII"] = False
        DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, sandbox=sandbox)
    # 4. Enviar factura y XML por correo SOLO si es Crédito Fiscal (E31) con cliente registrado.
    #    Las Facturas de Consumo (E32) son para consumidores finales y NO se envían por email.
    if ecf_type == 'Factura de Crédito Fiscal (E31)' and client_id and client_id != 'default':
        try:
            client = DatabaseService.get_client(owner_uid, client_id, sandbox=sandbox)
            if client and client.get('email'):
                recipient_email = client['email'].strip()
                if recipient_email:
                    from flask import current_app
                    flask_app = current_app._get_current_object()
                    import threading
                    
                    def send_invoice_email_bg(app_instance, o_uid, inv, email_to, sb, base):
                        with app_instance.app_context():
                            try:
                                from app.web.invoices import send_invoice_email
                                send_invoice_email(o_uid, inv, email_to, sb, base)
                            except Exception as th_err:
                                print(f"❌ Error en hilo de envío de correo POS: {th_err}")
                                
                    host_url = request.host_url
                    threading.Thread(
                        target=send_invoice_email_bg,
                        args=(flask_app, owner_uid, invoice_dict, recipient_email, sandbox, host_url)
                    ).start()
                    print(f"📧 [POS] Correo de e-CF programado para {recipient_email} para factura {invoice_number}", flush=True)
        except Exception as email_err:
            print(f"⚠️ Error al iniciar hilo de envío de correo en POS: {email_err}")
            
    return jsonify({
        "success": True,
        "invoiceId": invoice_id,
        "invoiceNumber": invoice_number,
        "total": calcs["total"],
        "encf": invoice_dict.get("encf", "Contingencia")
    })


@web_pos_bp.route('/pos/invoice/<invoice_id>/print')
@require_permission('canManagePOS', 'Impresión POS')
def print_receipt(invoice_id):
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return "Factura no encontrada.", 404
        
    company = DatabaseService.get_company_profile(owner_uid)
    
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
        rnc_emisor = company.get("companyRNC", "").replace("-", "").strip()
        rnc_comprador = invoice.get("clientRNC", "").replace("-", "").strip()
        if not rnc_comprador: rnc_comprador = "999999999"
        monto_total = f"{invoice.get('total', 0.0):.2f}"
        
        is_consumo = 'Consumo' in invoice.get("ecfType", "")
        if is_consumo and invoice.get("total", 0.0) < 250000:
            query_params = {
                "RncEmisor": rnc_emisor,
                "ENCF": invoice.get("encf"),
                "MontoTotal": monto_total,
                "CodigoSeguridad": codigo_seg
            }
            qs = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
            qr_url = "https://fc.dgii.gov.do/eCF/ConsultaTimbreFC?" + qs
        else:
            query_params = {
                "RncEmisor": rnc_emisor,
                "RncComprador": rnc_comprador,
                "ENCF": invoice.get("encf"),
                "FechaEmision": fecha_emision_str,
                "MontoTotal": monto_total,
                "FechaFirma": fecha_firma_str,
                "CodigoSeguridad": codigo_seg
            }
            qs = urllib.parse.urlencode(query_params, quote_via=urllib.parse.quote)
            qr_url = "https://ecf.dgii.gov.do/ecf/ConsultaTimbre?" + qs
            
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
            
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
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


@web_pos_bp.route('/pos/register/new', methods=['POST'])
@require_permission('canManagePOS', 'Punto de Venta')
def create_cash_register():
    if session['user'].get('role') != 'owner':
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="Propietario")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    name = request.form.get('name', '').strip()
    if not name:
        flash('El nombre de la caja es obligatorio.', 'error')
        return redirect(url_for('web_pos.pos_admin_dashboard'))
        
    register_id = f"caja-{uuid.uuid4().hex[:8]}"
    register_dict = {
        "name": name,
        "status": "CLOSED",
        "createdAt": datetime.utcnow().isoformat()
    }
    
    DatabaseService.save_cash_register(owner_uid, register_id, register_dict, sandbox=sandbox)
    flash(f'Caja registradora "{name}" creada correctamente.', 'success')
    return redirect(url_for('web_pos.pos_admin_dashboard'))


@web_pos_bp.route('/pos/admin')
@require_permission('canManagePOS', 'Administración de Caja')
def pos_admin_dashboard():
    if session['user'].get('role') != 'owner':
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="Propietario")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    registers = DatabaseService.get_cash_registers(owner_uid, sandbox=sandbox)
    shifts = DatabaseService.get_cash_shifts(owner_uid, sandbox=sandbox)
    
    # Map registers name to shifts
    regs_map = {r['id']: r['name'] for r in registers}
    for s in shifts:
        s['registerName'] = regs_map.get(s['registerId'], 'Caja Desconocida')
        
    return render_template(
        'pos/admin.html',
        active_page='pos',
        registers=registers,
        shifts=shifts
    )


@web_pos_bp.route('/pos/admin/shift/<shift_id>')
@require_permission('canManagePOS', 'Administración de Caja')
def pos_admin_shift_detail(shift_id):
    if session['user'].get('role') != 'owner':
        return render_template('auth/restricted.html', feature_name="Administración de Cajas", required_permission="Propietario")

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    shifts = DatabaseService.get_cash_shifts(owner_uid, sandbox=sandbox)
    shift = next((s for s in shifts if s['id'] == shift_id), None)
    if not shift:
        flash('Turno no encontrado.', 'error')
        return redirect(url_for('web_pos.pos_admin_dashboard'))

    registers = DatabaseService.get_cash_registers(owner_uid, sandbox=sandbox)
    register = next((r for r in registers if r['id'] == shift['registerId']), None)
    shift['registerName'] = register['name'] if register else 'Caja Desconocida'

    transactions = DatabaseService.get_cash_transactions(owner_uid, shift_id, sandbox=sandbox)

    return render_template(
        'pos/shift_detail.html',
        active_page='pos',
        shift=shift,
        transactions=transactions
    )


@web_pos_bp.route('/pos/register/<register_id>/toggle-consolidation', methods=['POST'])
@require_permission('canManagePOS', 'Administración de Caja')
def toggle_consolidation_mode(register_id):
    """Activa o desactiva el modo comprobante consolidado para una caja registradora."""
    if session['user'].get('role') != 'owner':
        return jsonify({"success": False, "error": "Solo el propietario puede cambiar esta configuración."}), 403

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or {}
    enabled = bool(data.get('enabled', False))

    DatabaseService.update_cash_register_settings(
        owner_uid, register_id, {"consolidationMode": enabled}, sandbox=sandbox
    )
    mode_str = "activado" if enabled else "desactivado"
    return jsonify({"success": True, "consolidationMode": enabled, "message": f"Modo consolidado {mode_str}."})
