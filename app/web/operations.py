from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from app.services.db_service import DatabaseService
from app.services.recurrence import RecurrenceService
from app.utils.decorators import check_permission
from datetime import datetime, timedelta
import uuid
import random

web_operations_bp = Blueprint('web_operations', __name__)

# =========================================================================
# GESTIÓN DE CONTRATOS Y FACTURACIÓN RECURRENTE
# =========================================================================

@web_operations_bp.route('/operations/contracts/new', methods=['GET'])
def new_contract():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html', feature_name="Contratos y Facturación Recurrente", required_permission="canManageContracts")
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
    return render_template(
        'operations/new_contract.html',
        active_page='contracts',
        clients=clients,
        items=items
    )

@web_operations_bp.route('/operations/contracts', methods=['GET', 'POST'])
def list_contracts():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html', feature_name="Contratos y Facturación Recurrente", required_permission="canManageContracts")
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    if request.method == 'POST':
        contract_id = request.form.get('id') or str(uuid.uuid4())
        client_id   = request.form.get('clientId')
        clients_all = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
        client      = next((c for c in clients_all if c['id'] == client_id), None)

        if not client:
            flash("Cliente no válido.", "error")
            return redirect(url_for('web_operations.new_contract'))

        # ── Parsear líneas del contrato (Fase 2) ──────────────────────────────
        line_item_ids    = request.form.getlist('lineItemId')
        line_names       = request.form.getlist('lineName')
        line_codes       = request.form.getlist('lineCode')
        line_qtys        = request.form.getlist('lineQty')
        line_prices      = request.form.getlist('linePrice')
        line_itbis_rates = request.form.getlist('lineItbisRate')

        contract_lines = []
        total_amount   = 0.0
        total_itbis    = 0.0
        total_subtotal = 0.0

        for i in range(len(line_item_ids)):
            if not line_item_ids[i]:
                continue
            qty        = float(line_qtys[i])        if i < len(line_qtys)        else 1.0
            unit_price = float(line_prices[i])      if i < len(line_prices)      else 0.0
            itbis_pct  = float(line_itbis_rates[i]) if i < len(line_itbis_rates) else 18.0
            itbis_rate = itbis_pct / 100.0
            subtotal   = round(qty * unit_price, 2)
            itbis_amt  = round(subtotal * itbis_rate, 2)
            line_total = round(subtotal + itbis_amt, 2)
            total_subtotal += subtotal
            total_itbis    += itbis_amt
            total_amount   += line_total
            contract_lines.append({
                "itemId":      line_item_ids[i],
                "name":        line_names[i] if i < len(line_names) else "",
                "code":        line_codes[i] if i < len(line_codes) else "",
                "quantity":    qty,
                "unitPrice":   unit_price,
                "itbisRate":   itbis_rate,
                "subtotal":    subtotal,
                "itbisAmount": itbis_amt,
                "total":       line_total
            })

        if not contract_lines:
            total_amount = float(request.form.get('amount', 0.0))

        contract_dict = {
            "contractNumber":   request.form.get('contractNumber') or f"CON-{random.randint(1000, 9999)}",
            "clientId":         client_id,
            "clientName":       client.get("razonSocial", ""),
            "clientRNC":        client.get("rnc", ""),
            "itemId":           contract_lines[0]["itemId"] if contract_lines else "",
            "contractLines":    contract_lines,
            "amount":           round(total_amount, 2),
            "totalSubtotal":    round(total_subtotal, 2),
            "totalITBIS":       round(total_itbis, 2),
            "recurrenceInterval": request.form.get('recurrenceInterval', 'mensual'),
            "status":           request.form.get('status', 'Activo'),
            "startDate":        request.form.get('startDate', datetime.utcnow().strftime("%Y-%m-%d")),
            "endDate":          request.form.get('endDate', ""),
            "nextBillingDate":  request.form.get('nextBillingDate', datetime.utcnow().strftime("%Y-%m-%d")),
            "notes":            request.form.get('notes', ""),
            "autoSendEmail":    request.form.get('autoSendEmail') == 'on',
            "autoRenew":        request.form.get('autoRenew') == 'on'
        }

        DatabaseService.save_contract(owner_uid, contract_id, contract_dict, sandbox=sandbox)
        flash("Contrato guardado exitosamente.", "success")
        return redirect(url_for('web_operations.list_contracts'))

    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox)
    items = DatabaseService.get_items(owner_uid, sandbox=sandbox)

    # Exportar a CSV si se solicita
    if request.args.get('export') == 'csv':
        import csv
        import io
        from flask import send_file
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)
        writer.writerow(["Número de Contrato", "Cliente", "RNC", "Monto Fijo (RD$)", "Frecuencia", "Fecha Inicio", "Fecha Fin", "Próximo Cobro", "Estatus"])
        for c in contracts:
            writer.writerow([
                c.get("contractNumber", ""),
                c.get("clientName", ""),
                c.get("clientRNC", ""),
                f"{c.get('amount', 0.0):.2f}",
                c.get("recurrenceInterval", ""),
                c.get("startDate", ""),
                c.get("endDate", ""),
                c.get("nextBillingDate", ""),
                c.get("status", "")
            ])
        dest = io.BytesIO()
        dest.write(b'\xef\xbb\xbf')  # UTF-8 BOM
        dest.write(output.getvalue().encode('utf-8'))
        dest.seek(0)
        filename = f"contratos_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(
            dest,
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )
    
    # Calcular estadísticas del panel de contratos
    total_active = sum(1 for c in contracts if c.get('status') == 'Activo')
    monthly_estimate = sum(c.get('amount', 0.0) for c in contracts if c.get('status') == 'Activo')
    total_contracts = len(contracts)
    
    return render_template(
        'operations/contracts.html',
        active_page='contracts',
        contracts=contracts,
        clients=clients,
        items=items,
        total_active=total_active,
        monthly_estimate=monthly_estimate,
        total_contracts=total_contracts
    )

