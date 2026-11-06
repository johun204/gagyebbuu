"""기기 알림(문자/카드앱/은행앱/알림톡 등) 문구에서 입출금 내역을 뽑아낸다.

안드로이드 앱은 알림 원문만 서버로 보내고 해석은 여기서 한다. 그래서 해석 규칙을 고쳐도
앱을 다시 설치할 필요가 없다. 특정 앱 전용 규칙 없이 흔한 형태만으로 판단한다.
  - '항목 : 값' 형태(알림톡): 승인금액/가맹점명/거래일시/거래구분 등
  - 한 줄/여러 줄 카드·은행 문자: 금액+'원', '₩12,000', '입금 50,000', 'MM/DD HH:MM', 마스킹된 이름 등
  - 문장형 앱 알림: '스타벅스에서 12,000원 결제', '홍길동님이 5만원을 보냈어요' 등
금액을 원화로 알 수 없는 해외 결제는 amount=0 으로 돌려주고(사용자가 금액 입력), 제목에 통화를 남긴다.
"""
import re
import unicodedata
from datetime import datetime, timedelta

MAX_RAW_LEN = 1000
MAX_TITLE_LEN = 100

_NUM = r'\d{1,3}(?:,\d{3})+|\d+'
_KRW = re.compile(rf'(?:₩|KRW|원화)\s*({_NUM})|({_NUM})\s*원(?!화)')
_FOREIGN = re.compile(r'(USD|JPY|EUR|CNY|GBP|HKD|SGD|AUD|CAD|THB|VND|PHP|TWD|CHF|US\$|\$|€|£|¥)\s*(\d[\d,]*(?:\.\d+)?)'
                      r'|(\d[\d,]*(?:\.\d+)?)\s*(USD|JPY|EUR|CNY|GBP|HKD|SGD|AUD|CAD|THB|VND|PHP|TWD|CHF|달러|엔|유로|위안)')
# 원 표기가 없는 은행 문자: '입금 50,000', '출금\n50,000', '금액:50,000'
_BARE_AFTER_KEYWORD = re.compile(rf'(?:입금|출금|이체|결제|승인|지급|인출|송금|금액)\s*:?\s*(?<![\d-])({_NUM})(?![\d,]*\s*원)(?![-/:.*\d])')

# 금액 바로 앞/뒤에 이런 말이 있으면 거래 금액이 아니다
_EXCLUDE_BEFORE = re.compile(r'(누적|잔액|잔고|한도|가능|포인트|적립|합계|총액|수수료|예정|청구|최대|최소|할인|이용가능|사용가능)[^\n\d]{0,4}$')
_EXCLUDE_AFTER = re.compile(r'^\s*(적립|할인|포인트|이상|이하|한도)')

_TX_WORDS = re.compile(r'승인|결제|출금|입금|사용|이체|송금|보냈|받았|들어왔|환불|취소|납부|지급|인출|캐시백|급여|이자|구매|충전')
_INCOME_WORDS = re.compile(r'입금(?!자|처|예정)|받았|받은|들어왔|들어옴|환불|캐시백|급여|이자|수령|입금됨|충전')
_EXPENSE_WORDS = re.compile(r'승인|결제|출금|사용|보냈|보낸|송금|납부|자동이체|이체|지급|인출|구매')
_REFUND = re.compile(r'취소|환불')
_REJECT = re.compile(r'\(광고\)|\[광고\]|^광고|승인\s*거절|거절|예정|명세서|인증\s*번호|OTP|결제일\s*안내|미납|연체|이벤트|혜택\s*안내|실패')

# '항목 : 값' 줄
_KV_LINE = re.compile(r'^\s*[\[(<]?\s*([가-힣A-Za-z][가-힣A-Za-z ]{0,11}?)\s*[\])>]?\s*[:=]\s*(.+?)\s*$')
_KV_AMOUNT = ('금액', '결제액', '출금액', '입금액', '이용액', '승인액', '거래액', '송금액', '이체액')
_KV_AMOUNT_NOT = ('누적', '잔액', '한도', '가능', '예정', '포인트', '합계', '총', '수수료', '청구')
_KV_MERCHANT = ('가맹점', '사용처', '이용처', '상호', '결제처', '거래처', '상점', '받는분', '받는사람', '보낸분',
                '보낸사람', '입금자', '출금처', '송금인', '수취인', '적요', '내용', '이용내역', '사용내역', '판매자', '업체')
