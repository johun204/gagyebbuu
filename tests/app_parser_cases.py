"""안드로이드 앱의 해석기(TxParser.kt)가 txparse.py 와 같은 결과를 내는지 검사할 때 쓰는 기대값을 만든다.

test_txparse.py 의 예시와 아래 EXTRA 를 txparse.py 로 해석한 결과를 txparse_cases.json 에 적는다.
앱 쪽 TxParserTest 가 이 파일을 읽어 같은 결과가 나오는지 본다. 규칙이나 예시를 고친 뒤에는 다시 만든다.
    python tests/app_parser_cases.py
"""
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'tests')]

from txparse import parse_notification  # noqa: E402
import test_txparse as t  # noqa: E402

PATH = os.path.join(ROOT, 'android', 'app', 'src', 'test', 'resources', 'txparse_cases.json')

# (제목, 본문, 받은 시각) — test_txparse.py 의 표에 없는 형태들
EXTRA = [
    ('신한카드', '[Web발신]\n신한카드(1*2*)해외승인 홍*동 USD 12.99 11/06 03:12 NETFLIX.COM', t.NOW),
    ('', '스타벅스 6,500원 결제, 포인트 65원 적립 (잔액 3,000원)', t.NOW),
    ('', '우리카드 승인 9,900원 12/31 23:50 넷플릭스', datetime(2027, 1, 1, 0, 5)),
    ('', '체크승인 3,000원 23:55 편의점', datetime(2026, 11, 7, 0, 2)),
    ('신한카드', '[Web발신]\n신한카드(1234)승인 홍*동 12,000원(일시불)11/06 12:30 스타벅스 누적1,234,567원', t.NOW),
    ('신한 SOL페이', '12,000원 결제 | 스타벅스', datetime(2026, 11, 6, 12, 31, 7, 123000)),
    ('', '[Web발신]\n신한카드승인 홍*동 1,500원 11/05 08:10 티머니', t.NOW),
    ('', '[Web발신]\n신한카드 해외승인 홍*동 JPY 1,200 11/06 10:00', t.NOW),
    ('', '해외결제 승인 $25.00 AMAZON', t.NOW),
    ('', '삼성카드 승인 30달러 APPLE.COM/BILL', t.NOW),
    ('', '[Web발신]\n신한카드 승인 홍*동 12,000원 일시불 02/30 12:30 스타벅스', t.NOW),
    ('', '2026.11.06. (금) 13:05 출금 4,000원 컴포즈커피', t.NOW),
    ('', '11월 6일 오전 12시 5분 택시 결제 23,400원', t.NOW),
    ('', '2025년 12월 31일 오후 11시 승인 50,000원 송년회', t.NOW),
    ('', '오후 3:20 GS25에서 2,300원 결제', t.NOW),
    ('', '11/6 출금 1,000원 수수료 500원 ATM', t.NOW),
    ('KB스타뱅킹', '출금 : 120,000원\n받는분 : 김*수\n거래일시 : 11.06 09:30\n잔액 : 80,000원', t.NOW),
    ('알림톡', '<결제금액> = 9,900\n[상호] : ㈜ 넷플릭스서비시스코리아\n구분 : 승인취소', t.NOW),
    ('알림톡', '■ 거래구분 : 출금\n■ 금액 : 0원\n■ 내용 : 이자\n출금 3,300원', t.NOW),
    ('토스', '김영희님께 30,000원을 송금했어요', t.NOW),
    ('토스', '김*희님이 30,000원을 보냈어요', t.NOW),
    ('카카오뱅크', '주식회사 카카오에서 2,500,000원이 입금됐어요. 급여', t.NOW),
    ('', '[Web발신]\n[우리] 11/06 14:00 입금 1,000,000원 홍길동 -> 내통장', t.NOW),
    ('출금 5,000원', '내 통장 ▶ (주)다이소', t.NOW),
    ('', '국민건강보험 자동이체 출금 123,450원 11/10', t.NOW),
    ('', '[Web발신]\nKB국민카드1*2*승인\n홍*동님\n10,000원 할부6개월\n11/06 12:00\n카드대금결제\n누적 0원', t.NOW),
    ('', '신한은행 입금 99,999,999,999,999원 홍길동', t.NOW),
    ('', '승인 1234-5678-9012-3456 15,000원 맥도날드(강남2호점)', t.NOW),
    ('', '​[Web발신]\r\n하나카드 승인\r\n\r\n홍*동님 ₩ 7,700\r\n11/06 08:00\r\n파리바게뜨', t.NOW),
    ('', '• 승인 4,400원\n• 가맹점: "빽다방"', t.NOW),
    ('', '체크카드 08:15 잔액 5,000원', t.NOW),
    ('', '환불 완료 15,000원 쿠팡', t.NOW),
    ('', '최대 30,000원 할인 쿠폰으로 결제하세요', t.NOW),
    ('', '오늘 점심 12:30 에 봐요', t.NOW),
    ('', '주문하신 상품이 배송을 시작했어요', t.NOW),
    ('', '결제 완료', t.NOW),
]


def build():
    inputs = [(title, text, t.NOW) for title, text, *_ in t.CASES]
    inputs += [(title, text, t.NOW) for title, text in t.test_non_transactions_ignored.pytestmark[0].args[1]]
    cases = []
    for title, text, posted_at in inputs + EXTRA:
        r = parse_notification(title, text, posted_at)
        if r:
            r = dict(r, datetime=r['datetime'].isoformat())
        cases.append({'title': title, 'text': text, 'posted_at': posted_at.isoformat(), 'expected': r})
    return cases


if __name__ == '__main__':
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump(build(), f, ensure_ascii=False, indent=1)
        f.write('\n')
    print(f'{len(build())} cases -> {PATH}')
