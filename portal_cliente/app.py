# portal_cliente/app.py
import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from database_service import DatabaseService

app = Flask(__name__)
app.secret_key = 'portal-cliente-secret-key'

@app.route('/')
def index():
    return "Portal de Clientes de e-Factura. Use un enlace de estado de cuenta enviado por su proveedor."

@app.route('/portal/cliente/<client_id>')
def client_portal_legacy(client_id):
    # Por defecto buscar en el ownerUID demo si no se especifica
    # (Retrocompatibilidad para links rápidos con client_id de un único dueño)
    owner_uid = "W2n2BfR1G4eN3K7m7n8b9v0c1x2z" # ownerUID por defecto
    return redirect(url_for('client_portal', owner_uid=owner_uid, client_id=client_id))

@app.route('/portal/cliente/<owner_uid>/<client_id>')
def client_portal(owner_uid, client_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    
    company = DatabaseService.get_company_profile(owner_uid)
    client = DatabaseService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return "Cliente no encontrado en este ambiente.", 404
        
    invoices = DatabaseService.get_client_invoices(owner_uid, client_id, sandbox=sandbox)
    
    # Calcular saldos consolidados
    total_invoiced = 0.0
    total_cxc = 0.0
    
    for inv in invoices:
        if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']:
            total_invoiced += float(inv.get('total', 0.0))
            if inv.get('status') in ['Emitida', 'Vencida', 'Parcialmente Cobrada']:
                total_cxc += float(inv.get('remainingBalance', inv.get('netPayable', 0.0)))
                
    return render_template(
        'portal.html',
        company=company,
        client=client,
        invoices=invoices,
        total_invoiced=total_invoiced,
        total_cxc=total_cxc,
        owner_uid=owner_uid,
        sandbox=sandbox
    )

@app.route('/portal/cliente/<owner_uid>/<client_id>/cotizacion/<invoice_id>/firmar', methods=['POST'])
def sign_quotation(owner_uid, client_id, invoice_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    signature_data = request.json.get('signature')
    
    if not signature_data:
        return jsonify({"success": False, "error": "No se recibió el trazo de la firma."}), 400
        
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        return jsonify({"success": False, "error": "Cotización no encontrada."}), 404
        
    invoice['status'] = 'Aprobada'
    invoice['signatureBase64'] = signature_data
    invoice['signedAt'] = datetime.utcnow().isoformat()
    
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    return jsonify({"success": True, "message": "Propuesta firmada y aprobada exitosamente."})

@app.route('/portal/cliente/<owner_uid>/<client_id>/pago/<invoice_id>', methods=['POST'])
def pay_invoice(owner_uid, client_id, invoice_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    amount = float(request.json.get('amount', 0.0))
    
    if amount <= 0.0:
        return jsonify({"success": False, "error": "Monto de pago no válido."}), 400
        
    invoice = DatabaseService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
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
    db = DatabaseService.get_db()
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
    db.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).collection("payments").document(payment_id).set(payment_dict)
    
    # Actualizar la factura principal
    invoice['status'] = new_status
    invoice['totalPaid'] = new_total_paid
    invoice['remainingBalance'] = new_remaining_balance
    invoice['paymentMethod'] = "Tarjeta en Línea (Portal)"
    invoice['paymentDate'] = payment_dict['paymentDate']
    
    DatabaseService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    return jsonify({"success": True, "message": "Pago simulado y procesado correctamente."})

if __name__ == '__main__':
    # Correr en puerto 5002 para coexistir con el app principal (5001)
    app.run(debug=True, port=5002)
