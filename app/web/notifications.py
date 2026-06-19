import json
import time
import logging
from datetime import datetime, timezone as dt_tz
from flask import Blueprint, session, request, Response, stream_with_context
from app.services.db_service import DatabaseService

logger = logging.getLogger(__name__)
web_notifications_bp = Blueprint('web_notifications', __name__)


@web_notifications_bp.route('/notifications/stream')
def notification_stream():
    if 'user' not in session:
        return Response("", status=401)

    user_uid = session['user']['uid']
    last_id = request.args.get('last_id', '')

    def event_stream():
        sent_ids = set()
        if last_id:
            sent_ids.add(last_id)

        while True:
            try:
                notifs = DatabaseService.get_user_notifications(user_uid, limit=5)
                for n in notifs:
                    nid = n.get('id', '')
                    if nid and nid not in sent_ids:
                        payload = json.dumps({
                            'id': nid,
                            'title': n.get('title', ''),
                            'message': n.get('message', n.get('body', '')),
                            'type': n.get('type', 'info'),
                            'encf': n.get('encf', ''),
                            'link': n.get('link', ''),
                            'clientName': n.get('clientName', ''),
                            'documentNumber': n.get('documentNumber', ''),
                            'documentType': n.get('documentType', ''),
                            'createdAt': n.get('createdAt', ''),
                        })
                        yield f"event: notification\ndata: {payload}\n\n"
                        sent_ids.add(nid)
            except Exception as e:
                logger.debug(f"SSE check error: {e}")

            yield ": heartbeat\n\n"
            time.sleep(5)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        }
    )
