import json
import logging
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException

import config
from models import db, User, PushSubscription
from helpers import json_error

push_bp = Blueprint('push', __name__)
log = logging.getLogger(__name__)

_PUSH_TIMEOUT = 5  # 초. 푸시 서버가 느려도 거래 등록 응답이 오래 막히지 않도록


def notify_partner(ledger_id, actor_user_id, title, body):
    """상대방에게 웹 푸시를 보낸다. 거래 저장(commit) 이후에 호출되며,
    여기서 어떤 오류가 나도 원래 요청은 성공으로 끝나야 하므로 예외를 밖으로 내보내지 않는다."""
    if not config.VAPID_PRIVATE_KEY:
        return
    try:
        partner_ids = [u.id for u in User.query.filter(
            User.ledger_id == ledger_id, User.id != actor_user_id
        ).all()]
        if not partner_ids:
            return

        subs = PushSubscription.query.filter(PushSubscription.user_id.in_(partner_ids)).all()
        payload = json.dumps({'title': title, 'body': body, 'url': '/home'})

        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        'endpoint': sub.endpoint,
                        'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}
                    },
                    data=payload,
                    vapid_private_key=config.VAPID_PRIVATE_KEY,
                    vapid_claims={'sub': config.VAPID_CLAIM_EMAIL},
                    timeout=_PUSH_TIMEOUT
                )
            except WebPushException as e:
                status = getattr(e.response, 'status_code', None)
                if status in (404, 410):
                    db.session.delete(sub)  # 만료된 구독 정리
            except Exception:
                log.exception('web push failed')

        db.session.commit()
    except Exception:
        db.session.rollback()
        log.exception('notify_partner failed')


@push_bp.route('/api/push/vapid_public_key')
def vapid_public_key():
    return jsonify({'key': config.VAPID_PUBLIC_KEY})


@push_bp.route('/api/push/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    keys = data.get('keys') or {}
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not all(isinstance(v, str) and v for v in (endpoint, p256dh, auth)):
        return json_error('잘못된 구독 정보입니다.')
    if len(endpoint) > 500 or len(p256dh) > 255 or len(auth) > 255:
        return json_error('잘못된 구독 정보입니다.')
    if not db.session.get(User, request.user_id):
        return json_error('Unauthorized', 401)

    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if not sub:
        sub = PushSubscription(endpoint=endpoint)
        db.session.add(sub)
    sub.user_id = request.user_id
    sub.p256dh = p256dh
    sub.auth = auth
    db.session.commit()
    return jsonify({'success': True})


@push_bp.route('/api/push/unsubscribe', methods=['POST'])
def unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get('endpoint')
    if isinstance(endpoint, str) and endpoint:
        PushSubscription.query.filter_by(endpoint=endpoint, user_id=request.user_id).delete()
        db.session.commit()
    return jsonify({'success': True})