_KV_DATETIME = ('일시', '일자', '시간', '날짜', '시각')
_KV_TYPE = ('거래구분', '구분', '거래종류', '거래유형', '유형', '종류')

# 날짜/시간
_DT_PATTERNS = [
    re.compile(r'(?P<y>20\d{2})\s*[./-]\s*(?P<mo>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})\.?(?:\s*\([^)]*\))?[\s,]*(?P<h>\d{1,2}):(?P<mi>\d{2})'),
    re.compile(r'(?<![\d.,])(?P<mo>\d{1,2})[./-](?P<d>\d{1,2})(?:\s*\([^)]*\))?[\s,]*(?P<h>\d{1,2}):(?P<mi>\d{2})'),
    re.compile(r'(?:(?P<y>20\d{2})년\s*)?(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일(?:\s*\([^)]*\))?\s*(?:(?P<ap>오전|오후)\s*)?(?P<h>\d{1,2})(?:시|:)\s*(?:(?P<mi>\d{1,2})분?)?'),
    re.compile(r'(?P<y>20\d{2})\s*[./-]\s*(?P<mo>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})'),
    re.compile(r'(?:(?P<y>20\d{2})년\s*)?(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일'),
    re.compile(r'(?<![\d.,/])(?P<mo>\d{1,2})/(?P<d>\d{1,2})(?![\d/])'),
    re.compile(r'(?<![\d:])(?:(?P<ap>오전|오후)\s*)?(?P<h>\d{1,2}):(?P<mi>\d{2})(?::\d{2})?(?![\d:])'),
]

# 가맹점(상대방) 후보에서 지울 것들. 지운 자리에서 조각을 나눈다.
_NOISE_PATTERNS = [
    re.compile(r'\[[^\]]*\]'),                            # [Web발신], [KB]
    re.compile(r'\([^)]*\)'),                             # (1*2*), (일시불), (주), (목)
    re.compile(rf'(?:누적|잔액|잔고|한도|가능|포인트|적립|합계|총액|수수료)\s*:?\s*(?:₩|KRW)?\s*(?:{_NUM})\s*원?'),
    _FOREIGN,
    re.compile(rf'(?:₩|KRW|원화)\s*(?:{_NUM})|(?:{_NUM})\s*원'),
    re.compile(r'(?:20\d{2}\s*[./-]\s*)?\d{1,2}\s*[./-]\s*\d{1,2}(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?'),
    re.compile(r'(?:20\d{2}년\s*)?\d{1,2}월\s*\d{1,2}일|(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?|\d{1,2}:\d{2}(?::\d{2})?'),
    re.compile(r'\S*\*\S*'),                              # 홍*동, 123-***-456, 1*2*
    re.compile(r'[→←▶▷►]|->|<-|\|'),
    re.compile(r'(?<![\w])[\d-]{4,}(?![\w])'),            # 계좌/카드 번호
]
_NOISE_WORDS = {
    '승인', '결제', '일시불', '입금', '출금', '이체', '사용', '취소', '승인취소', '결제취소', '환불', '지급', '거절',
    '누적', '잔액', '원', '을', '를', '이', '가', '은', '는', '에서', '으로', '로', '님', '금액', '알림', '내역', '안내',
    'Web발신', 'web발신', '해외', '국내', '건', '완료', '결제완료', '승인완료', '출금완료', '입금완료', '송금완료',
    '이용', '거래', '총', '내', '통장', '계좌', '입출금', '입출금통장', '고객님', '회원님', '본인', '가족', '개인', '법인',
    '신용', '체크', '할부', '무이자', '승인안내', '결제안내', '이용안내', '거래안내', '입출금알림', '결제알림', '승인알림',
    '자동이체', '송금', '받기', '보내기', '충전', '출금예정', '타행', '당행', '이체입금', '이체출금', '전자금융', '인터넷', '모바일',
    '적립', '보낸', '받은', '돈', '돈이', '돈을', '들어온', '결제한', '사용한', '이용한', '보낸돈', '받은돈',
    'ATM', 'CD', '해외승인', '해외결제', '체크승인', '신용승인', '정상', '처리', '접수', '사용금액', '결제금액', '승인금액',
}
# 카드사/은행/간편결제 이름 (정확히 이 낱말일 때만 지운다)
_BRAND_WORDS = {
    '신한', 'KB', '국민', 'KB국민', '우리', '하나', '농협', 'NH', 'NH농협', 'IBK', '기업', 'SC', 'SC제일', '씨티', '새마을',
    '새마을금고', 'MG', '우체국', '신협', '수협', '산업', 'KDB', '광주', '전북', '경남', '부산', '대구', '제주', 'BNK', 'DGB',
    '삼성', '현대', '롯데', 'BC', '비씨', '토스', 'toss', 'Toss', '카카오페이', '네이버페이', 'Npay', 'N페이', '페이코', 'PAYCO',
    '삼성페이', '토스페이', '애플페이', '제로페이', '페이북', 'SOL', 'KB Pay', 'KBPay', '스마일페이', 'SSGPAY', 'SSG페이',
    '카카오뱅크', '토스뱅크', '케이뱅크', '하나머니', '카카오페이머니', '네이버페이머니', '페이머니', '머니',
}
_VERB_TAIL = re.compile(r'(습니다|니다|어요|아요|해요|돼요|세요|었음|됨)[.!~?]*$')
_HALBU = re.compile(r'^(?:할부)?\d*개월$|^할부\S*$')
_COUNTERPARTY = re.compile(r'^(.+?)님(?:이|께서|으로부터|에게서)$')   # 보낸 사람: 홍길동님이
_RECIPIENT = re.compile(r'^(.+?)님(?:에게|께)$')                     # 받는 사람: 홍길동님에게
_SALUTATION = re.compile(r'^.+님[,!.]*$|^.+고객님')                   # 홍길동님, (인사말)
_CORP = re.compile(r'\(주\)|㈜|주식회사|\(유\)|유한회사')


