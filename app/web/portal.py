import uuid
import html
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, make_response, g
from firebase_admin import firestore
from app.services.db_service import db_firestore, DatabaseService
from app.services.azul_service import AzulService
from cryptography.hazmat.primitives.serialization import pkcs12
from app.brand import get_product_name
from app.utils.decorators import check_permission
from app.utils.module_gate import module_enabled

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
    def get_client_contracts(cls, owner_uid, client_id, sandbox=True):
        contracts = []
        try:
            coll_name = "sandbox_contracts" if sandbox else "contracts"
            docs = db_firestore.collection('users').document(owner_uid).collection(coll_name)\
                .where(filter=firestore.FieldFilter('clientId', '==', client_id)).get()
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                data['amount'] = float(data.get('amount', 0.0))
                contracts.append(data)
            contracts.sort(key=lambda x: x.get('contractNumber', ''))
        except Exception as e:
            print(f"Error en PortalDbService.get_client_contracts: {e}")
        return contracts

    @classmethod
    def get_contract(cls, owner_uid, contract_id, sandbox=True):
        try:
            coll_name = "sandbox_contracts" if sandbox else "contracts"
            doc = db_firestore.collection('users').document(owner_uid).collection(coll_name).document(contract_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                data['amount'] = float(data.get('amount', 0.0))
                return data
        except Exception as e:
            print(f"Error en PortalDbService.get_contract: {e}")
        return None

    @classmethod
    def save_contract(cls, owner_uid, contract_id, contract_dict, sandbox=True):
        try:
            coll_name = "sandbox_contracts" if sandbox else "contracts"
            db_firestore.collection('users').document(owner_uid).collection(coll_name).document(contract_id).set(contract_dict)
            return True
        except Exception as e:
            print(f"Error en PortalDbService.save_contract: {e}")
        return False

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
                
                # Excluir documentos en estado Borrador (tanto facturas como cotizaciones en Borrador se ocultan)
                if status == 'Borrador':
                    continue
                
                due_date_str = data.get("dueDate")
                if status in ["Emitida", "Parcialmente Cobrada"] and due_date_str:
                    due_date_clean = due_date_str[:10]
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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

@portal_bp.route('/portal/p/<token>')
def portal_entry(token):
    from app.utils.security import decode_portal_token
    data = decode_portal_token(token)
    if not data:
        return "El enlace es inválido, ha expirado o ha sido modificado.", 403
    
    session['portal_owner_uid'] = data['owner_uid']
    session['portal_client_id'] = data['client_id']
    session['portal_sandbox'] = data['sandbox']
    
    return redirect(url_for('portal.client_portal_main'))

@portal_bp.route('/portal')
def client_portal_main():
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    
    if not owner_uid or not client_id:
        return "Sesión de autogestión no válida o expirada. Por favor use el enlace oficial enviado a su correo.", 403
        
    company = DatabaseService.get_company_profile(owner_uid)
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return "Cliente no encontrado.", 404
        
    # Verificar identidad mediante RNC/Cédula y PIN
    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return render_template(
            'portal/verify.html',
            company=company,
            owner_uid=owner_uid,
            client_id=client_id,
            sandbox=sandbox
        )
        
    invoices = PortalDbService.get_client_invoices(owner_uid, client_id, sandbox=sandbox)
    contracts = PortalDbService.get_client_contracts(owner_uid, client_id, sandbox=sandbox)
    
    # Calcular saldos consolidados
    total_invoiced = 0.0
    total_cxc = 0.0
    
    for inv in invoices:
        if not inv.get('isQuotation') and inv.get('status') not in ['Anulada', 'Borrador']:
            total_invoiced += float(inv.get('total', 0.0))
            if inv.get('status') in ['Emitida', 'Vencida', 'Parcialmente Cobrada', 'Revisión de Pago']:
                total_cxc += float(inv.get('remainingBalance', inv.get('netPayable', 0.0)))
                
    return render_template(
        'portal/portal.html',
        company=company,
        client=client,
        invoices=invoices,
        contracts=contracts,
        total_invoiced=total_invoiced,
        total_cxc=total_cxc,
        owner_uid=owner_uid,
        sandbox=sandbox
    )

@portal_bp.route('/portal/verify', methods=['POST'])
def client_portal_verify_main():
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    
    if not owner_uid or not client_id:
        return "Sesión de autogestión no válida o expirada.", 403
        
    input_rnc = request.form.get('rnc', '').strip()
    input_pin = request.form.get('accessPin', '').strip()
    
    company = DatabaseService.get_company_profile(owner_uid)
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return "Cliente no encontrado.", 404
        
    db_pin = client.get('accessPin', '')
    if not db_pin:
        import random
        db_pin = "".join([str(random.randint(0, 9)) for _ in range(6)])
        client['accessPin'] = db_pin
        DatabaseService.save_client(owner_uid, client_id, client, sandbox=sandbox)
        
    if clean_rnc(input_rnc) == clean_rnc(client.get('rnc', '')) and input_pin == db_pin:
        session[f'verified_client_{client_id}'] = True
        return redirect(url_for('portal.client_portal_main'))
    else:
        error = "El RNC/Cédula o el Código de Acceso ingresado es incorrecto. Por favor, intente de nuevo."
        return render_template(
            'portal/verify.html',
            company=company,
            owner_uid=owner_uid,
            client_id=client_id,
            sandbox=sandbox,
            error=error
        )

@portal_bp.route('/portal/cliente/<client_id>')
def client_portal_legacy(client_id):
    owner_uid = "W2n2BfR1G4eN3K7m7n8b9v0c1x2z" # ownerUID por defecto
    return redirect(url_for('portal.client_portal', owner_uid=owner_uid, client_id=client_id))

def clean_rnc(rnc_str):
    if not rnc_str:
        return ""
    return "".join(c for c in rnc_str if c.isalnum()).lower()

@portal_bp.route('/portal/cliente/<owner_uid>/<client_id>')
def client_portal(owner_uid, client_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    session['portal_owner_uid'] = owner_uid
    session['portal_client_id'] = client_id
    session['portal_sandbox'] = sandbox
    return redirect(url_for('portal.client_portal_main'))

@portal_bp.route('/portal/cliente/<owner_uid>/<client_id>/verify', methods=['POST'])
def client_portal_verify(owner_uid, client_id):
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    session['portal_owner_uid'] = owner_uid
    session['portal_client_id'] = client_id
    session['portal_sandbox'] = sandbox
    return redirect(url_for('portal.client_portal_verify_main'), code=307)


def validate_certificate_signature(cert_file, password, client_rnc):
    try:
        cert_data = cert_file.read()
        if not cert_data:
            return False, "El archivo de certificado está vacío."
        
        # Cargar llave privada y certificado
        private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
            cert_data, password.encode()
        )
        
        if not certificate:
            return False, "No se encontró un certificado válido en el archivo."
        
        # Limpiar RNC del cliente
        client_rnc_clean = "".join(c for c in client_rnc if c.isalnum()).lower()
        found_match = False
        
        # 1. Buscar en el subject del certificado
        for attribute in certificate.subject:
            val = "".join(c for c in str(attribute.value) if c.isalnum()).lower()
            if client_rnc_clean in val:
                found_match = True
                break
                
        # 2. Buscar en Subject Alternative Name (SAN)
        if not found_match:
            try:
                from cryptography.x509.oid import ExtensionOID
                san_ext = certificate.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                for name in san_ext.value:
                    val = "".join(c for c in str(name.value) if c.isalnum()).lower()
                    if client_rnc_clean in val:
                        found_match = True
                        break
            except Exception:
                pass
                
        if not found_match:
            return False, f"El certificado digital no corresponde al RNC/Cédula ({client_rnc}) registrado para este cliente."
            
        # Extraer información del certificado para los metadatos
        subject_name = ""
        issuer_name = ""
        for attr in certificate.subject:
            if attr.oid._name == "commonName":
                subject_name = attr.value
                break
        for attr in certificate.issuer:
            if attr.oid._name == "commonName":
                issuer_name = attr.value
                break
        if not subject_name:
            subject_name = str(certificate.subject)
        if not issuer_name:
            issuer_name = str(certificate.issuer)
            
        try:
            not_before = certificate.not_valid_before_utc.isoformat()
            not_after = certificate.not_valid_after_utc.isoformat()
        except AttributeError:
            not_before = certificate.not_valid_before.isoformat()
            not_after = certificate.not_valid_after.isoformat()
            
        cert_info = {
            "subject": subject_name,
            "issuer": issuer_name,
            "serialNumber": str(certificate.serial_number),
            "notBefore": not_before,
            "notAfter": not_after,
            "signedAt": datetime.now(timezone.utc).isoformat()
        }
        return True, cert_info
        
    except ValueError:
        return False, "La contraseña del certificado es incorrecta o el archivo no es un certificado PKCS#12 (.p12/.pfx) válido."
    except Exception as e:
        return False, f"Error al procesar el certificado digital: {html.escape(str(e))}"

@portal_bp.route('/portal/cotizacion/<invoice_id>/firmar', methods=['POST'])
def sign_quotation(invoice_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403
    
    # Validar sesión de cliente
    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return jsonify({"success": False, "error": "Acceso no autorizado. Verifique su RNC primero."}), 403
        
    cert_file = request.files.get('certificate')
    password = request.form.get('password', '')
    
    if not cert_file:
        return jsonify({"success": False, "error": "No se recibió el archivo del certificado digital."}), 400
        
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
        
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        return jsonify({"success": False, "error": "Cotización no encontrada."}), 404
        
    if invoice.get('status') == 'Aprobada':
        return jsonify({"success": False, "error": "La cotización ya fue firmada y aprobada anteriormente."}), 400
        
    if invoice.get('status') != 'Pendiente Aut. Cliente':
        return jsonify({"success": False, "error": "La cotización no se encuentra en estado pendiente de autorización por el cliente."}), 400
        
    success, result = validate_certificate_signature(cert_file, password, client.get('rnc', ''))
    if not success:
        return jsonify({"success": False, "error": result}), 400
        
    # Guardar metadatos de la firma
    before_invoice = invoice.copy()
    invoice['status'] = 'Aprobada'
    invoice['signatureInfo'] = result
    invoice['signedAt'] = result['signedAt']
    
    PortalDbService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

    # Registrar evento de auditoría
    try:
        from app.services.audit_service import AuditService, MODULE_COTIZACIONES
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ua = request.headers.get("User-Agent", "")
        AuditService.log(
            owner_uid=owner_uid,
            action="SIGN",
            module=MODULE_COTIZACIONES,
            entity_id=invoice_id,
            entity_label=f"Cotización {invoice.get('invoiceNumber')} aprobada por firma del cliente",
            performed_by_name=f"Cliente: {client.get('name')}",
            performed_by_uid=client_id,
            performed_by_email=client.get('email', ''),
            before=before_invoice,
            after=invoice,
            sandbox=sandbox,
            ip_address=ip,
            user_agent=ua
        )
    except Exception as ae:
        print(f"⚠️ Error al registrar auditoría de firma: {ae}")

    # --- Notificar al responsable ---
    _notify_portal_action(
        owner_uid=owner_uid,
        action='firmada',
        document_type='Cotización',
        document_number=invoice.get('invoiceNumber', invoice_id),
        client=client,
        signed_at=result['signedAt'],
        invoice_or_contract=invoice,
        invoice_id=invoice_id,
        sandbox=sandbox
    )

    return jsonify({"success": True, "message": "Propuesta firmada y aprobada digitalmente de forma exitosa."})

@portal_bp.route('/portal/contrato/<contract_id>/firmar', methods=['POST'])
def sign_contract(contract_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403
    
    # Validar sesión de cliente
    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return jsonify({"success": False, "error": "Acceso no autorizado. Verifique su RNC primero."}), 403
        
    cert_file = request.files.get('certificate')
    password = request.form.get('password', '')
    
    if not cert_file:
        return jsonify({"success": False, "error": "No se recibió el archivo del certificado digital."}), 400
        
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
        
    contract = PortalDbService.get_contract(owner_uid, contract_id, sandbox=sandbox)
    if not contract:
        return jsonify({"success": False, "error": "Contrato no encontrado."}), 404
        
    success, result = validate_certificate_signature(cert_file, password, client.get('rnc', ''))
    if not success:
        return jsonify({"success": False, "error": result}), 400
        
    # Guardar metadatos de la firma
    before_contract = contract.copy()
    contract['status'] = 'Activo'
    contract['signatureInfo'] = result
    contract['signedAt'] = result['signedAt']
    
    PortalDbService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)

    # Registrar evento de auditoría
    try:
        from app.services.audit_service import AuditService, MODULE_CONTRATOS
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ua = request.headers.get("User-Agent", "")
        AuditService.log(
            owner_uid=owner_uid,
            action="SIGN",
            module=MODULE_CONTRATOS,
            entity_id=contract_id,
            entity_label=f"Contrato {contract.get('contractNumber')} firmado por el cliente",
            performed_by_name=f"Cliente: {client.get('name')}",
            performed_by_uid=client_id,
            performed_by_email=client.get('email', ''),
            before=before_contract,
            after=contract,
            sandbox=sandbox,
            ip_address=ip,
            user_agent=ua
        )
    except Exception as ae:
        print(f"⚠️ Error al registrar auditoría de firma de contrato: {ae}")

    # --- Notificar al responsable ---
    _notify_portal_action(
        owner_uid=owner_uid,
        action='firmada',
        document_type='Contrato',
        document_number=contract.get('contractNumber', contract_id),
        client=client,
        signed_at=result['signedAt'],
        invoice_or_contract=contract,
        invoice_id=None,
        sandbox=sandbox
    )

    return jsonify({"success": True, "message": "Contrato firmado y activado digitalmente de forma exitosa."})

@portal_bp.route('/portal/cotizacion/<invoice_id>/rechazar', methods=['POST'])
def reject_quotation(invoice_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403

    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return jsonify({"success": False, "error": "Acceso no autorizado."}), 403

    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404

    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or not invoice.get('isQuotation'):
        return jsonify({"success": False, "error": "Cotización no encontrada."}), 404
        
    if invoice.get('status') == 'Aprobada':
        return jsonify({"success": False, "error": "No se puede rechazar una cotización que ya fue aprobada."}), 400
        
    if invoice.get('status') != 'Pendiente Aut. Cliente':
        return jsonify({"success": False, "error": "La cotización no se encuentra en estado pendiente de autorización."}), 400

    before_invoice = invoice.copy()
    rejected_at = datetime.now(timezone.utc).isoformat()
    invoice['status'] = 'Rechazada'
    invoice['rejectedAt'] = rejected_at
    invoice['rejectedBy'] = client.get('name', client.get('rnc', 'Cliente'))
    PortalDbService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

    # Registrar evento de auditoría
    try:
        from app.services.audit_service import AuditService, MODULE_COTIZACIONES
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ua = request.headers.get("User-Agent", "")
        AuditService.log(
            owner_uid=owner_uid,
            action="REJECT",
            module=MODULE_COTIZACIONES,
            entity_id=invoice_id,
            entity_label=f"Cotización {invoice.get('invoiceNumber')} rechazada por el cliente",
            performed_by_name=f"Cliente: {client.get('name')}",
            performed_by_uid=client_id,
            performed_by_email=client.get('email', ''),
            before=before_invoice,
            after=invoice,
            sandbox=sandbox,
            ip_address=ip,
            user_agent=ua
        )
    except Exception as ae:
        print(f"⚠️ Error al registrar auditoría de rechazo: {ae}")

    _notify_portal_action(
        owner_uid=owner_uid,
        action='rechazada',
        document_type='Cotización',
        document_number=invoice.get('invoiceNumber', invoice_id),
        client=client,
        signed_at=rejected_at,
        invoice_or_contract=invoice,
        invoice_id=invoice_id,
        sandbox=sandbox
    )

    return jsonify({"success": True, "message": "Cotización rechazada. Hemos notificado al equipo responsable."})


@portal_bp.route('/portal/contrato/<contract_id>/rechazar', methods=['POST'])
def reject_contract(contract_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403

    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return jsonify({"success": False, "error": "Acceso no autorizado."}), 403

    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404

    contract = PortalDbService.get_contract(owner_uid, contract_id, sandbox=sandbox)
    if not contract:
        return jsonify({"success": False, "error": "Contrato no encontrado."}), 404

    rejected_at = datetime.now(timezone.utc).isoformat()
    contract['status'] = 'Rechazado'
    contract['rejectedAt'] = rejected_at
    contract['rejectedBy'] = client.get('name', client.get('rnc', 'Cliente'))
    PortalDbService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)

    _notify_portal_action(
        owner_uid=owner_uid,
        action='rechazada',
        document_type='Contrato',
        document_number=contract.get('contractNumber', contract_id),
        client=client,
        signed_at=rejected_at,
        invoice_or_contract=contract,
        invoice_id=None,
        sandbox=sandbox
    )

    return jsonify({"success": True, "message": "Contrato rechazado. Hemos notificado al equipo responsable."})


def _notify_portal_action(owner_uid, action, document_type, document_number, client, signed_at, invoice_or_contract, invoice_id, sandbox):
    """Helper interno: resuelve el responsable del cliente y envía email + notificación in-app."""
    try:
        from app.services.notifications import NotificationService
        from app.services.db_service import DatabaseService
        from flask import request as flask_request
        import uuid as _uuid

        # 1. Resolver el responsable de la cuenta del cliente (responsibleId)
        responsible_uid = None
        responsible_email = None
        responsible_name = None

        responsible_id = client.get('responsibleId')
        if responsible_id:
            try:
                team_members = DatabaseService.get_team_members(owner_uid)
                for member in team_members:
                    if member.get('uid') == responsible_id or member.get('id') == responsible_id:
                        responsible_uid = member.get('uid') or member.get('id')
                        responsible_email = member.get('email')
                        responsible_name = member.get('name') or member.get('email')
                        break
            except Exception as ex:
                print(f"⚠️ [Portal Notification] Error al buscar responsable en equipo: {ex}")

        # 2. Si no hay responsable asignado, caer al owner
        if not responsible_email or '@' not in str(responsible_email):
            try:
                from app.services.db_service import db_firestore
                doc = db_firestore.collection('users').document(owner_uid).collection('config').document('user_profile').get()
                if doc.exists:
                    owner_profile = doc.to_dict()
                    responsible_email = owner_profile.get('email', '')
                    responsible_name = owner_profile.get('name') or responsible_email
                    responsible_uid = owner_uid
            except Exception:
                pass

        if not responsible_email:
            print(f"⚠️ [Portal Notification] No se encontró email del responsable para notificar.")
            return

        # 3. Construir URL del documento en el sistema
        document_url = ""
        if invoice_id and document_type == 'Cotización':
            try:
                base_url = flask_request.host_url.rstrip('/')
                document_url = f"{base_url}/invoices/{invoice_id}"
            except Exception:
                pass

        # 4. Enviar notificación por email al responsable
        NotificationService.send_portal_action_notification(
            owner_uid=owner_uid,
            action=action,
            document_type=document_type,
            document_number=document_number,
            client_name=client.get('name', 'Cliente'),
            client_rnc=client.get('rnc', ''),
            signed_at=signed_at,
            recipient_email=responsible_email,
            document_url=document_url,
            sandbox=sandbox
        )

        # 5. Guardar notificación in-app al responsable
        if responsible_uid:
            try:
                client_name = client.get('name', 'Cliente')
                if action == 'firmada':
                    notif_icon = '✅'
                    notif_title = f"{document_type} aprobada por cliente"
                    notif_body = f"{client_name} autorizó {document_type.lower()} {document_number}."
                    notif_type = 'portal_firma'
                elif action == 'rechazada':
                    notif_icon = '❌'
                    notif_title = f"{document_type} rechazada por cliente"
                    notif_body = f"{client_name} rechazó {document_type.lower()} {document_number}."
                    notif_type = 'portal_rechazo'
                elif action == 'cancelada':
                    notif_icon = '🚫'
                    notif_title = f"Solicitud de cancelación de {document_type}"
                    notif_body = f"{client_name} solicitó la cancelación de {document_type.lower()} {document_number}. El servicio seguirá activo hasta el vencimiento del período pagado."
                    notif_type = 'portal_cancelacion'
                else:
                    notif_icon = '💰'
                    notif_title = "Pago reportado por cliente"
                    notif_body = f"{client_name} cargó un comprobante de pago para {document_number}."
                    notif_type = 'portal_pago'

                DatabaseService.create_user_notification(responsible_uid, {
                    "id": str(_uuid.uuid4()),
                    "type": notif_type,
                    "icon": notif_icon,
                    "title": notif_title,
                    "body": notif_body,
                    "documentType": document_type,
                    "documentNumber": document_number,
                    "clientName": client_name,
                    "documentUrl": document_url,
                    "createdAt": signed_at,
                    "read": False
                })
            except Exception as ex:
                print(f"⚠️ [Portal Notification] Error al guardar notificación in-app: {ex}")

    except Exception as e:
        print(f"⚠️ [Portal Notification] Error al notificar: {e}")


@portal_bp.route('/portal/contrato/<contract_id>/cancelar', methods=['POST'])
def cancel_contract(contract_id):
    """
    Permite al cliente cancelar (no renovar) un contrato activo usando firma electrónica.
    El servicio sigue activo hasta que el periodo pagado expire. Solo se deja de renovar.
    """
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403

    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return jsonify({"success": False, "error": "Acceso no autorizado. Verifique su identidad primero."}), 403

    cert_file = request.files.get('certificate')
    password = request.form.get('password', '')

    if not cert_file:
        return jsonify({"success": False, "error": "No se recibió el archivo del certificado digital."}), 400

    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404

    contract = PortalDbService.get_contract(owner_uid, contract_id, sandbox=sandbox)
    if not contract:
        return jsonify({"success": False, "error": "Contrato no encontrado."}), 404

    if contract.get('status') not in ['Activo']:
        return jsonify({"success": False, "error": "Solo se pueden cancelar contratos activos."}), 400

    success, result = validate_certificate_signature(cert_file, password, client.get('rnc', ''))
    if not success:
        return jsonify({"success": False, "error": result}), 400

    cancelled_at = result.get('signedAt', datetime.now(timezone.utc).isoformat())

    # Marcar como "No Renovar" — el servicio sigue activo hasta el próximo vencimiento
    contract['cancelRequest'] = True
    contract['cancelRequestAt'] = cancelled_at
    contract['cancelRequestBy'] = client.get('razonSocial', client.get('rnc', 'Cliente'))
    contract['cancelSignatureInfo'] = result
    # No tocamos contract['status'] = 'Activo' — el servicio continúa
    # El scheduler de recurrencia debe chequear cancelRequest=True para NO generar la siguiente factura

    PortalDbService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)

    _notify_portal_action(
        owner_uid=owner_uid,
        action='cancelada',
        document_type='Contrato',
        document_number=contract.get('contractNumber', contract_id),
        client=client,
        signed_at=cancelled_at,
        invoice_or_contract=contract,
        invoice_id=None,
        sandbox=sandbox
    )

    return jsonify({
        "success": True,
        "message": "Solicitud de cancelación registrada. Su servicio continuará activo hasta el final del período vigente y no será renovado automáticamente."
    })

@portal_bp.route('/portal/pago/<invoice_id>', methods=['POST'])
def pay_invoice(invoice_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403

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
        "bank": f"Pasarela {get_product_name()}",
        "referenceNumber": f"WEB-{uuid.uuid4().hex[:8].upper()}",
        "paymentDate": datetime.now(timezone.utc).isoformat(),
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

@portal_bp.route('/portal/pago/<invoice_id>/reportar', methods=['POST'])
def report_invoice_payment(invoice_id):
    import os
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    if not owner_uid or not client_id:
        return jsonify({"success": False, "error": "Sesión no válida o expirada."}), 403
    
    # Validar sesión de cliente
    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return jsonify({"success": False, "error": "Acceso no autorizado. Verifique su RNC primero."}), 403
        
    # Validar campos del formulario
    try:
        amount = float(request.form.get('amount', 0.0))
    except ValueError:
        return jsonify({"success": False, "error": "Monto de pago no válido."}), 400
        
    if amount <= 0.0:
        return jsonify({"success": False, "error": "El monto debe ser mayor a cero."}), 400
        
    payment_method = request.form.get('paymentMethod', '').strip()
    bank = request.form.get('bank', '').strip()
    reference_number = request.form.get('referenceNumber', '').strip()
    payment_date = request.form.get('paymentDate', '').strip()
    notes = request.form.get('notes', '').strip()
    
    if not payment_method or not bank or not reference_number or not payment_date:
        return jsonify({"success": False, "error": "Todos los campos de confirmación de pago son requeridos."}), 400
        
    # Obtener el archivo del comprobante
    proof_file = request.files.get('paymentProofFile')
    if not proof_file or not proof_file.filename:
        return jsonify({"success": False, "error": "Debe adjuntar el archivo del comprobante de pago."}), 400
        
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado."}), 404
        
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or invoice.get('isQuotation'):
        return jsonify({"success": False, "error": "Factura no encontrada."}), 404
        
    # Validar que el monto no exceda el balance pendiente
    remaining_balance = float(invoice.get('remainingBalance', invoice.get('netPayable', 0.0)))
    if amount > remaining_balance + 0.01:
        return jsonify({"success": False, "error": f"El monto reportado (RD$ {amount:,.2f}) no puede ser mayor que el balance pendiente (RD$ {remaining_balance:,.2f})."}), 400
        
    try:
        # Subir archivo a storage
        file_data = proof_file.read()
        mime_type = proof_file.mimetype or "application/octet-stream"
        ext = os.path.splitext(proof_file.filename)[1] or ".pdf"
        filename = f"proof_{invoice_id}_{uuid.uuid4().hex[:8]}{ext}"
        destination_path = f"users/{owner_uid}/payment_proofs/{filename}"
        
        file_url = DatabaseService.upload_file_to_storage(
            file_data=file_data,
            destination_path=destination_path,
            mime_type=mime_type
        )
        
        # Guardar en la factura los detalles del comprobante pendiente
        before_invoice = invoice.copy()
        invoice['status'] = 'Revisión de Pago'
        invoice['pendingPaymentProof'] = {
            "amount": amount,
            "paymentMethod": payment_method,
            "bank": bank,
            "referenceNumber": reference_number,
            "paymentDate": payment_date,
            "fileUrl": file_url,
            "fileName": proof_file.filename,
            "notes": notes,
            "uploadedAt": datetime.now(timezone.utc).isoformat()
        }
        
        PortalDbService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)

        # Registrar evento de auditoría
        try:
            from app.services.audit_service import AuditService, MODULE_FACTURAS
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
            ua = request.headers.get("User-Agent", "")
            AuditService.log(
                owner_uid=owner_uid,
                action="REPORT_PAYMENT",
                module=MODULE_FACTURAS,
                entity_id=invoice_id,
                entity_label=f"Pago reportado por cliente: RD$ {amount:,.2f} ({payment_method} - {bank})",
                performed_by_name=f"Cliente: {client.get('name')}",
                performed_by_uid=client_id,
                performed_by_email=client.get('email', ''),
                before=before_invoice,
                after=invoice,
                sandbox=sandbox,
                ip_address=ip,
                user_agent=ua
            )
        except Exception as ae:
            print(f"⚠️ Error al registrar auditoría de pago reportado: {ae}")
        
        # Notificar al responsable (email + in-app) usando _notify_portal_action
        try:
            _notify_portal_action(
                owner_uid=owner_uid,
                action='pago_reportado',
                document_type='Factura',
                document_number=invoice.get('invoiceNumber', invoice_id),
                client=client,
                signed_at=invoice['pendingPaymentProof']['uploadedAt'],
                invoice_or_contract=invoice,
                invoice_id=invoice_id,
                sandbox=sandbox
            )
        except Exception as e:
            print(f"⚠️ Error al notificar pago reportado: {e}")
            
        return jsonify({"success": True, "message": "El comprobante de pago ha sido cargado correctamente y está en proceso de revisión."})
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al procesar el comprobante: {str(e)}"}), 500

@portal_bp.route('/portal/pago/<invoice_id>/azul', methods=['GET', 'POST'])
def pay_invoice_azul(invoice_id):
    return "El pago con tarjeta de crédito/débito a través del simulador de Azul se encuentra inhabilitado temporalmente.", 403

@portal_bp.route('/portal/azul/callback', methods=['GET', 'POST'])
def azul_callback():
    client_id = request.args.get('client_id')
    sandbox = request.args.get('sandbox', 'true').lower() == 'true'
    
    response_data = request.values.to_dict()
    owner_uid = response_data.get('CustomField1')
    invoice_id = response_data.get('CustomField2')
    
    if not owner_uid or not invoice_id:
        return "Respuesta de pago incompleta.", 400
        
    company = DatabaseService.get_company_profile(owner_uid)
    result = AzulService.verify_payment_response(company, response_data)
    
    if result.get('success'):
        _process_azul_payment_record(result)
        flash("¡Tu pago a través de la pasarela Azul ha sido procesado con éxito!", "success")
        return render_template('portal/payment_success.html', result=result, company=company, client_id=client_id, sandbox=sandbox)
    else:
        flash(f"El pago no pudo ser procesado: {result.get('error') or 'Error desconocido'}", "error")
        return render_template('portal/payment_failed.html', result=result, company=company, client_id=client_id, sandbox=sandbox)

@portal_bp.route('/portal/azul/webhook', methods=['POST'])
def azul_webhook():
    response_data = request.form.to_dict()
    owner_uid = response_data.get('CustomField1')
    
    if not owner_uid:
        return jsonify({"success": False, "error": "owner_uid no provisto"}), 400
        
    company = DatabaseService.get_company_profile(owner_uid)
    result = AzulService.verify_payment_response(company, response_data)
    
    if result.get('success'):
        _process_azul_payment_record(result)
        return jsonify({"success": True, "message": "Webhook procesado correctamente."})
    else:
        return jsonify({"success": False, "error": result.get('error') or "Error de verificación"}), 400

def _process_azul_payment_record(result):
    owner_uid = result['owner_uid']
    invoice_id = result['invoice_id']
    sandbox = result['is_sandbox']
    amount = result['amount']
    payment_id = result['reference']
    
    coll_inv = "sandbox_invoices" if sandbox else "invoices"
    
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice:
        return False
        
    payment_doc = db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).collection("payments").document(payment_id).get()
    if payment_doc.exists:
        return True
        
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
        
    payment_dict = {
        "id": payment_id,
        "amount": amount,
        "paymentMethod": "Tarjeta en Línea (Azul)",
        "bank": "Pasarela Azul",
        "referenceNumber": payment_id,
        "paymentDate": datetime.now(timezone.utc).isoformat(),
        "registeredBy": "Cliente (Pasarela Azul)"
    }
    
    db_firestore.collection("users").document(owner_uid).collection(coll_inv).document(invoice_id).collection("payments").document(payment_id).set(payment_dict)
    
    invoice['status'] = new_status
    invoice['totalPaid'] = new_total_paid
    invoice['remainingBalance'] = new_remaining_balance
    invoice['paymentMethod'] = "Tarjeta en Línea (Azul)"
    invoice['paymentDate'] = payment_dict['paymentDate']
    
    PortalDbService.save_invoice(owner_uid, invoice_id, invoice, sandbox=sandbox)
    return True


@portal_bp.route('/portal/documento/<invoice_id>')
def portal_document_detail(invoice_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    
    if not owner_uid or not client_id:
        return "Sesión de autogestión no válida o expirada. Por favor use el enlace oficial enviado a su correo.", 403
        
    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return redirect(url_for('portal.client_portal_main'))
        
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or invoice.get('clientId') != client_id:
        return "Documento no encontrado o acceso denegado.", 404
        
    # Excluir cotizaciones en borrador
    if invoice.get('isQuotation') and invoice.get('status') == 'Borrador':
        return "Documento no disponible.", 404
        
    from app.web.invoices import _enrich_invoice_totals
    invoice = _enrich_invoice_totals(invoice)
    
    company = DatabaseService.get_company_profile(owner_uid)
    client = PortalDbService.get_client_by_id(owner_uid, client_id, sandbox=sandbox)
    
    # Obtener sucursal
    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
    if not branch and branches:
        branch = branches[0]
        
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
    return render_template(
        'portal/document_detail.html',
        company=company,
        client=client,
        invoice=invoice,
        branch=branch,
        today_str=today_str,
        owner_uid=owner_uid,
        sandbox=sandbox
    )


@portal_bp.route('/portal/documento/<invoice_id>/pdf')
def portal_document_pdf(invoice_id):
    owner_uid = session.get('portal_owner_uid')
    client_id = session.get('portal_client_id')
    sandbox = session.get('portal_sandbox', True)
    
    if not owner_uid or not client_id:
        return "Sesión de autogestión no válida o expirada.", 403
        
    session_key = f'verified_client_{client_id}'
    if session.get(session_key) != True:
        return "No verificado", 401
        
    invoice = PortalDbService.get_invoice(owner_uid, invoice_id, sandbox=sandbox)
    if not invoice or invoice.get('clientId') != client_id:
        return "Documento no encontrado o acceso denegado.", 404
        
    # Excluir cotizaciones en borrador
    if invoice.get('isQuotation') and invoice.get('status') == 'Borrador':
        return "Documento no disponible.", 404
        
    from app.web.invoices import _enrich_invoice_totals, WEASYPRINT_AVAILABLE
    try:
        if WEASYPRINT_AVAILABLE:
            from weasyprint import HTML as WeasyprintHTML
        else:
            WeasyprintHTML = None
    except ImportError:
        WeasyprintHTML = None
        
    invoice = _enrich_invoice_totals(invoice)
    company = DatabaseService.get_company_profile(owner_uid)
    
    import io
    import base64
    import qrcode
    import urllib.parse
    
    qr_url = invoice.get("qrCodeURL")
    fecha_firma_str = ""
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

    if not qr_url:
        qr_url = "https://dgii.gov.do/validaecf"

    qr = qrcode.QRCode(version=1, box_size=10, border=0)
    qr.add_data(qr_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    stream = io.BytesIO()
    img.save(stream, format="PNG")
    qr_base64 = base64.b64encode(stream.getvalue()).decode('utf-8')

    branches = DatabaseService.get_branches(owner_uid, sandbox=sandbox)
    branch = next((b for b in branches if b['id'] == invoice.get("branchId")), None)
    if not branch and branches:
        branch = branches[0]

    rendered_html = render_template(
        'invoices/pdf.html',
        invoice=invoice,
        company=company,
        branch=branch,
        auto_print=True,
        qr_base64=qr_base64,
        fecha_firma_str=fecha_firma_str,
        sandbox=sandbox
    )
    
    if WEASYPRINT_AVAILABLE and WeasyprintHTML:
        pdf_bytes = WeasyprintHTML(string=rendered_html, base_url=request.host_url).write_pdf()
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        inv_num = invoice.get('invoiceNumber', invoice_id).replace('/', '-').replace(' ', '_')
        response.headers['Content-Disposition'] = f'attachment; filename="{inv_num}.pdf"'
        return response
    else:
        return rendered_html


@portal_bp.route('/portal/admin')
def portal_admin():
    if 'user' not in session:
        flash('Debe iniciar sesión para acceder a esta página.', 'error')
        return redirect(url_for('web_auth.login'))
    if not check_permission('canClients'):
        return render_template('auth/restricted.html', feature_name='Portal de Clientes',
                               required_permission='canClients')

    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    company = DatabaseService.get_company_profile(owner_uid) or {}

    clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'))
    portal_clients = []
    for c in clients:
        if c.get('accessPin'):
            from app.utils.security import generate_portal_token
            token = generate_portal_token(owner_uid, c['id'], sandbox=sandbox)
            portal_url = url_for('portal.portal_entry', token=token, _external=True)
            portal_clients.append({
                'id': c['id'],
                'razonSocial': c.get('razonSocial', ''),
                'rnc': c.get('rnc', ''),
                'email': c.get('email', ''),
                'telefono': c.get('telefono', ''),
                'accessPin': c.get('accessPin', ''),
                'portalUrl': portal_url
            })
    portal_clients.sort(key=lambda x: x['razonSocial'].lower())

    return render_template('portal/admin.html', active_page='portal_admin',
                           clients=portal_clients, company=company, sandbox=sandbox)


