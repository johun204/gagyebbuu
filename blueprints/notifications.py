from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, g

from models import db, Category, Transaction, PushLog, DetectedTx
from helpers import (require_ledger, json_error, clean_text, get_or_create_uncategorized, parse_int,
                     MAX_TITLE_LEN)
from txparse import parse_notification, MAX_RAW_LEN
from blueprints.push import notify_partner
from blueprints.transactions import suggest_category_id

notifications_bp = Blueprint('notifications', __name__)

LOG_KEEP_DAYS = 30        # 알림 목록 보관 기간
DETECTED_KEEP_DAYS = 7    # 감지 내역 유효 기간
_DUP_WINDOW = timedelta(minutes=3)  # 문자와 카드앱이 같은 결제를 각각 알리는 경우를 하나로 본다
_MAX_BULK = 100


def purge_old(user_id):
    now = datetime.now()
    PushLog.query.filter(PushLog.user_id == user_id,
                         PushLog.created_at < now - timedelta(days=LOG_KEEP_DAYS)).delete()
    DetectedTx.query.filter(DetectedTx.user_id == user_id,
                            DetectedTx.created_at < now - timedelta(days=DETECTED_KEEP_DAYS)).delete()


def badge_counts(user_id):
    """상단 종 버튼 배지용 (안 읽은 알림 수, 대기 중인 감지 내역 수)."""
    now = datetime.now()
    unread = PushLog.query.filter(PushLog.user_id == user_id, PushLog.is_read.is_(False),
                                  PushLog.created_at >= now - timedelta(days=LOG_KEEP_DAYS)).count()
    detected = DetectedTx.query.filter(DetectedTx.user_id == user_id,
                                       DetectedTx.created_at >= now - timedelta(days=DETECTED_KEEP_DAYS)).count()
    return unread, detected


def _valid_detected(user_id):
    since = datetime.now() - timedelta(days=DETECTED_KEEP_DAYS)
    return DetectedTx.query.filter(DetectedTx.user_id == user_id, DetectedTx.created_at >= since)


def _serialize_detected(d, cat):
    expires = d.created_at + timedelta(days=DETECTED_KEEP_DAYS)
    return {
        'id': d.id, 'tx_type': d.tx_type, 'amount': d.amount, 'title': d.title,
        'date': d.datetime_val.strftime('%Y-%m-%d'), 'time': d.datetime_val.strftime('%H:%M'),
        'source_label': d.source_label, 'raw_text': d.raw_text,
        'category_id': cat.id if cat else None, 'category': cat.name if cat else None,
        'detected_at': d.created_at.strftime('%Y-%m-%d %H:%M'),
        'days_left': max(0, (expires - datetime.now()).days),
    }


def _suggested_category(ledger_id, d, uncat_id):
    if d.tx_type != '지출':
        return None
    cat_id = suggest_category_id(ledger_id, d.tx_type, d.title, d.amount, uncat_id)
    return db.session.get(Category, cat_id) if cat_id else None


def detected_list(user, ledger):
    uncat_id = get_or_create_uncategorized(ledger.id)
    items = _valid_detected(user.id).order_by(DetectedTx.datetime_val.desc()).all()
    return [_serialize_detected(d, _suggested_category(ledger.id, d, uncat_id)) for d in items]


@notifications_bp.route('/notifications')
@require_ledger
def notifications():
    user, ledger = g.user, g.ledger
    purge_old(user.id)
    db.session.commit()
    logs = PushLog.query.filter_by(user_id=user.id).order_by(PushLog.created_at.desc()).limit(300).all()
    log_items = [{'id': l.id, 'title': l.title, 'body': l.body, 'url': l.url, 'is_read': l.is_read,
                  'created_at': l.created_at.strftime('%Y-%m-%d %H:%M')} for l in logs]
    detected = detected_list(user, ledger)
    db.session.commit()  # 미분류 분류가 새로 만들어졌을 수 있다
    return render_template('notifications.html', ledger=ledger, current_user=user,
                           logs=log_items, detected=detected,
                           log_keep_days=LOG_KEEP_DAYS, detected_keep_days=DETECTED_KEEP_DAYS)