def _normalize(title, text):
    full = '\n'.join(s for s in ((title or '').strip(), (text or '').strip()) if s)
    full = unicodedata.normalize('NFKC', full).replace('\r', '')
    full = re.sub(r'[​-‏⁠﻿]', '', full)
    full = re.sub(r'^[ \t]*[■□▶▷●○◆◇※•·\-*>]+[ \t]*', '', full, flags=re.M)  # 글머리표
    full = re.sub(r'[ \t ]+', ' ', full)
    full = re.sub(r'\n\s*\n+', '\n', full)
    return full.strip()[:MAX_RAW_LEN]


def _to_int(s):
    return int(s.replace(',', ''))


def _krw_in(s):
    m = _KRW.search(s)
    if m:
        return _to_int(m.group(1) or m.group(2))
    m = re.fullmatch(rf'\s*({_NUM})\s*', s)
    return _to_int(m.group(1)) if m else None


def _parse_kv(full):
    kv = {'amount': None, 'merchant': None, 'datetime': None, 'type': None}
    for line in full.split('\n'):
        m = _KV_LINE.match(line)
        if not m:
            continue
        key, value = m.group(1).replace(' ', ''), m.group(2).strip()
        if kv['amount'] is None and any(k in key for k in _KV_AMOUNT) and not any(k in key for k in _KV_AMOUNT_NOT):
            kv['amount'] = _krw_in(value)
        elif kv['merchant'] is None and any(k in key for k in _KV_MERCHANT):
            kv['merchant'] = value
        elif kv['datetime'] is None and any(k in key for k in _KV_DATETIME):
            kv['datetime'] = value
        elif kv['type'] is None and key in _KV_TYPE:
            kv['type'] = value
    return kv


