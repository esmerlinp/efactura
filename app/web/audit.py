# app/web/audit.py
"""
Blueprint de Auditoría Web del Sistema
======================================
Rutas para el panel de auditoría con filtros avanzados,
vista de detalle before/after, y exportación CSV.

Acceso restringido: solo owner o usuario con canViewAuditLog=True.
"""
import csv
import io
from datetime import datetime
from flask import (Blueprint, render_template, request, session,
                   redirect, url_for, jsonify, flash, Response)
from app.services.audit_service import AuditService

web_audit_bp = Blueprint('web_audit', __name__)


def _require_audit_access():
    """Verifica que el usuario tenga acceso al log de auditoría."""
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    user = session['user']
    is_owner = user.get('role') == 'owner'
    has_perm = user.get('permissions', {}).get('canViewAuditLog', False)
    if not is_owner and not has_perm:
        flash('No tienes permiso para acceder al Registro de Auditoría.', 'error')
        return redirect(url_for('web_dashboard.dashboard'))
    return None


@web_audit_bp.route('/audit')
def audit_log():
    """Panel principal del Registro de Auditoría con filtros avanzados."""
    denied = _require_audit_access()
    if denied:
        return denied

    owner_uid = session['user']['ownerUID']

    # Obtener lista de usuarios de la compañía (propietario + colaboradores)
    from app.services.db_service import DatabaseService
    company_users = []
    owner_profile = DatabaseService.get_user_profile(owner_uid)
    if owner_profile:
        company_users.append({
            "uid": owner_profile["uid"],
            "name": owner_profile["name"] or owner_profile["email"].split('@')[0],
            "email": owner_profile["email"]
        })
    for member in DatabaseService.get_team_members(owner_uid):
        company_users.append({
            "uid": member["uid"],
            "name": member["name"] or member["email"].split('@')[0],
            "email": member["email"]
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
        page=page,
        per_page=25,
        module_filter=module_f,
        action_filter=action_f,
        user_filter=user_f or None,
        date_from=date_from or None,
        date_to=date_to or None,
        entity_filter=entity_f or None,
        sandbox_filter=sandbox_f if sandbox_f != 'all' else None,
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
    log = AuditService.get_log_detail(owner_uid, log_id)

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

    # Leer filtros del formulario POST
    module_f  = request.form.get('module', 'Todos')
    action_f  = request.form.get('action', 'Todos')
    user_f    = [u.strip() for u in request.form.getlist('user') if u.strip()]
    entity_f  = request.form.get('entity', '').strip()
    date_from = request.form.get('date_from', '').strip()
    date_to   = request.form.get('date_to', '').strip()
    sandbox_f = request.form.get('env', 'all')

    logs = AuditService.export_to_csv_rows(
        owner_uid=owner_uid,
        module_filter=module_f if module_f != 'Todos' else None,
        action_filter=action_f if action_f != 'Todos' else None,
        user_filter=user_f or None,
        date_from=date_from or None,
        date_to=date_to or None,
        entity_filter=entity_f or None,
        sandbox_filter=sandbox_f if sandbox_f != 'all' else None,
    )

    # Generar CSV en memoria
    output = io.StringIO()
    fieldnames = ['Fecha/Hora', 'Módulo', 'Acción', 'Descripción',
                  'Entidad ID', 'Realizado por', 'Email', 'IP', 'Entorno']
    writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()

    for log in logs:
        writer.writerow({
            'Fecha/Hora': log.get('timestamp', '')[:19].replace('T', ' '),
            'Módulo': log.get('module', ''),
            'Acción': log.get('action', ''),
            'Descripción': log.get('entityLabel', ''),
            'Entidad ID': log.get('entityId', ''),
            'Realizado por': log.get('performedBy', ''),
            'Email': log.get('performedByEmail', ''),
            'IP': log.get('ipAddress', ''),
            'Entorno': 'Sandbox' if log.get('isSandbox') else 'Producción',
        })

    output.seek(0)
    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'audit_log_{timestamp_str}.csv'

    return Response(
        output.getvalue().encode('utf-8-sig'),  # BOM para Excel en español
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