@web_operations_bp.route('/operations/contracts/<contract_id>/toggle', methods=['POST'])
def toggle_contract(contract_id):
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    if not check_permission('canManageContracts'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    contract = next((c for c in contracts if c['id'] == contract_id), None)
    
    if contract:
        new_status = 'Inactivo' if contract.get('status') == 'Activo' else 'Activo'
        contract['status'] = new_status
        DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
        return jsonify({"success": True, "new_status": new_status})
        
    return jsonify({"success": False, "error": "Contrato no encontrado"}), 404

@web_operations_bp.route('/operations/contracts/<contract_id>/status', methods=['POST'])
def set_contract_status(contract_id):
    if 'user' not in session: return jsonify({"success": False, "error": "No autorizado"}), 401
    if not check_permission('canManageContracts'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.get_json() or {}
    new_status = data.get('status', '').strip()
    
    valid_statuses = ['Borrador', 'Pendiente de Aprobación', 'Activo', 'Suspendido', 'Cancelado', 'Expirado', 'Inactivo']
    if new_status not in valid_statuses:
        return jsonify({"success": False, "error": f"Estado no válido: {new_status}"}), 400
    
    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    contract = next((c for c in contracts if c['id'] == contract_id), None)
    
    if contract:
        contract['status'] = new_status
        DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
        return jsonify({"success": True, "new_status": new_status})
        
    return jsonify({"success": False, "error": "Contrato no encontrado"}), 404

@web_operations_bp.route('/operations/contracts/<contract_id>/delete', methods=['POST'])
def delete_contract_route(contract_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_contract(owner_uid, contract_id, sandbox=sandbox)
    flash("Contrato eliminado correctamente.", "success")
    return redirect(url_for('web_operations.list_contracts'))

@web_operations_bp.route('/operations/contracts/<contract_id>/trigger', methods=['POST'])
def trigger_contract_billing(contract_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html', feature_name="Contratos y Facturación Recurrente", required_permission="canManageContracts")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
    contract = next((c for c in contracts if c['id'] == contract_id), None)
    
    if not contract:
        flash("Contrato no encontrado.", "error")
        return redirect(url_for('web_operations.list_contracts'))
    
    # Solo los contratos Activos pueden generar facturas
    if contract.get('status') != 'Activo':
        flash(f"El contrato '{contract.get('contractNumber')}' tiene estado '{contract.get('status')}' y no puede generar facturas. Debes activarlo primero.", "warning")
        return redirect(url_for('web_operations.list_contracts'))
    
    # Verificar si el contrato ha expirado por fecha
    end_date = contract.get('endDate', '')
    next_billing = contract.get('nextBillingDate', '')
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    if end_date and next_billing and next_billing > end_date:
        if contract.get('autoRenew'):
            # Calcular nueva fecha de vencimiento extendiendo por el mismo intervalo
            from app.services.recurrence import RecurrenceService
            new_end = RecurrenceService.calculate_next_date(end_date, contract.get('recurrenceInterval', 'mensual'))
            contract['endDate'] = new_end
            DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
            flash(f"Contrato '{contract.get('contractNumber')}' renovado automáticamente hasta {new_end}.", "info")
        else:
            contract['status'] = 'Expirado'
            DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
            flash(f"El contrato '{contract.get('contractNumber')}' ha vencido y fue marcado como Expirado.", "warning")
            return redirect(url_for('web_operations.list_contracts'))
        
    # Crear factura e-CF
    random_num = f"{random.randint(1, 999999):06d}"
    invoice_number = f"FAC-{random_num}"
    invoice_id = str(uuid.uuid4())
    
    # ── Construir ítems de la factura ─────────────────────────────────────────
    contract_lines = contract.get('contractLines', [])

    if contract_lines:
        # FASE 2: Contrato con múltiples líneas
        items         = []
        subtotal      = 0.0
        itbis_amount  = 0.0
        total_invoice = 0.0
        for line in contract_lines:
            qty        = float(line.get('quantity', 1))
            unit_price = float(line.get('unitPrice', 0))
            itbis_rate = float(line.get('itbisRate', 0.18))
            line_sub   = round(qty * unit_price, 2)
            line_itbis = round(line_sub * itbis_rate, 2)
            line_total = round(line_sub + line_itbis, 2)
            items.append({
                "id":           str(uuid.uuid4()),
                "code":         line.get('code', 'SERV-REC'),
                "type":         line.get('type', 'Servicio'),
                "name":         f"{line.get('name', 'Servicio')} — {contract.get('contractNumber')}",
                "price":        unit_price,
                "quantity":     qty,
                "itbisRate":    itbis_rate,
                "discountRate": 0.0,
                "subtotal":     line_sub,
                "itbis_amount": line_itbis,
                "total":        line_total
            })
            subtotal      += line_sub
            itbis_amount  += line_itbis
            total_invoice += line_total
    else:
        # FASE 1 (compatibilidad): Contrato de ítem único
        contract_item_id = contract.get('itemId')
        selected_item = None
        if contract_item_id:
            all_items = DatabaseService.get_items(owner_uid, sandbox=sandbox)
            selected_item = next((it for it in all_items if it['id'] == contract_item_id), None)

        itbis_rate   = selected_item.get('itbisRate', 0.18) if selected_item else 0.18
        subtotal     = round(contract['amount'] / (1 + itbis_rate), 2)
        itbis_amount = round(contract['amount'] - subtotal, 2)
        total_invoice = contract['amount']
        items = [{
            "id":           str(uuid.uuid4()),
            "code":         selected_item.get('code', 'SERV-REC') if selected_item else 'SERV-REC',
            "type":         selected_item.get('type', 'Servicio') if selected_item else 'Servicio',
            "name":         f"{selected_item.get('name', 'Servicio Contratado')} ({contract.get('contractNumber')})" if selected_item else f"Servicio Contratado ({contract.get('contractNumber')})",
            "price":        subtotal,
            "quantity":     1,
            "itbisRate":    itbis_rate,
            "discountRate": 0.0,
            "subtotal":     subtotal,
            "itbis_amount": itbis_amount,
            "total":        total_invoice
        }]
    
    invoice_dict = {
        "id": invoice_id,
        "invoiceNumber": invoice_number,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "dueDate": (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "clientId": contract['clientId'],
        "clientName": contract['clientName'],
        "clientRNC": contract['clientRNC'],
        "status": "Emitida",
        "ecfType": "Factura de Consumo (E32)",
        "encf": "E32PENDIENTE",
        "xmlSignature": "",
        "qrCodeURL": "",
        "isSyncedWithDGII": False,
        "creditedAmount": 0.0,
        "retainedISR": 0.0,
        "retainedITBIS": 0.0,
        "netPayable": round(total_invoice, 2),
        "subtotal": round(subtotal, 2),
        "totalITBIS": round(itbis_amount, 2),
        "total": round(total_invoice, 2),
        "isQuotation": False,
        "isConvertedToInvoice": False,
        "notes": f"Generado automáticamente desde Contrato {contract.get('contractNumber')}",
        "comentario": contract.get('notes', ''),
        "isRecurring": False,
        "firebasePDFURL": "",
        "firebaseXMLURL": "",
        "currency": "DOP",
        "paymentType": "Contado",
        "paymentMethod": "Efectivo",
        "incomeType": "01 - Ingresos por operaciones",
        "exchangeRate": 1.0,
        "registeredBy": session['user']['email'],
        "contractId": contract_id,
        "contractNumber": contract.get('contractNumber', ''),
        "items": items
    }
    
    # Guardar factura
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, sandbox=sandbox)
    
    # Actualizar fecha de próxima ocurrencia en el contrato
    next_date = RecurrenceService.calculate_next_date(contract.get("nextBillingDate"), contract.get("recurrenceInterval"))
    contract["nextBillingDate"] = next_date
    DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
    
    # Enviar email automático si está configurado
    if contract.get('autoSendEmail') and invoice_dict.get('clientId'):
        try:
            client_record = DatabaseService.get_client(owner_uid, invoice_dict['clientId'], sandbox=sandbox)
            if client_record and client_record.get('email'):
                recipient_email = client_record['email'].strip()
                if recipient_email:
                    from flask import current_app, request
                    flask_app = current_app._get_current_object()
                    import threading
                    
                    def send_invoice_email_bg(app_instance, o_uid, inv, email_to, sb, base):
                        with app_instance.app_context():
                            try:
                                from app.web.invoices import send_invoice_email
                                send_invoice_email(o_uid, inv, email_to, sb, base)
                            except Exception as th_err:
                                print(f"❌ Error en hilo de envío de correo Contrato: {th_err}")
                                
                    host_url = request.host_url
                    threading.Thread(
                        target=send_invoice_email_bg,
                        args=(flask_app, owner_uid, invoice_dict, recipient_email, sandbox, host_url)
                    ).start()
                    print(f"📧 [Contratos] Correo programado para {recipient_email} para factura {invoice_number}", flush=True)
        except Exception as email_err:
            print(f"⚠️ Error al iniciar hilo de envío automático en contratos: {email_err}")
            
    flash(f"¡Factura {invoice_number} por RD$ {contract['amount']:,.2f} generada y programada con éxito!", "success")
    return redirect(url_for('web_operations.list_contracts'))

# =========================================================================
# CONTROL DE COMISIONES Y RENDIMIENTO (GAMIFICACIÓN)
# =========================================================================

@web_operations_bp.route('/operations/commissions', methods=['GET', 'POST'])
def list_commissions():
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageCommissions'):
        return render_template('auth/restricted.html', feature_name="Comisiones y Metas", required_permission="canManageCommissions")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    if request.method == 'POST':
        if 'percentage' in request.form:
            # Configuración de comisiones
            settings_dict = {
                "percentage": float(request.form.get('percentage', 5.0)),
                "payOn": request.form.get('payOn', 'cobrada')
            }
            DatabaseService.save_commission_settings(owner_uid, settings_dict)
            flash("Configuración de comisiones actualizada.", "success")
        elif 'monthlyGoal' in request.form:
            # Metas mensuales de ventas
            goals_dict = {
                "monthlyGoal": float(request.form.get('monthlyGoal', 500000.0))
            }
            DatabaseService.save_sales_goals(owner_uid, goals_dict)
            flash("Metas de venta de la empresa actualizadas.", "success")
        return redirect(url_for('web_operations.list_commissions'))
        
    # Cargar datos
    settings = DatabaseService.get_commission_settings(owner_uid)
    goals = DatabaseService.get_sales_goals(owner_uid)
    team = DatabaseService.get_team_members(owner_uid)
    invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
    
    # Filtrar facturas reales
    real_invoices = [inv for inv in invoices if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']]
    
    # Calcular ventas totales y comisiones por vendedor
    sellers_data = {}
    
    # Inicializar con los miembros del equipo
    for member in team:
        sellers_data[member['email']] = {
            "name": member['name'],
            "email": member['email'],
            "total_invoiced": 0.0,
            "total_collected": 0.0,
            "commission_earned": 0.0,
            "invoice_count": 0
        }
    # Añadir al propietario también por si emite facturas
    owner_email = session['user']['email']
    if owner_email not in sellers_data:
        sellers_data[owner_email] = {
            "name": session['user'].get('name', 'Propietario'),
            "email": owner_email,
            "total_invoiced": 0.0,
            "total_collected": 0.0,
            "commission_earned": 0.0,
            "invoice_count": 0
        }
        
    for inv in real_invoices:
        reg_by = inv.get('registeredBy') or owner_email
        if reg_by not in sellers_data:
            sellers_data[reg_by] = {
                "name": reg_by.split('@')[0],
                "email": reg_by,
                "total_invoiced": 0.0,
                "total_collected": 0.0,
                "commission_earned": 0.0,
                "invoice_count": 0
            }
            
        inv_total = inv.get('total', 0.0)
        sellers_data[reg_by]["total_invoiced"] += inv_total
        sellers_data[reg_by]["invoice_count"] += 1
        
        # Calcular recaudado (cobrado)
        if inv.get('status') == 'Saldada':
            sellers_data[reg_by]["total_collected"] += inv_total
        else:
            # Obtener abonos
            try:
                abonos = DatabaseService.get_invoice_abonos(owner_uid, inv['id'], sandbox=sandbox)
                collected = sum(ab.get('amount', 0.0) for ab in abonos)
                sellers_data[reg_by]["total_collected"] += collected
            except Exception:
                pass

    # Calcular comisión final
    pct = settings.get('percentage', 5.0) / 100.0
    pay_on = settings.get('payOn', 'cobrada')
    
    total_sales_month = 0.0
    
    for email, data in sellers_data.items():
        if pay_on == 'cobrada':
            data["commission_earned"] = data["total_collected"] * pct
        else:
            data["commission_earned"] = data["total_invoiced"] * pct
        total_sales_month += data["total_invoiced"]
            
    # Ordenar ranking para Gamificación
    ranking = sorted(sellers_data.values(), key=lambda x: x["total_invoiced"], reverse=True)
    
    # Progreso de meta mensual
    goal_amount = goals.get('monthlyGoal', 500000.0)
    goal_pct = min(100.0, (total_sales_month / goal_amount) * 100.0) if goal_amount > 0 else 0.0
    
    return render_template(
        'operations/commissions.html',
        active_page='commissions',
        settings=settings,
        goals=goals,
        ranking=ranking,
        total_sales_month=total_sales_month,
        goal_pct=goal_pct,
        goal_amount=goal_amount
    )

# =========================================================================
# GESTIÓN DOCUMENTAL DE CLIENTES (RUTAS AJAX)
# =========================================================================

@web_operations_bp.route('/clients/<client_id>/documents/upload', methods=['POST'])
def upload_client_document_route(client_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    file = request.files.get('file')
    doc_type = request.form.get('documentType', 'Contrato Legal')
    notes = request.form.get('notes', '')
    
    if not file or not file.filename:
        flash("Por favor, selecciona un archivo válido.", "error")
        return redirect(url_for('web_clients.client_detail', client_id=client_id))
        
    try:
        file_data = file.read()
        mime_type = file.mimetype or "application/octet-stream"
        filename = f"doc_{client_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
        destination_path = f"users/{owner_uid}/crm_documents/{filename}"
        
        # Guardar en Firebase Storage
        url = DatabaseService.upload_file_to_storage(
            file_data=file_data,
            destination_path=destination_path,
            mime_type=mime_type
        )
        
        # Registrar en la base de datos
        doc_id = str(uuid.uuid4())
        doc_dict = {
            "documentType": doc_type,
            "name": file.filename,
            "url": url,
            "uploadedBy": session['user']['email'],
            "createdAt": datetime.utcnow().isoformat(),
            "notes": notes
        }
        
        DatabaseService.save_client_document(owner_uid, client_id, doc_id, doc_dict, sandbox=sandbox)
        flash("Documento cargado de forma segura y adjuntado al historial del cliente.", "success")
        
    except Exception as e:
        flash(f"Error al subir el archivo: {html.escape(str(e))}", "error")
        
    return redirect(url_for('web_clients.client_detail', client_id=client_id))

@web_operations_bp.route('/clients/<client_id>/documents/<doc_id>/delete', methods=['POST'])
def delete_client_document_route(client_id, doc_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'): return jsonify({"success": False, "error": "Sin permisos"}), 403
    
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_client_document(owner_uid, client_id, doc_id, sandbox=sandbox)
    flash("Documento eliminado del archivo centralizado del cliente.", "success")
    return redirect(url_for('web_clients.client_detail', client_id=client_id))


def _get_taggable_users(owner_uid):
    taggable_users = []
    owner_prof = DatabaseService.get_user_profile(owner_uid)
    if owner_prof:
        taggable_users.append({
            "uid": owner_uid,
            "name": owner_prof.get("name", "Propietario"),
            "email": owner_prof.get("email", ""),
            "role": "owner"
        })
    team = DatabaseService.get_team_members(owner_uid) or []
    for member in team:
        taggable_users.append({
            "uid": member.get("uid"),
            "name": member.get("name", ""),
            "email": member.get("email", ""),
            "role": member.get("role", "collaborator")
        })
    return taggable_users


def process_resource_comment_mentions(owner_uid, content, resource_type, resource_id, resource_label, sandbox):
    taggable_users = _get_taggable_users(owner_uid)
    for u in taggable_users:
        name = u.get("name", "")
        email = u.get("email", "")
        uid = u.get("uid")
        if not uid or not email:
            continue
            
        if 'user' in session and session['user'].get('uid') == uid:
            continue
            
        import re
        escaped_name = re.escape(name)
        escaped_email = re.escape(email)
        pattern = rf"@({escaped_name}|{escaped_email})\b"
        if re.search(pattern, content, re.IGNORECASE):
            notif_id = str(uuid.uuid4())
            
            if resource_type == "contracts":
                link = f"/contracts/{resource_id}?sandbox={'true' if sandbox else 'false'}"
                msg = f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del contrato: {resource_label}."
            else:
                link = f"/operations/contracts?sandbox={'true' if sandbox else 'false'}"
                msg = f"{session['user'].get('name', session['user']['email'])} te mencionó en un comentario del contrato: {resource_label}."
                
            notif_dict = {
                "id": notif_id,
                "title": "Nueva mención en un comentario",
                "message": msg,
                "documentId": resource_id,
                "documentNumber": resource_label,
                "link": link,
                "createdAt": datetime.utcnow().isoformat(),
                "read": False,
                "type": "mention"
            }
            DatabaseService.create_user_notification(uid, notif_dict)
            
            from flask import request
            import os
            try:
                base_url = request.host_url.rstrip('/')
            except Exception:
                base_url = os.environ.get("PORTAL_BASE_URL", "http://localhost:5001").rstrip('/')
            doc_url = f"{base_url}{link}"
            
            from app.services.notifications import NotificationService
            
            # Obtener el nombre comercial de la empresa
            company = DatabaseService.get_company(owner_uid) or {}
            issuer_company_name = company.get("tradeName") or company.get("companyName") or "e-Factura"
            
            NotificationService.send_mention_notification(
                recipient_email=email,
                recipient_name=name,
                commenter_name=session['user'].get('name', session['user']['email']),
                comment_snippet=content[:150] + ("..." if len(content) > 150 else ""),
                doc_number=resource_label,
                doc_url=doc_url,
                issuer_company_name=issuer_company_name,
                sandbox=sandbox
            )


def format_mentions(content, users):
    if not content:
        return ""
    from markupsafe import Markup
    import re
    import html
    escaped_content = html.escape(content)
    sorted_users = sorted(users, key=lambda x: len(x.get("name", "")), reverse=True)
    for u in sorted_users:
        name = u.get("name", "")
        email = u.get("email", "")
        if not name:
            continue
        escaped_name = re.escape(html.escape(name))
        escaped_email = re.escape(html.escape(email))
        pattern = rf"@({escaped_name}|{escaped_email})\b"
        replacement = r'<span class="mention-tag" style="background-color: rgba(124, 58, 237, 0.15); color: var(--accent-purple); font-weight: 600; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(124, 58, 237, 0.25);">@\1</span>'
        escaped_content = re.sub(pattern, replacement, escaped_content, flags=re.IGNORECASE)
    return Markup(escaped_content)


@web_operations_bp.route('/contracts/<contract_id>')
def contract_detail(contract_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    if not check_permission('canManageContracts'):
        return render_template('auth/restricted.html', feature_name="Detalle de Contrato", required_permission="canManageContracts")
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    contract = DatabaseService.get_contract(owner_uid, contract_id, sandbox=sandbox)
    if not contract:
        flash('Contrato no encontrado.', 'error')
        return redirect(url_for('web_operations.list_contracts'))
        
    comments = DatabaseService.get_resource_comments(owner_uid, "contracts", contract_id, sandbox=sandbox)
    taggable_users = _get_taggable_users(owner_uid)
    contract_invoices = DatabaseService.get_invoices_by_contract(owner_uid, contract_id, sandbox=sandbox)
    # Ordenar por fecha descendente
    contract_invoices.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    return render_template(
        'contracts/detail.html',
        active_page='contracts',
        contract=contract,
        comments=comments,
        taggable_users=taggable_users,
        format_mentions=format_mentions,
        contract_invoices=contract_invoices
    )


@web_operations_bp.route('/contracts/<contract_id>/comments/new', methods=['POST'])
def add_contract_comment(contract_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))
        
    attachment_url = ""
    attachment_name = ""
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_contract_{contract_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            attachment_name = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    comment_id = str(uuid.uuid4())
    comment_dict = {
        "content": content,
        "createdBy": session['user']['email'],
        "createdByName": session['user'].get('name', session['user']['email']),
        "createdByUid": session['user']['uid'],
        "createdAt": datetime.utcnow().isoformat(),
        "attachmentUrl": attachment_url,
        "attachmentName": attachment_name,
        "edited": False
    }
    
    DatabaseService.save_resource_comment(owner_uid, "contracts", contract_id, comment_id, comment_dict, sandbox=sandbox)
    
    try:
        contract = DatabaseService.get_contract(owner_uid, contract_id, sandbox=sandbox) or {}
        num = contract.get('contractNumber', 'Contrato')
        process_resource_comment_mentions(owner_uid, content, "contracts", contract_id, num, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en add_contract_comment: {ex}")
        
    flash('Comentario agregado exitosamente.', 'success')
    return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))


@web_operations_bp.route('/contracts/<contract_id>/comments/<comment_id>/edit', methods=['POST'])
def edit_contract_comment(contract_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_resource_comments(owner_uid, "contracts", contract_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))
        
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para editar este comentario.', 'error')
        return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))
        
    content = request.form.get('content', '').strip()
    if not content:
        flash('El comentario no puede estar vacío.', 'error')
        return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))
        
    comment['content'] = content
    comment['edited'] = True
    comment['editedAt'] = datetime.utcnow().isoformat()
    
    file = request.files.get('attachment')
    if file and file.filename:
        try:
            file_data = file.read()
            mime_type = file.mimetype or "application/octet-stream"
            filename = f"comment_contract_{contract_id}_{str(uuid.uuid4())[:8]}_{file.filename}"
            destination_path = f"users/{owner_uid}/comments/{filename}"
            attachment_url = DatabaseService.upload_file_to_storage(file_data, destination_path, mime_type)
            comment['attachmentUrl'] = attachment_url
            comment['attachmentName'] = file.filename
        except Exception as e:
            flash(f"Advertencia: No se pudo cargar el archivo adjunto: {html.escape(str(e))}", 'warning')
            
    DatabaseService.save_resource_comment(owner_uid, "contracts", contract_id, comment_id, comment, sandbox=sandbox)
    
    try:
        contract = DatabaseService.get_contract(owner_uid, contract_id, sandbox=sandbox) or {}
        num = contract.get('contractNumber', 'Contrato')
        process_resource_comment_mentions(owner_uid, content, "contracts", contract_id, num, sandbox)
    except Exception as ex:
        print(f"⚠️ Error al procesar menciones en edit_contract_comment: {ex}")
        
    flash('Comentario modificado.', 'success')
    return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))


@web_operations_bp.route('/contracts/<contract_id>/comments/<comment_id>/delete', methods=['POST'])
def delete_contract_comment(contract_id, comment_id):
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    comments = DatabaseService.get_resource_comments(owner_uid, "contracts", contract_id, sandbox=sandbox)
    comment = next((c for c in comments if c['id'] == comment_id), None)
    if not comment:
        flash('Comentario no encontrado.', 'error')
        return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))
        
    is_owner = session['user'].get('role') == 'owner'
    is_author = session['user']['uid'] == comment.get('createdByUid')
    if not (is_owner or is_author):
        flash('No tienes permiso para eliminar este comentario.', 'error')
        return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))
        
    DatabaseService.delete_resource_comment(owner_uid, "contracts", contract_id, comment_id, sandbox=sandbox)
    flash('Comentario eliminado.', 'success')
    return redirect(url_for('web_operations.contract_detail', contract_id=contract_id))


@web_operations_bp.route('/contracts/billing/trigger-test', methods=['POST'])
def trigger_contract_billing_route():
    """
    Ruta para pruebas en sandbox: permite gatillar manualmente el proceso
    de facturación recurrente de contratos.
    """
    if 'user' not in session: return redirect(url_for('web_auth.login'))
    sandbox = session.get('sandbox', False)
    if not sandbox:
        flash('Esta acción solo está permitida en modo Sandbox.', 'error')
        return redirect(url_for('web_operations.contracts_list'))
        
    owner_uid = session['user']['uid']
    from app.services.recurrence import RecurrenceService
    
    try:
        # Ejecutar facturación para el owner actual
        created_count = RecurrenceService.process_pending_contracts(owner_uid, sandbox=True)
        flash(f'Proceso completado. Se generaron {created_count} facturas recurrentes.', 'success')
    except Exception as e:
        import traceback
        logging.getLogger(__name__).error(f"Error en trigger_contract_billing_route: {str(e)}\n{traceback.format_exc()}")
        flash(f'Error al procesar facturación: {str(e)}', 'error')
        
    return redirect(url_for('web_operations.contracts_list'))