def _amount_candidates(full):
    """(위치, 금액, 점수) 목록. 거래 단어(승인/결제/입금 등)와 붙어 있을수록 점수가 높다."""
    out = []
    for m in _KRW.finditer(full):
        out.append((m.start(), m.end(), _to_int(m.group(1) or m.group(2))))
    for m in _BARE_AFTER_KEYWORD.finditer(full):
        out.append((m.start(1), m.end(1), _to_int(m.group(1))))
    scored = []
    for start, end, n in out:
        line_start = full.rfind('\n', 0, start) + 1
        before = full[max(line_start, start - 12):start]
        after = full[end:end + 8]
        if n <= 0 or _EXCLUDE_BEFORE.search(before) or _EXCLUDE_AFTER.search(after):
            continue
        near = full[max(0, start - 8):end + 8]
        scored.append((start, n, 1 if _TX_WORDS.search(near) else 0))
    return scored


def _pick_amount(full):
    cands = _amount_candidates(full)
    if not cands:
        return None, None
    best = max(cands, key=lambda c: (c[2], -c[0]))
    return best[1], best[0]


def _pick_foreign(full):
    m = _FOREIGN.search(full)
    if not m:
        return None
    cur, num = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return f'{cur} {num}'


def _tx_type(full, kv_type, amount_pos):
    if kv_type:
        if _REFUND.search(kv_type):
            return '수입', True
        if _INCOME_WORDS.search(kv_type):
            return '수입', False
        if _EXPENSE_WORDS.search(kv_type):
            return '지출', False
    if _REFUND.search(full):
        return '수입', True
    # 송금 문장: '홍길동님이 ... 보냈어요' = 받음, '홍길동님에게 ... 보냈어요' = 보냄
    if re.search(r'님(?:이|께서)\s.*(?:보냈|보내셨|송금했|입금했)', full):
        return '수입', False
    if re.search(r'님(?:에게|께)\s.*(?:보냈|송금|이체)', full):
        return '지출', False
    # 금액과 가장 가까운 입금/출금 단어로 판단 (동점이면 지출)
    pos = amount_pos if amount_pos is not None else 0
    dist = lambda rx: min((abs(m.start() - pos) for m in rx.finditer(full)), default=10 ** 6)
    return ('수입' if dist(_INCOME_WORDS) < dist(_EXPENSE_WORDS) else '지출'), False


def _valid_dt(y, mo, d, h, mi):
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        return None


def _pick_datetime(s, posted_at):
    for i, rx in enumerate(_DT_PATTERNS):
        for m in rx.finditer(s):
            g = m.groupdict()
            has_date = g.get('mo') is not None
            has_time = g.get('h') is not None
            y = int(g['y']) if g.get('y') else posted_at.year
            mo = int(g['mo']) if has_date else posted_at.month
            d = int(g['d']) if has_date else posted_at.day
            h = int(g['h']) if has_time else posted_at.hour
            mi = int(g['mi']) if has_time and g.get('mi') else (0 if has_time else posted_at.minute)
            if g.get('ap') == '오후' and h < 12:
                h += 12
            elif g.get('ap') == '오전' and h == 12:
                h = 0
            dt = _valid_dt(y, mo, d, h, mi)
            if not dt:
                continue
            if not g.get('y') and has_date and dt > posted_at + timedelta(days=1):
                dt = dt.replace(year=dt.year - 1)  # 1월 초에 받은 12월 31일 문자
            if not has_date and dt > posted_at + timedelta(minutes=5):
                dt -= timedelta(days=1)  # 자정 직후에 받은 전날 밤 결제
            return dt
    return posted_at


def _clean_merchant(s):
    s = _CORP.sub(' ', s or '')
    s = re.sub(r'\s+', ' ', s).strip(' ,.:;|/-')
    return s[:MAX_TITLE_LEN]


def _clean_token(tok):
    tok = tok.strip(' ,.:;|/·-~!?"\'')
    if not tok or re.fullmatch(r'[\d,.%]+', tok):
        return ''
    if tok in _NOISE_WORDS or tok in _BRAND_WORDS or _VERB_TAIL.search(tok) or _HALBU.match(tok):
        return ''
    for rx in (_COUNTERPARTY, _RECIPIENT):
        m = rx.match(tok)
        if m:
            return m.group(1)
    if _SALUTATION.match(tok):
        return ''
    if len(tok) > 3:
        tok = re.sub(r'(에서|으로|에게|에서의)$', '', tok)
    tok = re.sub(r'(원|님)$', '', tok) if re.search(r'\d(원)$', tok) else tok
    return '' if tok in _NOISE_WORDS or tok in _BRAND_WORDS else tok


