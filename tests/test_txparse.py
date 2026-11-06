from datetime import datetime

from txparse import parse_notification

NOW = datetime(2026, 11, 6, 12, 40)


def p(title, text, now=NOW):
    return parse_notification(title, text, now)


def test_card_sms_single_line():
    r = p('신한카드', '[Web발신]\n신한카드(1234)승인 홍*동 12,000원(일시불)11/06 12:30 스타벅스 누적1,234,567원')
    assert r['tx_type'] == '지출' and r['amount'] == 12000
    assert r['title'] == '스타벅스'
    assert r['datetime'] == datetime(2026, 11, 6, 12, 30)


def test_card_multiline():
    r = p('KB국민카드', 'KB국민카드1234승인\n홍*동님\n45,300원 일시불\n11/05 19:02\n이마트 성수점\n누적 523,000원')
    assert (r['tx_type'], r['amount'], r['title']) == ('지출', 45300, '이마트 성수점')
    assert r['datetime'] == datetime(2026, 11, 5, 19, 2)


def test_installment_and_card_brand_word():
    r = p('현대카드', '현대카드 ZERO 승인\n홍*동\n1,290,000원 할부3개월\n11/06 10:11\n쿠팡')
    assert (r['amount'], r['title']) == (1290000, '쿠팡')


def test_bank_deposit_without_won():
    r = p('KB국민은행', '[KB]11/06 09:00\n123456**789\n홍길동\n입금\n50,000\n잔액1,000,000')
    assert (r['tx_type'], r['amount'], r['title']) == ('수입', 50000, '홍길동')


def test_bank_withdrawal_balance_not_amount():
    r = p('', '신한 11/06 08:15 110-***-123456 출금 32,000원 잔액 1,500,000원 관리비')
    assert (r['tx_type'], r['amount'], r['title']) == ('지출', 32000, '관리비')


def test_toss_style_sentence():
    r = p('토스', '홍길동님이 50,000원을 보냈어요')
    assert r['tx_type'] == '지출' and r['amount'] == 50000 and r['title'] == '홍길동'
    r = p('입금 50,000원', '김영희님이 보낸 돈이 들어왔어요')
    assert r['tx_type'] == '수입' and r['amount'] == 50000


def test_app_push_title_is_merchant():
    r = p('GS25 역삼점', '12,500원 결제 완료')
    assert (r['tx_type'], r['amount'], r['title']) == ('지출', 12500, 'GS25 역삼점')


def test_cancel_is_income():
    r = p('삼성카드', '삼성1234승인취소 홍*동\n12,000원\n11/06 13:00 스타벅스')
    assert r['tx_type'] == '수입' and r['amount'] == 12000 and r['title'] == '스타벅스 (취소)'


def test_year_rollover():
    r = p('', '우리카드 승인 9,900원 12/31 23:50 넷플릭스', now=datetime(2027, 1, 1, 0, 5))
    assert r['datetime'] == datetime(2026, 12, 31, 23, 50)


def test_non_transactions_ignored():
    assert p('카카오톡', '내일 3시에 보자') is None
    assert p('(광고) 신한카드', '최대 50,000원 캐시백 이벤트! 지금 결제하세요') is None
    assert p('카드', '이번 달 결제 예정 금액을 확인하세요') is None
    assert p('', '') is None


def test_no_date_uses_posted_time():
    r = p('네이버페이', '8,900원 결제')
    assert r['datetime'] == NOW and r['amount'] == 8900
