from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from app.services.db_service import DatabaseService
import uuid

web_notes_bp = Blueprint('web_notes', __name__)

@web_notes_bp.route('/notes')
def list_notes():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
        
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    notes = DatabaseService.get_notes(owner_uid, user_uid, sandbox=sandbox)
    statuses = DatabaseService.get_note_statuses(owner_uid, sandbox=sandbox)
    
    return render_template(
        'notes/list.html',
        active_page='notes',
        notes=notes,
        statuses=statuses,
        user_uid=user_uid
    )

@web_notes_bp.route('/notes/create', methods=['POST'])
def create_note():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
    owner_uid = session['user']['ownerUID']
    user_uid = session['user']['uid']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json or request.form
    title = data.get('title', 'Sin título')
    content = data.get('content', '')
    color = data.get('color', 'default')
    visibility = data.get('visibility', 'shared')
    
    note_id = data.get('note_id')
    if not note_id:
        note_id = str(uuid.uuid4())
    
    note_dict = {
        'title': title,
        'content': content,
        'color': color,
        'visibility': visibility,
        'createdBy': user_uid
    }
    
    DatabaseService.save_note(owner_uid, note_id, note_dict, sandbox=sandbox)
    
    return jsonify({'success': True, 'note_id': note_id})

@web_notes_bp.route('/notes/update_status/<note_id>', methods=['POST'])
def update_note_status(note_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json or request.form
    new_status = data.get('status', 'pending')
    
    DatabaseService.update_note_status(owner_uid, note_id, new_status, sandbox=sandbox)
    
    return jsonify({'success': True})

@web_notes_bp.route('/notes/delete/<note_id>', methods=['POST'])
def delete_note(note_id):
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    DatabaseService.delete_note(owner_uid, note_id, sandbox=sandbox)
    
    return jsonify({'success': True})

@web_notes_bp.route('/notes/save_statuses', methods=['POST'])
def save_statuses():
    if 'user' not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
    owner_uid = session['user']['ownerUID']
    sandbox = session.get('is_sandbox_mode', True)
    
    data = request.json
    statuses = data.get('statuses', [])
    
    if not isinstance(statuses, list):
        return jsonify({'success': False, 'error': 'Formato inválido'}), 400
        
    # Validar que cada estado tenga id y name
    for s in statuses:
        if 'id' not in s or 'name' not in s:
            return jsonify({'success': False, 'error': 'Faltan campos requeridos'}), 400
            
    DatabaseService.save_note_statuses(owner_uid, statuses, sandbox=sandbox)
    return jsonify({'success': True})
