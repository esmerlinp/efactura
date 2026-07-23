from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, g
from app.services.db_service import DatabaseService
from app.utils.decorators import require_permission, check_permission
from datetime import datetime, timezone
import uuid

web_notes_bp = Blueprint('web_notes', __name__)


@web_notes_bp.route('/notes')
@require_permission('canManageNotes', 'Gestor de Tareas')
def list_notes():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    notes = DatabaseService.get_notes(owner_uid, user_uid, sandbox=sandbox, company_id=company_id)
    team = DatabaseService.get_team_members(owner_uid, company_id=company_id)

    return render_template(
        'notes/list.html',
        active_page='notes',
        notes=notes,
        team=team,
        user_uid=user_uid
    )


@web_notes_bp.route('/notes/<note_id>')
def get_note(note_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    notes = DatabaseService.get_notes(owner_uid, user_uid, sandbox=sandbox, company_id=company_id)
    note = next((n for n in notes if n.get('id') == note_id), None)
    if not note:
        return jsonify({'success': False, 'error': 'Tarea no encontrada'}), 404

    return jsonify({'success': True, 'note': note})


@web_notes_bp.route('/notes/create', methods=['POST'])
def create_note():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canManageNotes'):
        return jsonify({'success': False, 'error': 'No tienes permisos para gestionar notas'}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or request.form
    title = (data.get('title', '') or '').strip() or 'Sin título'
    content = data.get('content', '')
    visibility = data.get('visibility', 'shared')
    priority = data.get('priority', 'media')
    due_date = data.get('dueDate', '')
    assigned_to = data.get('assignedTo', '')
    entity_type = data.get('entityType', '')
    entity_id = data.get('entityId', '')
    entity_label = data.get('entityLabel', '')

    note_id = data.get('note_id')
    is_update = bool(note_id)
    if not note_id:
        note_id = str(uuid.uuid4())

    note_dict = {
        'title': title,
        'content': content,
        'visibility': visibility,
        'priority': priority,
        'dueDate': due_date if due_date else None,
        'assignedTo': assigned_to,
        'entityType': entity_type,
        'entityId': entity_id,
        'entityLabel': entity_label,
        'createdBy': user_uid,
        'status': 'pending'
    }

    DatabaseService.save_note(owner_uid, note_id, note_dict, sandbox=sandbox, company_id=company_id)

    from app.services.audit_service import AuditService, ACTION_CREATE, MODULE_NOTAS
    action = ACTION_CREATE
    label = f"Tarea {'actualizada' if is_update else 'creada'}: {title}"
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=action,
        module=MODULE_NOTAS,
        entity_id=note_id,
        entity_label=label,
        user_session=session.get('user', {}),
        after=note_dict,
        sandbox=sandbox
    )

    return jsonify({'success': True, 'note_id': note_id})


@web_notes_bp.route('/notes/update/<note_id>', methods=['POST'])
def update_note(note_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canManageNotes'):
        return jsonify({'success': False, 'error': 'No tienes permisos para gestionar notas'}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or request.form
    update_dict = {}
    for field in ('title', 'content', 'priority', 'dueDate', 'assignedTo',
                  'entityType', 'entityId', 'entityLabel', 'visibility'):
        if field in data:
            val = data[field]
            if field == 'dueDate' and not val:
                val = None
            update_dict[field] = val

    if update_dict:
        DatabaseService.update_note(owner_uid, note_id, update_dict, sandbox=sandbox, company_id=company_id)

    return jsonify({'success': True})


@web_notes_bp.route('/notes/update_status/<note_id>', methods=['POST'])
def update_note_status(note_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canManageNotes'):
        return jsonify({'success': False, 'error': 'No tienes permisos para gestionar notas'}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    data = request.json or request.form
    new_status = data.get('status', 'pending')

    DatabaseService.update_note_status(owner_uid, note_id, new_status, sandbox=sandbox, company_id=company_id)

    return jsonify({'success': True})


@web_notes_bp.route('/notes/delete/<note_id>', methods=['POST'])
def delete_note(note_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not check_permission('canManageNotes'):
        return jsonify({'success': False, 'error': 'No tienes permisos para gestionar notas'}), 403

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)

    note_details = {}
    try:
        notes = DatabaseService.get_notes(owner_uid, session['user']['uid'], sandbox=sandbox, company_id=company_id)
        for n in notes:
            if n.get('id') == note_id:
                note_details = n
                break
    except Exception:
        pass

    DatabaseService.delete_note(owner_uid, note_id, sandbox=sandbox, company_id=company_id)

    from app.services.audit_service import AuditService, ACTION_DELETE, MODULE_NOTAS
    AuditService.log_from_request(
        owner_uid=owner_uid,
        action=ACTION_DELETE,
        module=MODULE_NOTAS,
        entity_id=note_id,
        entity_label=f"Tarea eliminada: {note_details.get('title', 'Sin título')}",
        user_session=session.get('user', {}),
        before=note_details,
        sandbox=sandbox
    )

    return jsonify({'success': True})


@web_notes_bp.route('/notes/search-entities')
def search_entities():
    """Autocomplete para vincular tareas a entidades."""
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    owner_uid = session['user']['ownerUID']
    company_id = session.get('selected_company_id')
    sandbox = session.get('is_sandbox_mode', True)
    q = (request.args.get('q', '') or '').strip().lower()
    entity_type = request.args.get('type', 'invoice')

    results = []

    if entity_type == 'invoice' and q:
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox, company_id=company_id)
        for inv in invoices:
            if inv.get('isQuotation'):
                continue
            label = inv.get('invoiceNumber', '') + ' - ' + (inv.get('clientName', '') or '')
            if q in label.lower() or q in (inv.get('encf', '') or '').lower():
                results.append({
                    'id': inv.get('id', ''),
                    'label': label[:80],
                    'type': 'invoice'
                })
                if len(results) >= 10:
                    break

    elif entity_type == 'client' and q:
        clients = DatabaseService.get_clients(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id)
        for c in clients:
            label = (c.get('razonSocial', '') or '') + ' - ' + (c.get('rnc', '') or '')
            if q in label.lower():
                results.append({
                    'id': c.get('id', ''),
                    'label': label[:80],
                    'type': 'client'
                })
                if len(results) >= 10:
                    break

    elif entity_type == 'expense' and q:
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox, branch_id=g.get('branch_id'), project_id=g.get('project_id'), company_id=company_id)
        for exp in expenses:
            label = (exp.get('concept', '') or '') + ' - ' + (exp.get('providerName', '') or '')
            if q in label.lower():
                results.append({
                    'id': exp.get('id', ''),
                    'label': label[:80],
                    'type': 'expense'
                })
                if len(results) >= 10:
                    break

    return jsonify({'success': True, 'results': results})
