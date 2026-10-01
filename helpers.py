import random
from datetime import datetime
from functools import wraps
from flask import request, redirect, jsonify, url_for, g
from models import db, User, Ledger, Category

# 사용자/'함께'/분류에 배정되는 색상 풀 (차트에서 사람·분류를 구분하는 색).
# 색약(CVD) 구분도와 명도 대역을 검증한 8색 팔레트이며, 다크 모드에서는 화면 쪽에서
# 같은 슬롯의 다크용 색(static 쪽 SERIES_DARK)으로 바꿔 그린다.
COLOR_PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
FALLBACK_COLOR = '#8b909c'

# 예전 10색 팔레트로 이미 저장된 색 -> 새 팔레트의 비슷한 색. DB 값은 그대로 두고 화면에 낼 때만 바꾼다.
LEGACY_COLOR_MAP = {
    '#22b57f': '#008300', '#f0a94e': '#eda100', '#3fadd6': '#2a78d6', '#c876c2': '#e87ba4',
    '#eb7a6e': '#eb6834', '#f0cb5c': '#eda100', '#8f79d6': '#4a3aa7', '#4fc2d6': '#2a78d6',
    '#e0a0d6': '#e87ba4', '#4fbfa0': '#1baf7a',
}


def norm_color(color, fallback=FALLBACK_COLOR):
    """저장된 색을 현재 팔레트 색으로. 예전 팔레트 색은 대응 색으로, 알 수 없는 값은 fallback."""
    c = (color or '').strip().lower()
    if c in COLOR_PALETTE:
        return c
    return LEGACY_COLOR_MAP.get(c, fallback)

TX_TYPES = ('수입', '지출')
TOGETHER = '함께'
UNCATEGORIZED = '미분류'

# 입력 길이 제한 (DB 컬럼 길이와 맞춤. 넘치면 PostgreSQL 이 오류를 내므로 서버에서 잘라낸다)
MAX_TITLE_LEN = 100
MAX_MEMO_LEN = 255
MAX_CATEGORY_NAME_LEN = 50
MAX_LEDGER_NAME_LEN = 100
MAX_NICKNAME_LEN = 50  # 내역의 transactor 컬럼(50자)에 그대로 들어가므로 50자로 제한
# 금액/예산 상한 (BIGINT 범위 및 JS Number 안전 범위 안쪽, 1조원 미만)
MAX_AMOUNT = 999_999_999_999


def pick_random_color(existing_colors):
    existing = {norm_color(c, None) for c in existing_colors}
    unused = [c for c in COLOR_PALETTE if c not in existing]
    pool = unused if unused else COLOR_PALETTE
    return random.choice(pool)


def is_ajax():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.form.get('ajax') == '1'


def wants_json():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept') == 'application/json'


def spa_redirect(target_url):
    if is_ajax():
        return jsonify({'redirect': target_url})
    return redirect(target_url)


def json_error(message, status=400):
    return jsonify({'success': False, 'error': message}), status


def clean_text(value, max_len):
    """앞뒤 공백 제거 후 최대 길이로 자른다. None 은 빈 문자열."""
    return (value or '').strip()[:max_len]


def parse_amount(value):
    """'1,234' 같은 금액 문자열을 정수로. 숫자가 아니거나 범위를 넘으면 None."""
    s = (value or '').replace(',', '').strip()
    if not s.isdigit():
        return None
    n = int(s)
    return n if n <= MAX_AMOUNT else None


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_year_month(year, month):
    """유효한 (연, 월)이면 정수 튜플, 아니면 None."""
    y, m = parse_int(year), parse_int(month)
    if y is None or m is None or not (1900 <= y <= 2999) or not (1 <= m <= 12):
        return None
    return y, m