@notifications_bp.route('/api/notifications/read_all', methods=['POST'])
@require_ledger
def read_all():
    PushLog.query.filter_by(user_id=g.user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/api/detected')
@require_ledger
def api_detected():
    items = detected_list(g.user, g.ledger)
    db.session.commit()
    return jsonify({'items': items})


@notifications_bp.route('/api/detected', methods=['POST'])
@require_ledger
def api_detect():
    """안드로이드 앱이 기기 알림 원문을 보낸다. 거래로 해석되면 저장하고 알림 문구를 돌려준다."""
    user = g.user
    data = request.get_json(silent=True) or {}
    title = clean_text(data.get('title'), 200)
    text = clean_text(data.get('text'), MAX_RAW_LEN)
    posted_ms = parse_int(data.get('posted_at'))
    now = datetime.now()
    posted_at = now
    if posted_ms:
        posted_at = datetime.fromtimestamp(posted_ms / 1000)
        if posted_at > now + timedelta(minutes=5) or posted_at < now - timedelta(days=DETECTED_KEEP_DAYS):
            posted_at = now

    parsed = parse_notification(title, text, posted_at)
    if not parsed:
        return jsonify({'success': True, 'ignored': True})

    raw = '\n'.join(s for s in (title, text) if s)[:MAX_RAW_LEN]
    purge_old(user.id)
    dup = _valid_detected(user.id).filter(
        db.or_(DetectedTx.raw_text == raw,
               db.and_(DetectedTx.amount == parsed['amount'], DetectedTx.tx_type == parsed['tx_type'],
                       DetectedTx.created_at >= now - _DUP_WINDOW))).first()
    if dup:
        db.session.commit()
        return jsonify({'success': True, 'duplicate': True, 'id': dup.id})

    d = DetectedTx(user_id=user.id, source_app=clean_text(data.get('package'), 150),
                   source_label=clean_text(data.get('app_label'), 100), raw_text=raw,
                   tx_type=parsed['tx_type'], amount=parsed['amount'],
                   title=clean_text(parsed['title'], MAX_TITLE_LEN), datetime_val=parsed['datetime'])
    db.session.add(d)
    db.session.flush()
    verb = '지출' if d.tx_type == '지출' else '입금'
    notice_title = f"{d.amount:,}원 {verb}을 감지했어요"
    notice_body = f"{d.title or d.source_label or '내용 없음'} · 눌러서 바로 등록하기 ({DETECTED_KEEP_DAYS}일간 보관)"
    url = f'/notifications?detected={d.id}'
    # 기기에서 바로 알림이 뜨고 대기 건수는 '감지된 내역'으로 따로 세므로 목록에는 읽은 상태로 남긴다
    db.session.add(PushLog(user_id=user.id, title=notice_title, body=notice_body[:255], url=url, is_read=True))
    db.session.commit()
    return jsonify({'success': True, 'id': d.id, 'notify': {'title': notice_title, 'body': notice_body, 'url': url}})


@notifications_bp.route('/api/detected/<int:detected_id>/delete', methods=['POST'])
@require_ledger
def api_detected_delete(detected_id):
    DetectedTx.query.filter_by(id=detected_id, user_id=g.user.id).delete()
    db.session.commit()
    return jsonify({'success': True})


@notifications_bp.route('/api/detected/register', methods=['POST'])
@require_ledger
def api_detected_register():
    """감지 내역 여러 건을 미리 채워진 값 그대로 한 번에 등록한다."""
    user, ledger = g.user, g.ledger
    ids = (request.get_json(silent=True) or {}).get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > _MAX_BULK:
        return json_error('등록할 내역을 골라주세요.')
    ids = [i for i in (parse_int(x) for x in ids) if i is not None]
    items = _valid_detected(user.id).filter(DetectedTx.id.in_(ids)).all()
    if not items:
        return json_error('이미 처리됐거나 기간이 지난 내역이에요.', 404)

    uncat_id = get_or_create_uncategorized(ledger.id)
    for d in items:
        cat = _suggested_category(ledger.id, d, uncat_id)
        db.session.add(Transaction(
            ledger_id=ledger.id, user_id=user.id, transactor=user.nickname[:50], transactor_user_id=user.id,
            tx_type=d.tx_type, amount=d.amount, title=d.title or d.source_label[:MAX_TITLE_LEN],
            memo='', datetime_val=d.datetime_val, category_id=cat.id if cat else uncat_id))
        db.session.delete(d)
    db.session.commit()

    notify_partner(ledger.id, user.id, '가계쀼', f"{user.nickname}님이 내역 {len(items)}건을 등록했어요")
    return jsonify({'success': True, 'registered': len(items)})