# 카드사/은행 낱말(신한카드1234승인, 토스뱅크 등)은 지우되 '카드대금', '통신요금' 같은 거래 내용은 남긴다
_ISSUER_TOKEN = re.compile(r'\S*(?:카드|은행|뱅크|뱅킹|BANK|Bank|bank|체크)\S*')
_KEEP_ISSUER = re.compile(r'대금|요금|수수료|보험|연회비|이자')


def _fragments(s):
    for p in _NOISE_PATTERNS:
        s = p.sub('\n', s)
    s = _ISSUER_TOKEN.sub(lambda m: m.group(0) if _KEEP_ISSUER.search(m.group(0)) else '\n', s)
    frags = []
    for line in s.split('\n'):
        raw = line.split()
        words = [w for w in (_clean_token(t) for t in raw) if w]
        if words:
            frags.append((raw, words))
    return frags


def _pick_title(full, tx_type):
    # 1) 'A → B' 송금/이체: 들어온 돈이면 A(보낸 사람), 나간 돈이면 B(받는 쪽)
    for line in full.split('\n'):
        parts = re.split(r'→|->|▶|▷|►', line)
        if len(parts) == 2:
            side = parts[0] if tx_type == '수입' else parts[1]
            frags = _fragments(side)
            if frags:
                return _clean_merchant(' '.join(frags[-1][1]))
    # 2) 송금 문장의 상대방: '홍길동님이 보냈어요', '홍길동님에게 보냈어요'
    for tok in full.split():
        m = _COUNTERPARTY.match(tok.strip(' ,.')) or _RECIPIENT.match(tok.strip(' ,.'))
        if m and '*' not in m.group(1):
            return _clean_merchant(m.group(1))
    frags = _fragments(full)
    if not frags:
        return ''
    # 3) '스타벅스 강남점에서 12,000원 결제' 처럼 '~에서' 가 붙은 말
    for raw, _ in frags:
        for i, t in enumerate(raw):
            t = t.strip(' ,.')
            if len(t) > 2 and t.endswith('에서'):
                words = [w for w in (_clean_token(x) for x in raw[:i]) if w] + [t[:-2]]
                return _clean_merchant(' '.join(words))
    # 4) 카드/은행 문자는 대개 가맹점(상대방)이 맨 뒤에 온다
    return _clean_merchant(' '.join(frags[-1][1]))


def parse_notification(title, text, posted_at=None):
    """알림 제목/본문에서 {'tx_type','amount','title','datetime'} 을 뽑는다. 거래 알림이 아니면 None.
    원화 금액을 알 수 없는 해외 결제는 amount=0 (사용자가 금액을 입력)."""
    posted_at = posted_at or datetime.now()
    full = _normalize(title, text)
    # 거래 단어가 없어도 '₩4,800 | 이디야커피' 처럼 원화 기호가 붙은 금액이면 결제 알림으로 본다
    if not full or _REJECT.search(full) or not (_TX_WORDS.search(full) or re.search(r'₩\s*\d', full)):
        return None

    kv = _parse_kv(full)
    amount, pos = (kv['amount'], None) if kv['amount'] else _pick_amount(full)
    foreign = None
    if amount is None:
        foreign = _pick_foreign(full)
        if not foreign:
            return None
        amount = 0

    tx_type, refund = _tx_type(full, kv['type'], pos)
    merchant = _clean_merchant(kv['merchant']) if kv['merchant'] else _pick_title(full, tx_type)
    if foreign:
        merchant = f'{merchant} ({foreign})'.strip() if merchant else f'해외결제 ({foreign})'
    if refund and merchant:
        merchant = f'{merchant} (취소)'
    dt = _pick_datetime(kv['datetime'], posted_at) if kv['datetime'] else None
    if dt is None or dt == posted_at:
        dt = _pick_datetime(full, posted_at)
    return {
        'tx_type': tx_type,
        'amount': amount,
        'title': merchant[:MAX_TITLE_LEN],
        'datetime': dt,
    }
