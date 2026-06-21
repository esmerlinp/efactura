from flask import Blueprint, session, request, jsonify
from app.services.db_service import DatabaseService
import logging

logger = logging.getLogger(__name__)
web_notifications_bp = Blueprint('web_notifications', __name__)


@web_notifications_bp.route('/notifications/poll')
def notification_poll():
    if 'user' not in session:
        return jsonify(success=False, error="No autorizado"), 401

    user_uid = session['user']['uid']
    try:
        notifs = DatabaseService.get_user_notifications(user_uid, limit=5)
        return jsonify(success=True, notifications=notifs)
    except Exception as e:
        logger.error(f"Poll check error: {e}")
        return jsonify(success=False, error=str(e)), 500
