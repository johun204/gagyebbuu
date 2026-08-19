import json
from flask import Blueprint, request, jsonify
from pywebpush import webpush, WebPushException

import config
from models import db, User, PushSubscription

push_bp = Blueprint('push', __name__)


def notify_partner(ledger_id, actor_user_id, title, body):
    if not config.VAPID_PRIVATE_KEY:
        return

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
                vapid_claims={'sub': config.VAPID_CLAIM_EMAIL}
            )
        except WebPushException as e:
            status = getattr(e.response, 'status_code', None)
            if status in (404, 410):
                db.session.delete(sub)
        except Exception:
            pass

    db.session.commit()


@push_bp.route('/api/push/vapid_public_key')
def vapid_public_key():
    return jsonify({'key': config.VAPID_PUBLIC_KEY})


@push_bp.route('/api/push/subscribe', methods=['POST'])
def subscribe():
    data = request.json or {}
    endpoint = data.get('endpoint')
    keys = data.get('keys') or {}
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    if not endpoint or not p256dh or not auth:
        return jsonify({'success': False}), 400

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
    data = request.json or {}
    endpoint = data.get('endpoint')
    if endpoint:
        PushSubscription.query.filter_by(endpoint=endpoint, user_id=request.user_id).delete()
        db.session.commit()
    return jsonify({'success': True})
