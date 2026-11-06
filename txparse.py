"""기기 알림(문자/카드앱/은행앱 등) 문구에서 입출금 내역을 뽑아낸다.

안드로이드 앱은 알림 원문만 서버로 보내고 해석은 여기서 한다. 그래서 해석 규칙을 고쳐도
앱을 다시 설치할 필요가 없다. 특정 앱 전용 규칙 없이 카드 승인/은행 입출금 문자에 흔한
형태(금액+'원', '입금 50,000', 'MM/DD HH:MM', 마스킹된 이름 등)만으로 판단한다.
"""
import re
from datetime import datetime, timedelta

_NUM = r'\d{1,3}(?:,\d{3})+|\d+'
# 'xx원' 형태의 금액
_AMOUNT_WON = re.compile(rf'({_NUM})\s*원')
# 원 표기가 없는 은행 문자: '입금 50,000', '출금\n50,000'
_AMOUNT_AFTER_KEYWORD = re.compile(rf'(?:입금|출금|이체|결제|승인|지급)\s*:?\s*({_NUM})')
# 금액 바로 앞에 이 말이 있으면 거래 금액이 아니다 (누적 사용액, 잔액 등)
_NOT_TX_AMOUNT = re.compile(r'(누적|잔액|잔고|한도|가능|포인트|적립|합계|총액)\s*:?\s*$')

_INCOME = re.compile(r'취소|환불|입금|받았|들어왔|캐시백|급여|이자')
_EXPENSE = re.compile(r'승인|결제|출금|사용|이체|보냈|납부|자동이체|지급')
_REFUND = re.compile(r'취소|환불')
_AD = re.compile(r'\(광고\)|\[광고\]')

_DATE_TIME = re.compile(r'(\d{1,2})[/.-](\d{1,2})\s*(\d{1,2}):(\d{2})')

# 내용(가맹점/보낸 사람) 후보에서 지울 것들
_NOISE_PATTERNS = [
    re.compile(r'\[[^\]]*\]'),                           # [Web발신], [KB]
    re.compile(r'\([^)]*\)'),                            # (1234), (일시불)
    re.compile(rf'(?:누적|잔액|잔고|한도|가능|포인트|적립|합계|총액)\s*:?\s*(?:{_NUM})\s*원?'),
    re.compile(rf'(?:{_NUM})\s*원'),
    re.compile(r'\d{1,2}[/.-]\d{1,2}(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?'),
    re.compile(r'\d{1,2}:\d{2}(?::\d{2})?'),
    re.compile(r'\S*\*\S*'),                             # 홍*동, 123-***-456
    re.compile(r'\S*(?:카드|은행|뱅크|BANK|Bank|bank|체크|신용)\S*'),
    re.compile(r'\b[\d-]{4,}\b'),                        # 계좌/카드 번호, 남은 숫자
]
_NOISE_WORDS = {
    '승인', '결제', '일시불', '입금', '출금', '이체', '사용', '취소', '승인취소', '환불', '지급', '거절',
    '누적', '잔액', '원', '을', '를', '이', '가', '에서', '으로', '로', '님', '금액', '알림', '내역',
    'Web발신', '해외', '국내', '건', '완료',
}
_VERB_TAIL = re.compile(r'(습니다|어요|았어요|었어요|해요|돼요|됨|했음|되었음)[.!]?$')
_HALBU = re.compile(r'^할부\S*$|^\d+개월$')
_NAME_SUFFIX = re.compile(r'^(.+?)님(?:이|께|에게|으로부터|의)?$')

MAX_RAW_LEN = 1000
MAX_TITLE_LEN = 100


def _pick_amount(text):
    for m in _AMOUNT_WON.finditer(text):
        if _NOT_TX_AMOUNT.search(text[max(0, m.start() - 8):m.start()]):
            continue
        n = int(m.group(1).replace(',', ''))
        if n > 0:
            return n
    m = _AMOUNT_AFTER_KEYWORD.search(text)
    if m:
        n = int(m.group(1).replace(',', ''))
        if n > 0:
            return n
    return None


def _pick_datetime(text, posted_at):
    m = _DATE_TIME.search(text)
    if not m:
        return posted_at
    mon, day, hh, mm = (int(x) for x in m.groups())
    try:
        dt = datetime(posted_at.year, mon, day, hh, mm)
    except ValueError:
        return posted_at
    if dt > posted_at + timedelta(days=1):  # 1월 초에 받은 12월 31일 문자
        dt = dt.replace(year=dt.year - 1)
    return dt


def _clean_token(tok):
    tok = tok.strip(' ,.:;|/·-')
    if not tok or re.fullmatch(r'[\d,.]+', tok) or tok in _NOISE_WORDS or _VERB_TAIL.search(tok) or _HALBU.match(tok):
        return ''
    m = _NAME_SUFFIX.match(tok)
    if m:
        tok = m.group(1)
    # '스타벅스에서' 처럼 붙은 조사만 떼어낸다 (두 글자 이하 단어는 그대로)
    if len(tok) > 3:
        tok = re.sub(r'(에서|으로|에게)$', '', tok)
    return '' if tok in _NOISE_WORDS else tok


def _pick_title(text):
    # 지운 자리에서 조각을 나눠, 서로 떨어져 있던 말(은행명, 가맹점)이 한 덩어리가 되지 않게 한다
    for p in _NOISE_PATTERNS:
        text = p.sub('\n', text)
    candidates = []
    for line in text.split('\n'):
        words = [w for w in (_clean_token(t) for t in line.split()) if w]
        if words:
            candidates.append(' '.join(words))
    # 카드/은행 문자는 대개 가맹점(보낸 사람)이 맨 뒤에 온다
    return candidates[-1][:MAX_TITLE_LEN] if candidates else ''


def parse_notification(title, text, posted_at=None):
    """알림 제목/본문에서 {'tx_type','amount','title','datetime'} 을 뽑는다. 거래 알림이 아니면 None."""
    posted_at = posted_at or datetime.now()
    full = '\n'.join(s for s in ((title or '').strip(), (text or '').strip()) if s)
    full = re.sub(r'[ \t ]+', ' ', full.replace('\r', ''))[:MAX_RAW_LEN]
    if not full or _AD.search(full):
        return None
    if not (_INCOME.search(full) or _EXPENSE.search(full)):
        return None
    amount = _pick_amount(full)
    if amount is None:
        return None

    if _REFUND.search(full):
        tx_type = '수입'
    elif _INCOME.search(full) and not re.search(r'출금|보냈|결제|승인', full):
        tx_type = '수입'
    else:
        tx_type = '지출'

    merchant = _pick_title(full)
    if tx_type == '수입' and _REFUND.search(full) and merchant:
        merchant = f'{merchant} (취소)'[:MAX_TITLE_LEN]
    return {
        'tx_type': tx_type,
        'amount': amount,
        'title': merchant,
        'datetime': _pick_datetime(full, posted_at),
    }
