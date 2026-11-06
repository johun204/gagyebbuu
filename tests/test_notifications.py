from datetime import datetime, timedelta

from models import db, Transaction, PushLog, DetectedTx

CARD = '[Web발신]\n신한카드(1234)승인 홍*동 12,000원(일시불)11/06 12:30 스타벅스 누적1,234,567원'


def detect(c, text=CARD, title='신한카드', **over):
    body = {'package': 'com.android.mms', 'app_label': '메시지', 'title': title, 'text': text,
            'posted_at': int(datetime.now().timestamp() * 1000)}
    body.update(over)
    return c.post('/api/detected', json=body)


def test_detect_stores_and_logs_notification(make_ledger, client_for):
    _, (chulsoo, younghee), _ = make_ledger()
    c = client_for(chulsoo)
    res = detect(c)
    data = res.get_json()
    assert res.status_code == 200 and data['id']
    assert '12,000원 지출' in data['notify']['title']
    assert data['notify']['url'] == f"/notifications?detected={data['id']}"
    d = db.session.get(DetectedTx, data['id'])
    assert (d.amount, d.title, d.tx_type, d.user_id) == (12000, '스타벅스', '지출', chulsoo.id)
    # 감지 알림은 본인 알림 목록에만 남는다
    assert PushLog.query.filter_by(user_id=chulsoo.id).count() == 1
    assert PushLog.query.filter_by(user_id=younghee.id).count() == 0
    # 상대방은 내 감지 내역을 볼 수 없다
    assert client_for(younghee).get('/api/detected').get_json()['items'] == []


