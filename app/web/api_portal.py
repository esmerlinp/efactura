import base64
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.services.db_service import DatabaseService, db_firestore, firebase_initialized
from app.services.ecf_readiness_service import EcfReadinessService
from app.utils.decorators import check_permission

web_api_portal_bp = Blueprint('web_api_portal', __name__, template_folder='templates')


def _require_login():
    if 'user' not in session:
        return redirect(url_for('web_auth.login', next=request.url))
    return _require_developers()


def _require_developers():
    """Bloquea el acceso si la empresa no tiene habilitada el Área de Desarrolladores."""
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
    if not profile.get('developersEnabled'):
        return render_template(
            'auth/restricted.html',
            feature_name='Área de Desarrolladores',
            required_permission='developers_enabled',
            custom_message='El acceso al Área de Desarrolladores (API REST) no está habilitado para tu cuenta. '
                           'Contacta a soporte para activarlo.'
        )
    return None


def _get_api_key(owner_uid, company_id):
    profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    key = (profile or {}).get('apiKey', '')
    if key:
        return key
    # Fallback: el apiKey (camelCase) se persiste en users/{owner}/config/profile
    if firebase_initialized:
        try:
            doc = db_firestore.collection('users').document(owner_uid).collection('config').document('profile').get()
            if doc.exists:
                key = doc.to_dict().get('apiKey', '') or ''
        except Exception:
            pass
    return key


def _portal_context():
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id) or {}
    status = EcfReadinessService.get_status(owner_uid, company_id=company_id)
    api_key = _get_api_key(owner_uid, company_id)
    base_url = request.host_url.rstrip('/') + '/api/v1'
    return {
        'owner_uid': owner_uid,
        'company_id': company_id,
        'profile': profile,
        'status': status,
        'api_key': api_key,
        'base_url': base_url,
    }


@web_api_portal_bp.route('/desarrolladores')
def index():
    guard = _require_login()
    if guard:
        return guard
    ctx = _portal_context()
    ctx['active_page'] = 'home'
    return render_template('dev_portal/home.html', **ctx)


@web_api_portal_bp.route('/desarrolladores/docs')
def docs():
    guard = _require_login()
    if guard:
        return guard
    ctx = _portal_context()
    ctx['active_page'] = 'docs'
    return render_template('dev_portal/docs.html', **ctx)


@web_api_portal_bp.route('/desarrolladores/setup')
def setup():
    guard = _require_login()
    if guard:
        return guard
    ctx = _portal_context()
    ctx['active_page'] = 'setup'
    return render_template('dev_portal/setup.html', **ctx)


@web_api_portal_bp.route('/desarrolladores/certificate', methods=['POST'])
def upload_certificate():
    guard = _require_login()
    if guard:
        return guard
    if not check_permission('canModifySettings'):
        flash('No tienes permisos para modificar la configuración.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    existing = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
    if not existing:
        flash('Perfil de empresa no encontrado.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    cert_file = request.files.get('certificateFile')
    if not cert_file or not cert_file.filename:
        flash('Debe seleccionar un archivo .p12 o .pfx.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    ext = cert_file.filename.rsplit('.', 1)[-1].lower() if '.' in cert_file.filename else 'p12'
    if ext not in ('p12', 'pfx'):
        flash('El archivo debe ser .p12 o .pfx.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    cert_password = request.form.get('certificatePassword', '').strip()
    if not cert_password:
        flash('La contraseña del certificado es obligatoria.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    file_data = cert_file.read()
    if not file_data:
        flash('El archivo está vacío.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    cert_content_b64 = base64.b64encode(file_data).decode('utf-8')

    valid, detail = EcfReadinessService._validate_certificate(cert_content_b64, cert_password)
    if not valid:
        flash(detail.get('message', 'El certificado no es válido.'), 'error')
        return redirect(url_for('web_api_portal.setup'))

    existing['certificateName'] = cert_file.filename.rsplit('.', 1)[0]
    existing['certificateExtension'] = f'.{ext}'
    existing['certificateContent'] = cert_content_b64
    existing['certificatePassword'] = cert_password

    saved = DatabaseService.save_company_profile(owner_uid, existing, company_id=company_id)
    if not saved:
        flash('No se pudo guardar el certificado.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    flash('Firma digital cargada y validada correctamente.', 'success')
    return redirect(url_for('web_api_portal.setup'))


@web_api_portal_bp.route('/desarrolladores/api-key/regenerate', methods=['POST'])
def regenerate_api_key():
    guard = _require_login()
    if guard:
        return guard
    if not check_permission('canModifySettings'):
        flash('No tienes permisos para modificar la configuración.', 'error')
        return redirect(url_for('web_api_portal.setup'))

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    new_key = DatabaseService.generate_api_key(owner_uid, company_id=company_id)
    if new_key:
        flash('Nueva API Key generada. Cópiala y guárdala en un lugar seguro.', 'success')
    else:
        flash('Ocurrió un error al generar la API Key.', 'error')
    return redirect(url_for('web_api_portal.setup'))
