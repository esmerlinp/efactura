from flask import Blueprint, session, request, jsonify, redirect, url_for, render_template
from app.services.db_service import DatabaseService
from app.extensions import limiter
import logging

logger = logging.getLogger(__name__)
web_notifications_bp = Blueprint('web_notifications', __name__)


@web_notifications_bp.route('/notifications/poll')
@limiter.limit("30/minute")
def notification_poll():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401

    user_uid = session['user']['uid']
    try:
        sandbox = session.get('is_sandbox_mode', False)
        notifs = DatabaseService.get_user_notifications(user_uid, limit=5, sandbox=sandbox)
        return jsonify(success=True, notifications=notifs)
    except Exception as e:
        logger.error(f"Poll check error: {e}")
        return jsonify(success=False, error=str(e)), 500


@web_notifications_bp.route('/notifications/center')
def notification_center():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))

    user = session['user']
    uid = user.get('uid')
    company_id = session.get('selected_company_id')
    owner_uid = user.get('ownerUID') or (session.get('company_context') or {}).get('owner_uid', '')
    sandbox = session.get('is_sandbox_mode', False)

    from app.services.notification_center import NotificationAggregator
    items, counters = NotificationAggregator.aggregate(
        uid, owner_uid, company_id, sandbox=sandbox
    )

    return render_template(
        'notifications_center.html',
        active_page='notifications',
        items=items,
        counters=counters,
    )


@web_notifications_bp.route('/notifications/center/mark-read', methods=['POST'])
def notification_center_mark_read():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401

    data = request.get_json(silent=True) if request.is_json else (request.form or {})
    item_id = (data.get('item_id') or data.get('id') or '').strip()
    if not item_id:
        return jsonify(success=False, error="item_id requerido"), 400

    uid = session['user']['uid']
    company_id = session.get('selected_company_id')

    from app.services.notification_center import NotificationStateService
    ok = NotificationStateService.mark_read(uid, company_id, item_id)
    return jsonify(success=ok)
