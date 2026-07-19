import base64
from flask import Blueprint, session, jsonify, request, flash, redirect, url_for
from app.services.db_service import DatabaseService
from app.services.ecf_readiness_service import EcfReadinessService
from app.utils.decorators import check_permission
from app.utils.security import encrypt_field

web_company_bp = Blueprint('web_company', __name__)


@web_company_bp.route('/company/ecf-status')
def ecf_status():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    owner_uid = session['user']['ownerUID']
    status = EcfReadinessService.get_status(owner_uid)
    return jsonify(status)


@web_company_bp.route('/company/certificate', methods=['POST'])
def upload_certificate():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canModifySettings'):
        return jsonify({"error": "Sin permisos"}), 403

    owner_uid = session['user']['ownerUID']
    existing = DatabaseService.get_company_profile(owner_uid)
    if not existing:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    cert_file = request.files.get('certificateFile')
    if not cert_file or not cert_file.filename:
        return jsonify({"error": "Debe seleccionar un archivo .p12 o .pfx"}), 400

    ext = cert_file.filename.rsplit('.', 1)[-1].lower() if '.' in cert_file.filename else 'p12'
    if ext not in ('p12', 'pfx'):
        return jsonify({"error": "El archivo debe ser .p12 o .pfx"}), 400

    file_data = cert_file.read()
    if not file_data:
        return jsonify({"error": "El archivo está vacío"}), 400

    cert_password = request.form.get('certificatePassword', '').strip()
    if not cert_password:
        return jsonify({"error": "La contraseña del certificado es obligatoria"}), 400

    cert_name = cert_file.filename.rsplit('.', 1)[0]
    cert_content_b64 = base64.b64encode(file_data).decode('utf-8')

    valid, detail = EcfReadinessService._validate_certificate(cert_content_b64, cert_password)
    if not valid:
        return jsonify({"error": detail.get("message", "El certificado no es válido")}), 400

    existing['certificateName'] = cert_name
    existing['certificateExtension'] = f".{ext}"
    existing['certificateContent'] = cert_content_b64
    existing['certificatePassword'] = cert_password

    saved = DatabaseService.save_company_profile(owner_uid, existing)
    if not saved:
        return jsonify({"error": "No se pudo guardar el certificado"}), 500

    return jsonify({"success": True})


@web_company_bp.route('/company/paypal-settings', methods=['POST'])
def save_paypal_settings():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canModifySettings'):
        return jsonify({"error": "Sin permisos"}), 403

    owner_uid = session['user']['ownerUID']
    existing = DatabaseService.get_company_profile(owner_uid)
    if not existing:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    paypal_client_id = request.form.get('paypalClientId', '').strip()
    paypal_secret_raw = request.form.get('paypalClientSecret', '').strip()
    paypal_currency = request.form.get('paypalCurrency', 'USD').strip()
    paypal_sandbox = request.form.get('paypalSandbox') == 'true'

    existing['paypalClientId'] = paypal_client_id
    if paypal_secret_raw:
        existing['paypalClientSecretEncrypted'] = encrypt_field(paypal_secret_raw)
    existing['paypalCurrency'] = paypal_currency
    existing['paypalSandbox'] = paypal_sandbox
    existing['paypalBankAccountId'] = request.form.get('paypalBankAccountId', '').strip()
    existing['paypalAccountingAccountId'] = request.form.get('paypalAccountingAccountId', '').strip()
    existing['paypalWebhookId'] = request.form.get('paypalWebhookId', '').strip()

    saved = DatabaseService.save_company_profile(owner_uid, existing)
    if saved:
        flash('Configuración de PayPal guardada correctamente.', 'success')
    else:
        flash('Error al guardar la configuración de PayPal.', 'error')

    return redirect(url_for('web_invoices.company_settings'))


@web_company_bp.route('/company/azul-settings', methods=['POST'])
def save_azul_settings():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    if not check_permission('canModifySettings'):
        return jsonify({"error": "Sin permisos"}), 403

    owner_uid = session['user']['ownerUID']
    existing = DatabaseService.get_company_profile(owner_uid)
    if not existing:
        return jsonify({"error": "Perfil de empresa no encontrado"}), 404

    existing['azulMerchantId'] = request.form.get('azulMerchantId', '').strip()
    existing['azulAuth1'] = request.form.get('azulAuth1', '').strip()
    existing['azulAuth2'] = request.form.get('azulAuth2', '').strip()
    existing['azulBankAccountId'] = request.form.get('azulBankAccountId', '').strip()
    existing['azulAccountingAccountId'] = request.form.get('azulAccountingAccountId', '').strip()

    saved = DatabaseService.save_company_profile(owner_uid, existing)
    if saved:
        flash('Configuración de Azul guardada correctamente.', 'success')
    else:
        flash('Error al guardar la configuración de Azul.', 'error')

    return redirect(url_for('web_invoices.company_settings'))
