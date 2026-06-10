import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from firebase_admin import firestore
from app.services.db_service import db_firestore, DatabaseService

portal_bp = Blueprint('portal', __name__, template_folder='templates')

class PortalDbService:
    @classmethod
    def get_client_by_id(cls, owner_uid, client_id, sandbox=True):
        try:
            coll_name = "sandbox_clients" if sandbox else "clients"
            doc = db_firestore.collection('users').document(owner_uid).collection(coll_name).document(client_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
        except Exception as e:
            print(f"Error en PortalDbService.get_client_by_id: {e}")
        return None

    @classmethod
    def get_client_invoices(cls, owner_uid, client_id, sandbox=True):
        invoices = []
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            docs = db_firestore.collection('users').document(owner_uid).collection(coll_name)\
                .where(filter=firestore.FieldFilter('clientId', '==', client_id)).get()
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                
                # Evaluar vencimiento de facturas
                status = data.get("status", "Borrador")
                due_date_str = data.get("dueDate")
                if status in ["Emitida", "Parcialmente Cobrada"] and due_date_str:
                    due_date_clean = due_date_str[:10]
                    today_str = datetime.utcnow().strftime("%Y-%m-%d")
                    if due_date_clean < today_str:
                        status = "Vencida"
                data['status'] = status
                
                # Normalizar montos
                data['netPayable'] = float(data.get('netPayable', data.get('total', 0.0)))
                data['remainingBalance'] = float(data.get('remainingBalance', 0.0 if status == 'Cobrada' else data['netPayable']))
                data['total'] = float(data.get('total', data['netPayable']))
                
                invoices.append(data)
            # Ordenar por fecha de emisión descendente
            invoices.sort(key=lambda x: x.get('date', ''), reverse=True)
        except Exception as e:
            print(f"Error en PortalDbService.get_client_invoices: {e}")
        return invoices

    @classmethod
    def get_invoice(cls, owner_uid, invoice_id, sandbox=True):
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            doc = db_firestore.collection('users').document(owner_uid).collection(coll_name).document(invoice_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                data['netPayable'] = float(data.get('netPayable', data.get('total', 0.0)))
                status = data.get('status', 'Borrador')
                data['remainingBalance'] = float(data.get('remainingBalance', 0.0 if status == 'Cobrada' else data['netPayable']))
                data['total'] = float(data.get('total', data['netPayable']))
                return data
        except Exception as e:
            print(f"Error en PortalDbService.get_invoice: {e}")
        return None

    @classmethod
    def save_invoice(cls, owner_uid, invoice_id, inv_dict, sandbox=True):
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            db_firestore.collection('users').document(owner_uid).collection(coll_name).document(invoice_id).set(inv_dict)
            return True
        except Exception as e:
            print(f"Error en PortalDbService.save_invoice: {e}")
        return False

@portal_bp.route('/portal/cliente/<client_id>')
def client_portal_legacy(client_id):
    # Por defecto buscar en el ownerUID demo si no se especifica
    # (Retrocompatibilidad para links rápidos con client_id de un único dueño)
    owner_uid = "W2n2BfR1G4eN3K7m7n8b9v0c1x2z" # ownerUID por defecto
    return redirect(url_for('portal.client_portal', owner_uid=owner_uid, client_id=client_id))

@portal_bp.route('/portal/cliente/<owner_uid>/<client_id>')
def client_portal(owner_uid, client_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    
    company = DatabaseService.get_company_profile(owner_uid)
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return "Cliente no encontrado en este ambiente.", 404
        
    invoices = PortalDbService.get_client_invoices(owner_uid, client_id, sandbox=sandbox)
    
    # Calcular saldos consolidados
    total_invoiced = 0.0
    total_cxc = 0.0
    
    for inv in invoices:
        if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']:
            total_invoiced += float(inv.get('total', 0.0))
            if inv.get('status') in ['Emitida', 'Vencida', 'Parcialmente Cobrada']:
                total_cxc += float(inv.get('remainingBalance', inv.get('netPayable', 0.0)))
                
    return render_template(
        'portal/portal.html',
        company=company,
        client=client,
        invoices=invoices,
        total_invoiced=total_invoiced,
        total_cxc=total_cxc,
        owner_uid=owner_uid,
        sandbox=sandbox
    )

@portal_bp.route('/portal/cliente/<owner_uid>/<client_id>/cotizacion/<invoice_id>/firmar', methods=['POST'])
def sign_quotation(owner_uid, client_id, invoice_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    signature_data = request.json.get('signature')
    
    if not signature_data:
        return jsonify({"success": False, "error": "No se recibió el trazo de la firma."}), 400
        
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        return jsonify({"success": False, "error": "Cotización no encontrada."}), 404
        
    invoice['status'] = 'Aprobada'
    invoice['signatureBase64'] = signature_data
    invoice['signedAt'] = datetime.utcnow().isoformat()
    
    PortalDbService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    return jsonify({"success": True, "message": "Propuesta firmada y aprobada exitosamente."})

@portal_bp.route('/portal/cliente/<owner_uid>/<client_id>/pago/<invoice_id>', methods=['POST'])
def pay_invoice(owner_uid, client_id, invoice_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    amount = float(request.json.get('amount', 0.0))
    
    if amount <= 0.0:
        return jsonify({"success": False, "error": "Monto de pago no válido."}), 400
        
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or invoice.get('isQuotation'):
        return jsonify({"success": False, "error": "Factura no encontrada."}), 404
        
    # Calcular nuevos balances
    net_payable = float(invoice.get('netPayable', 0.0))
    current_status = invoice.get('status')
    current_total_paid = float(invoice.get('totalPaid', net_payable if current_status == "Cobrada" else 0.0))
    
    new_total_paid = current_total_paid + amount
    new_remaining_balance = max(0.0, net_payable - new_total_paid)
    
    if new_remaining_balance <= 0.01:
        new_status = "Cobrada"
        new_remaining_balance = 0.0
    else:
        new_status = "Parcialmente Cobrada"
        
    # Registrar el abono en la subcolección de pagos
    payment_id = str(uuid.uuid4())
    payment_dict = {
        "id": payment_id,
        "amount": amount,
        "paymentMethod": "Tarjeta en Línea (Portal)",
        "bank": "Pasarela e-Factura",
        "referenceNumber": f"WEB-{uuid.uuid4().hex[:8].upper()}",
        "paymentDate": datetime.utcnow().isoformat(),
        "registeredBy": "Cliente (Portal Autogestión)"
    }
    
    coll_inv = "sandbox_invoices" if sandbox else "invoices"
    db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).collection("payments").document(payment_id).set(payment_dict)
    
    # Actualizar la factura principal
    invoice['status'] = new_status
    invoice['totalPaid'] = new_total_paid
    invoice['remainingBalance'] = new_remaining_balance
    invoice['paymentMethod'] = "Tarjeta en Línea (Portal)"
    invoice['paymentDate'] = payment_dict['paymentDate']
    
    PortalDbService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    return jsonify({"success": True, "message": "Pago simulado y procesado correctamente."})