def test_non_transaction_ignored_and_duplicates_merged(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    assert detect(c, text='오늘 저녁 뭐 먹지', title='카톡').get_json()['ignored'] is True
    first = detect(c).get_json()['id']
    assert detect(c).get_json() == {'success': True, 'duplicate': True, 'id': first}
    # 같은 결제를 카드앱이 다른 문구로 다시 알려도 하나로 본다
    assert detect(c, title='신한 SOL페이', text='12,000원 결제 | 스타벅스').get_json()['duplicate'] is True
    assert DetectedTx.query.count() == 1


def test_register_from_sheet_consumes_detection(make_ledger, client_for):
    _, (chulsoo, younghee), cats = make_ledger()
    c = client_for(chulsoo)
    did = detect(c).get_json()['id']
    res = c.post('/transaction', data={'tx_type': '지출', 'amount': '12,000', 'transactor': '철수', 'title': '스타벅스 강남',
                                       'date': '2026-11-06', 'time': '12:30', 'category_id': str(cats['카페'].id),
                                       'detected_id': str(did), 'ajax': '1'})
    assert res.status_code == 200
    assert DetectedTx.query.count() == 0
    assert Transaction.query.one().title == '스타벅스 강남'
    # 상대방이 남의 감지 내역 id 를 보내도 지워지지 않는다
    did2 = detect(c, text=CARD.replace('12,000', '9,000')).get_json()['id']
    client_for(younghee).post('/transaction', data={'tx_type': '지출', 'amount': '1', 'date': '2026-11-06',
                                                   'detected_id': str(did2), 'ajax': '1'})
    assert db.session.get(DetectedTx, did2) is not None


def test_bulk_register_uses_suggested_category(make_ledger, client_for):
    _, (chulsoo, younghee), cats = make_ledger()
    c = client_for(chulsoo)
    # 과거에 스타벅스를 카페로 기록한 적이 있으면 그 분류로
    db.session.add(Transaction(ledger_id=cats['카페'].ledger_id, user_id=chulsoo.id, transactor='철수', tx_type='지출',
                               title='스타벅스', amount=5000, category_id=cats['카페'].id,
                               datetime_val=datetime.now() - timedelta(days=3)))
    db.session.commit()
    a = detect(c).get_json()['id']
    b = detect(c, text='[KB]11/06 09:00\n123456**789\n홍길동\n입금\n50,000\n잔액1,000,000', title='KB').get_json()['id']
    items = {i['id']: i for i in c.get('/api/detected').get_json()['items']}
    assert items[a]['category'] == '카페' and items[b]['tx_type'] == '수입'

    res = c.post('/api/detected/register', json={'ids': [a, b]})
    assert res.get_json() == {'success': True, 'registered': 2}
    assert DetectedTx.query.count() == 0
    txs = {t.title: t for t in Transaction.query.all()}
    assert txs['스타벅스'].category_id == cats['카페'].id and txs['스타벅스'].transactor_user_id == chulsoo.id
    assert txs['홍길동'].tx_type == '수입' and txs['홍길동'].amount == 50000
    # 상대방에게 알림 기록
    assert PushLog.query.filter_by(user_id=younghee.id).one().body.endswith('2건을 등록했어요')
    assert c.post('/api/detected/register', json={'ids': [a]}).status_code == 404


def test_delete_and_expiry(make_ledger, client_for):
    _, (chulsoo, younghee), _ = make_ledger()
    c = client_for(chulsoo)
    did = detect(c).get_json()['id']
    client_for(younghee).post(f'/api/detected/{did}/delete')
    assert db.session.get(DetectedTx, did) is not None
    c.post(f'/api/detected/{did}/delete')
    assert db.session.get(DetectedTx, did) is None

    old = detect(c).get_json()['id']
    db.session.get(DetectedTx, old).created_at = datetime.now() - timedelta(days=8)
    db.session.add(PushLog(user_id=chulsoo.id, title='옛날', created_at=datetime.now() - timedelta(days=31)))
    db.session.commit()
    assert c.get('/api/detected').get_json()['items'] == []
    assert c.get('/notifications').status_code == 200  # 열면서 오래된 것 정리
    assert DetectedTx.query.count() == 0
    assert PushLog.query.filter_by(title='옛날').count() == 0


def test_partner_actions_logged_and_read_all(make_ledger, client_for):
    _, (chulsoo, younghee), _ = make_ledger()
    c = client_for(chulsoo)
    c.post('/transaction', data={'tx_type': '지출', 'amount': '3,000', 'title': '커피', 'date': '2026-11-06', 'ajax': '1'})
    log = PushLog.query.filter_by(user_id=younghee.id).one()
    assert '커피' in log.body and not log.is_read
    y = client_for(younghee)
    page = y.get('/home').get_data(as_text=True)
    assert 'data-unread="1"' in page
    html = y.get('/notifications').get_data(as_text=True)
    assert '커피'.encode('unicode_escape').decode() in html  # tojson 은 한글을 \uXXXX 로 내보낸다
    y.post('/api/notifications/read_all')
    assert PushLog.query.filter_by(user_id=younghee.id, is_read=False).count() == 0
    assert 'data-unread="0"' in y.get('/home').get_data(as_text=True)


def test_foreign_detection_requires_amount(make_ledger, client_for):
    _, (chulsoo, _), _ = make_ledger()
    c = client_for(chulsoo)
    data = detect(c, text='[Web발신]\n신한카드(1*2*)해외승인 홍*동 USD 12.99 11/06 03:12 NETFLIX.COM').get_json()
    assert data['notify']['title'] == '해외 결제를 감지했어요'
    d = db.session.get(DetectedTx, data['id'])
    assert d.amount == 0 and d.title == 'NETFLIX.COM (USD 12.99)'
    # 다른 해외 결제는 금액(0)이 같아도 별개로 저장
    assert 'duplicate' not in detect(c, text='[Web발신]\n신한카드 해외승인 홍*동 USD 5.00 11/06 03:20 STEAM').get_json()
    # 일괄 등록에서는 제외된다
    assert c.post('/api/detected/register', json={'ids': [data['id']]}).status_code == 404
    assert Transaction.query.count() == 0


def test_poll_for_app_notifications(make_ledger, client_for):
    _, (chulsoo, younghee), _ = make_ledger()
    y = client_for(younghee)
    first = y.get('/api/notifications/poll').get_json()
    assert first['items'] == []
    client_for(chulsoo).post('/transaction', data={'tx_type': '지출', 'amount': '3,000', 'title': '커피',
                                                  'date': '2026-11-06', 'ajax': '1'})
    res = y.get(f"/api/notifications/poll?after={first['last_id']}").get_json()
    assert len(res['items']) == 1 and '커피' in res['items'][0]['body']
    assert y.get(f"/api/notifications/poll?after={res['last_id']}").get_json()['items'] == []