def parse_datetime(date_str, time_str):
    """'YYYY-MM-DD', 'HH:MM' -> datetime. 시간이 비어 있으면 현재 시각, 형식이 틀리면 None."""
    time_str = (time_str or '').strip() or datetime.now().strftime('%H:%M')
    try:
        return datetime.strptime(f"{(date_str or '').strip()} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def safe_next_url(url, default):
    """같은 사이트 안의 경로만 허용 (외부 주소/javascript: 로의 이동 방지)."""
    if url and url.startswith('/') and not url.startswith('//') and '\\' not in url:
        return url
    return default


def get_target_date():
    now = datetime.now()
    ym = parse_year_month(request.args.get('year'), request.args.get('month'))
    target_year, target_month = ym if ym else (now.year, now.month)

    p_m = target_month - 1 if target_month > 1 else 12
    p_y = target_year if target_month > 1 else target_year - 1
    n_m = target_month + 1 if target_month < 12 else 1
    n_y = target_year if target_month < 12 else target_year + 1

    return target_year, target_month, p_y, p_m, n_y, n_m


def get_kakao_redirect_uri():
    return f"{request.host_url.rstrip('/')}/oauth/kakao/callback"


def month_range(year, month):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def get_or_create_uncategorized(ledger_id):
    cat = Category.query.filter_by(ledger_id=ledger_id, name=UNCATEGORIZED).first()
    if not cat:
        existing_colors = [c.color for c in Category.query.filter_by(ledger_id=ledger_id).all() if c.color]
        cat = Category(ledger_id=ledger_id, name=UNCATEGORIZED, is_default=True, sort_order=-1, color=pick_random_color(existing_colors))
        db.session.add(cat)
        db.session.flush()
    return cat.id


def require_ledger(view):
    """로그인 사용자와 그 사용자의 가계부를 g.user / g.ledger 로 준비한다.
    사용자가 없으면 로그아웃, 가계부가 없으면 온보딩으로 보낸다 (API 요청이면 JSON 오류)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        is_api = request.path.startswith('/api/')
        user = db.session.get(User, request.user_id)
        if not user:
            if is_api:
                return json_error('Unauthorized', 401)
            return _redirect_for_method(url_for('auth.logout'))
        ledger = db.session.get(Ledger, user.ledger_id) if user.ledger_id else None
        if not ledger:
            if is_api:
                return json_error('참여 중인 가계부가 없습니다.', 400)
            return _redirect_for_method(url_for('auth.onboarding'))
        g.user, g.ledger = user, ledger
        return view(*args, **kwargs)
    return wrapper


def _redirect_for_method(target_url):
    # 화면 이동(GET)은 SPA 가 응답 HTML 을 그대로 그리므로 일반 리다이렉트,
    # 폼 제출(POST)은 SPA 가 {'redirect': ...} JSON 을 받아 이동한다.
    if request.method == 'GET':
        return redirect(target_url)
    return spa_redirect(target_url)


def resolve_transactor(ledger, value, actor):
    """폼에서 받은 거래자 값(닉네임 또는 '함께')을 (표시 이름, 사용자 id)로 바꾼다.
    값이 비어 있으면 등록하는 본인으로 본다. 현재 참여자와 일치하지 않는 이름은
    (예전 데이터 수정 등) 그대로 두되 사용자 id 는 비운다."""
    value = clean_text(value, MAX_NICKNAME_LEN)
    if not value:
        return actor.nickname[:MAX_NICKNAME_LEN], actor.id
    if value == TOGETHER:
        return TOGETHER, None
    for u in ledger.users:
        if u.nickname == value:
            return u.nickname[:MAX_NICKNAME_LEN], u.id
    return value, None


class TransactorInfo:
    """내역의 거래자를 화면용 이름/색상/집계 키로 풀어주는 도우미 (가계부 단위로 한 번 만든다)."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.by_id = {u.id: u for u in ledger.users}
        self.by_nickname = {}
        for u in ledger.users:
            self.by_nickname.setdefault(u.nickname, u)

    def member(self, tx):
        if tx.transactor == TOGETHER:
            return None
        if tx.transactor_user_id is not None:
            # 가계부를 나간 사용자를 가리키면 None (이름 문자열로 대체 표시)
            return self.by_id.get(tx.transactor_user_id)
        return self.by_nickname.get(tx.transactor)

    def color(self, tx):
        if tx.transactor == TOGETHER:
            return norm_color(self.ledger.together_color)
        u = self.member(tx)
        return norm_color(u.color if u else None)

    def key(self, tx):
        """참여자별 집계에 쓰는 이름: 현재 참여자면 현재 닉네임으로 묶는다."""
        if tx.transactor == TOGETHER:
            return TOGETHER
        u = self.member(tx)
        return u.nickname if u else tx.transactor

    def form_value(self, tx):
        """수정 시트의 거래자 버튼(현재 닉네임 기준)을 맞게 선택하기 위한 값."""
        return self.key(tx)


def serialize_tx(tx, tinfo):
    """화면(목록/달력/홈/수정 시트)에서 공통으로 쓰는 내역 JSON."""
    cat = tx.category
    return {
        'id': tx.id, 'tx_type': tx.tx_type,
        'date': tx.datetime_val.strftime('%Y-%m-%d'), 'time': tx.datetime_val.strftime('%H:%M'),
        'title': tx.title, 'memo': tx.memo or '', 'amount': tx.amount,
        'category': cat.name if cat else UNCATEGORIZED, 'category_id': tx.category_id,
        'category_color': norm_color(cat.color if cat else None),
        'transactor': tx.transactor, 'transactor_color': tinfo.color(tx),
        'transactor_value': tinfo.form_value(tx),
        'exclude_analysis': bool(tx.exclude_analysis), 'exclude_budget': bool(tx.exclude_budget),
    }
