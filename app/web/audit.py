# app/web/audit.py
"""
Blueprint de Auditoría Web del Sistema
======================================
Rutas para el panel de auditoría con filtros avanzados,
vista de detalle before/after, y exportación CSV.

Acceso restringido: solo owner o usuario con canViewAuditLog=True.
"""
from datetime import datetime
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, jsonify, flash)
from app.services.audit_service import AuditService
from app.services.db_service import DatabaseService, _resolve_company_id
from app.utils.module_gate import gate_blueprint_module
from app.utils.decorators import check_permission

web_audit_bp = Blueprint('web_audit', __name__)
gate_blueprint_module(web_audit_bp, 'auditoria')


def _require_audit_access():
    """Verifica que el usuario tenga acceso al log de auditoría."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    user = session['user']
    is_owner = user.get('role') == 'owner'
    has_perm = is_owner or check_permission('canViewAuditLog')
    if not has_perm:
        return render_template('auth/restricted.html', feature_name="Registro de Auditoría", required_permission="canViewAuditLog"), 403
    return None


@web_audit_bp.route('/audit')
def audit_log():
    """Panel principal del Registro de Auditoría con filtros avanzados."""
    denied = _require_audit_access()
    if denied:
        return denied

    owner_uid = session['user']['ownerUID']

    # Obtener lista de usuarios de la compañía (propietario + colaboradores)
    company_id = session.get('selected_company_id') or _resolve_company_id(owner_uid)
    company_users = []
    owner_profile = DatabaseService.get_user_profile(owner_uid, company_id=company_id)
    if owner_profile:
        company_users.append({
            "uid": owner_profile.get("uid", ""),
            "name": owner_profile.get("name") or owner_profile.get("email", "").split('@')[0],
            "email": owner_profile.get("email", "")
        })
    for member in DatabaseService.get_team_members(owner_uid, company_id=company_id):
        company_users.append({
            "uid": member.get("uid", ""),
            "name": member.get("name") or member.get("email", "").split('@')[0],
            "email": member.get("email", "")
        })

    # Leer parámetros de filtro desde URL (user es ahora una lista)
    page         = int(request.args.get('page', 1))
    module_f     = request.args.get('module', 'Todos')
    action_f     = request.args.get('action', 'Todos')
    user_f       = [u.strip() for u in request.args.getlist('user') if u.strip()]
    entity_f     = request.args.get('entity', '').strip()
    date_from    = request.args.get('date_from', '').strip()
    date_to      = request.args.get('date_to', '').strip()
    sandbox_f    = request.args.get('env', 'all')  # all | sandbox | production

    result = AuditService.get_logs(
        owner_uid=owner_uid,
        company_id=company_id,
        page=page,
        per_page=25,
        module_filter=module_f,
        action_filter=action_f,
        user_filter=user_f or None,
        date_from=date_from or None,
        date_to=date_to or None,
        entity_filter=entity_f or None,
        sandbox_filter=sandbox_f if sandbox_f != 'all' else None,
        cursor=request.args.get('cursor') or None,
    )

    # Lista de módulos canónicos para el dropdown
    modules = [
        'Todos', 'Facturas', 'Cotizaciones', 'Gastos', 'Clientes',
        'CRM Interacciones', 'Catálogo / Ítems', 'Configuración Empresa',
        'Usuarios y Permisos', 'Punto de Venta (POS)', 'Cuentas por Cobrar',
        'Cuentas por Pagar', 'Contratos / Recurrencia', 'Notas Internas',
        'Secuencias Fiscales', 'Autenticación', 'Documentos de Cliente',
    ]
    actions = ['Todos', 'CREATE', 'UPDATE', 'DELETE', 'VIEW', 'LOGIN', 'LOGOUT', 'EXPORT']

    return render_template(
        'audit/audit_log.html',
        active_page='audit',
        logs=result['logs'],
        total=result['total'],
        pages=result['pages'],
        next_cursor=result.get('next_cursor'),
        has_more=result.get('has_more', False),
        current_page=result['current_page'],
        is_limited=result.get('is_limited', False),
        modules=modules,
        actions=actions,
        company_users=company_users,
        # Filtros activos (para re-poblar el formulario)
        f_module=module_f,
        f_action=action_f,
        f_users=user_f,
        f_entity=entity_f,
        f_date_from=date_from,
        f_date_to=date_to,
        f_env=sandbox_f,
    )


@web_audit_bp.route('/audit/<log_id>')
def audit_detail(log_id):
    """Vista de detalle de un log específico (before vs after)."""
    denied = _require_audit_access()
    if denied:
        return denied

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id') or _resolve_company_id(owner_uid)
    log = AuditService.get_log_detail(owner_uid, log_id, company_id=company_id)

    if not log:
        flash('Registro de auditoría no encontrado.', 'error')
        return redirect(url_for('web_audit.audit_log'))

    return render_template(
        'audit/audit_detail.html',
        active_page='audit',
        log=log,
    )


@web_audit_bp.route('/audit/export', methods=['POST'])
def audit_export():
    """Exporta los logs de auditoría filtrados como CSV (solo owner)."""
    if 'user' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    user = session['user']
    if user.get('role') != 'owner':
        flash('Solo el propietario puede exportar el registro de auditoría.', 'error')
        return redirect(url_for('web_audit.audit_log'))

    owner_uid = user['ownerUID']
    company_id = session.get('selected_company_id') or _resolve_company_id(owner_uid)

    # Leer filtros del formulario POST
    module_f  = request.form.get('module', 'Todos')
    action_f  = request.form.get('action', 'Todos')
    user_f    = [u.strip() for u in request.form.getlist('user') if u.strip()]
    entity_f  = request.form.get('entity', '').strip()
    date_from = request.form.get('date_from', '').strip()
    date_to   = request.form.get('date_to', '').strip()
    sandbox_f = request.form.get('env', 'all')

    filters = {
        'module_filter': module_f if module_f != 'Todos' else None,
        'action_filter': action_f if action_f != 'Todos' else None,
        'user_filter': user_f or None,
        'date_from': date_from or None,
        'date_to': date_to or None,
        'entity_filter': entity_f or None,
        'sandbox_filter': sandbox_f if sandbox_f != 'all' else None,
    }
    from app.services.audit_export_service import AuditExportService
    job_id = AuditExportService.create_job(company_id, owner_uid, filters, sandbox=True)
    AuditExportService.start_worker(company_id, owner_uid, job_id, filters, sandbox=True)
    return jsonify({'success': True, 'job_id': job_id, 'status': 'pending'})


@web_audit_bp.route('/audit/export/<job_id>', methods=['GET'])
def audit_export_status(job_id):
    denied = _require_audit_access()
    if denied:
        return denied
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id') or _resolve_company_id(owner_uid)
    from app.services.audit_export_service import AuditExportService
    job = AuditExportService.get_job(company_id, job_id, sandbox=True)
    if not job or job.get('ownerUID') != owner_uid:
        return jsonify({'error': 'Job no encontrado'}), 404
    return jsonify(job)


@web_audit_bp.route('/audit/export/<job_id>/download', methods=['GET'])
def audit_export_download(job_id):
    denied = _require_audit_access()
    if denied:
        return denied
    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id') or _resolve_company_id(owner_uid)
    from app.services.audit_export_service import AuditExportService
    url = AuditExportService.get_download_url(company_id, owner_uid, job_id, sandbox=True)
    if not url:
        return jsonify({'error': 'Exportación no disponible'}), 404
    return redirect(url)
