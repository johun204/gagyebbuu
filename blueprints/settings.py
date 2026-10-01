import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, url_for, jsonify, Response, g
from sqlalchemy import or_

from models import db, Category, Transaction
from helpers import (spa_redirect, COLOR_PALETTE, norm_color, pick_random_color, require_ledger, json_error, clean_text,
                     parse_amount, parse_int, parse_datetime, resolve_transactor, get_or_create_uncategorized,
                     TX_TYPES, TOGETHER, UNCATEGORIZED, MAX_NICKNAME_LEN, MAX_LEDGER_NAME_LEN,
                     MAX_CATEGORY_NAME_LEN, MAX_TITLE_LEN, MAX_MEMO_LEN)

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings')
@require_ledger
def settings():
    ledger = g.ledger
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return render_template('settings.html', ledger=ledger, current_user=g.user, categories=categories, current_tab='settings')


@settings_bp.route('/mypage')
@require_ledger
def mypage():
    return render_template('mypage.html', ledger=g.ledger, current_user=g.user, current_tab='settings',
                           msg=request.args.get('msg', ''),
                           imported=parse_int(request.args.get('imported')),
                           skipped_dup=parse_int(request.args.get('skipped_dup')),
                           skipped_bad=parse_int(request.args.get('skipped_bad')))


@settings_bp.route('/update_nickname', methods=['POST'])
@require_ledger
def update_nickname():
    user, ledger = g.user, g.ledger
    new_nickname = clean_text(request.form.get('nickname'), MAX_NICKNAME_LEN)
    update_past = request.form.get('update_past') == 'on'

    if not new_nickname:
        return spa_redirect(url_for('settings.mypage', msg='nickname_empty'))
    if new_nickname == TOGETHER or any(u.nickname == new_nickname for u in ledger.users if u.id != user.id):
        return spa_redirect(url_for('settings.mypage', msg='nickname_taken'))

    old_nickname = user.nickname
    if new_nickname != old_nickname:
        user.nickname = new_nickname
        if update_past:
            # 내 이름으로 기록된 내역만 바꾼다 (사용자 id 로 연결된 것 + 예전 방식으로 이름만 남은 것)
            Transaction.query.filter(
                Transaction.ledger_id == ledger.id,
                Transaction.transactor == old_nickname,
                or_(Transaction.transactor_user_id == user.id, Transaction.transactor_user_id.is_(None)),
            ).update({'transactor': new_nickname, 'transactor_user_id': user.id}, synchronize_session=False)
        db.session.commit()
    return spa_redirect(url_for('settings.settings'))


@settings_bp.route('/update_color', methods=['POST'])
@require_ledger
def update_color():
    color = request.form.get('color')
    if color not in COLOR_PALETTE:
        return json_error('지원하지 않는 색상입니다.')
    g.user.color = color
    db.session.commit()
    return spa_redirect(url_for('settings.mypage'))


@settings_bp.route('/update_together_color', methods=['POST'])
@require_ledger
def update_together_color():
    color = request.form.get('color')
    if color not in COLOR_PALETTE:
        return json_error('지원하지 않는 색상입니다.')
    g.ledger.together_color = color
    db.session.commit()
    return spa_redirect(url_for('settings.mypage'))


@settings_bp.route('/update_ledger_name', methods=['POST'])
@require_ledger
def update_ledger_name():
    new_name = clean_text(request.form.get('name'), MAX_LEDGER_NAME_LEN)
    if new_name:
        g.ledger.name = new_name
        db.session.commit()
    return spa_redirect(url_for('settings.settings'))


@settings_bp.route('/set_budget', methods=['POST'])
@require_ledger
def set_budget():
    ledger = g.ledger
    ledger.monthly_budget = parse_amount(request.form.get('total_budget')) or 0

    cats = {c.id: c for c in Category.query.filter_by(ledger_id=ledger.id).all()}
    for key, val in request.form.items():
        if key.startswith('cat_budget_'):
            cat = cats.get(parse_int(key[len('cat_budget_'):]))
            if cat and cat.name != UNCATEGORIZED:
                cat.budget = parse_amount(val) or 0

    db.session.commit()
    return spa_redirect(url_for('settings.settings', saved='budget'))


def _category_name_error(ledger_id, name, exclude_id=None):
    if not name:
        return '분류 이름을 입력해주세요.'
    if name == UNCATEGORIZED:
        return f"'{UNCATEGORIZED}'는 사용할 수 없는 이름입니다."
    q = Category.query.filter(Category.ledger_id == ledger_id, Category.name == name)
    if exclude_id is not None:
        q = q.filter(Category.id != exclude_id)
    if q.first():
        return '이미 같은 이름의 분류가 있습니다.'
    return None


@settings_bp.route('/api/categories', methods=['GET'])
@require_ledger
def api_get_categories():
    cats = Category.query.filter_by(ledger_id=g.ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return jsonify([{'id': c.id, 'name': c.name, 'is_default': c.is_default, 'color': norm_color(c.color)} for c in cats])


@settings_bp.route('/api/category/add', methods=['POST'])
@require_ledger
def api_add_category():
    ledger_id = g.ledger.id
    name = clean_text((request.get_json(silent=True) or {}).get('name'), MAX_CATEGORY_NAME_LEN)
    err = _category_name_error(ledger_id, name)
    if err:
        return json_error(err)
    max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=ledger_id).scalar() or 0
    existing_colors = [c.color for c in Category.query.filter_by(ledger_id=ledger_id).all() if c.color]
    db.session.add(Category(ledger_id=ledger_id, name=name, sort_order=max_order + 1, color=pick_random_color(existing_colors)))
    db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/api/category/<int:cat_id>/edit', methods=['POST'])
@require_ledger
def api_edit_category(cat_id):
    ledger_id = g.ledger.id
    cat = Category.query.filter_by(id=cat_id, ledger_id=ledger_id).first()
    if not cat or cat.name == UNCATEGORIZED:
        return json_error('수정할 수 없는 분류입니다.', 404)
    name = clean_text((request.get_json(silent=True) or {}).get('name'), MAX_CATEGORY_NAME_LEN)
    if name != cat.name:
        err = _category_name_error(ledger_id, name, exclude_id=cat.id)
        if err:
            return json_error(err)
        cat.name = name
        db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/api/category/<int:cat_id>/set_color', methods=['POST'])
@require_ledger
def api_set_category_color(cat_id):
    cat = Category.query.filter_by(id=cat_id, ledger_id=g.ledger.id).first()
    color = (request.get_json(silent=True) or {}).get('color')
    if not cat or color not in COLOR_PALETTE:
        return json_error('색상을 변경할 수 없습니다.')
    cat.color = color
    db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/api/category/<int:cat_id>/delete', methods=['POST'])
@require_ledger
def api_delete_category(cat_id):
    ledger_id = g.ledger.id
    cat = Category.query.filter_by(id=cat_id, ledger_id=ledger_id).first()
    if not cat or cat.name == UNCATEGORIZED:
        return json_error('삭제할 수 없는 분류입니다.', 404)
    # 이 분류를 쓰던 내역은 지우지 않고 '미분류'로 옮긴 뒤 분류만 삭제한다.
    uncat_id = get_or_create_uncategorized(ledger_id)
    moved = Transaction.query.filter_by(ledger_id=ledger_id, category_id=cat.id) \
        .update({'category_id': uncat_id}, synchronize_session=False)
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'success': True, 'moved': moved})


@settings_bp.route('/api/category/<int:cat_id>/move', methods=['POST'])
@require_ledger
def api_move_category(cat_id):
    ledger_id = g.ledger.id
    direction = (request.get_json(silent=True) or {}).get('dir')
    cat = Category.query.filter_by(id=cat_id, ledger_id=ledger_id).first()
    if not cat or cat.name == UNCATEGORIZED: return jsonify({'success': False})

    cats = Category.query.filter(Category.ledger_id == ledger_id, Category.name != UNCATEGORIZED).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    # 예전 데이터에 sort_order 가 겹친 분류가 있으면 자리 바꾸기가 먹지 않으므로 먼저 번호를 정리한다.
    for i, c in enumerate(cats):
        c.sort_order = i + 1
    idx = cats.index(cat)

    if direction == 'up' and idx > 0:
        cats[idx].sort_order, cats[idx-1].sort_order = cats[idx-1].sort_order, cats[idx].sort_order
    elif direction == 'down' and idx < len(cats) - 1:
        cats[idx].sort_order, cats[idx+1].sort_order = cats[idx+1].sort_order, cats[idx].sort_order

    db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/export')
@require_ledger
def export_csv():
    ledger = g.ledger
    transactions = Transaction.query.filter_by(ledger_id=ledger.id).order_by(Transaction.datetime_val.desc(), Transaction.id.desc()).all()
    categories = Category.query.filter_by(ledger_id=ledger.id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(['#LEDGER_META', ledger.name, ledger.monthly_budget or 0])
    writer.writerow(['#CATEGORY_META', 'name', 'is_default', 'budget', 'sort_order', 'color'])
    for cat in categories:
        writer.writerow(['#CATEGORY_ROW', cat.name, int(bool(cat.is_default)), cat.budget or 0, cat.sort_order or 0, cat.color or ''])

    writer.writerow(['#TX_META', 'date', 'time', 'tx_type', 'transactor', 'category', 'title', 'memo', 'amount', 'exclude_analysis', 'nickname', 'exclude_budget'])
    for tx in transactions:
        writer.writerow(['#TX_ROW', tx.datetime_val.strftime('%Y-%m-%d'), tx.datetime_val.strftime('%H:%M'),
                         tx.tx_type, tx.transactor, tx.category.name, tx.title, tx.memo or '', tx.amount,
                         int(bool(tx.exclude_analysis)), tx.user.nickname, int(bool(tx.exclude_budget))])

    csv_data = output.getvalue().encode('utf-8-sig')
    response = Response(csv_data, mimetype="application/octet-stream")
    response.headers["Content-Disposition"] = 'attachment; filename="ledger.csv"'
    response.headers["Cache-Control"] = 'no-store'
    return response


def _resolve_category_id(ledger_id, name, cache):
    name = clean_text(name, MAX_CATEGORY_NAME_LEN) or UNCATEGORIZED
    if name in cache:
        return cache[name]
    if name == UNCATEGORIZED:
        cache[name] = get_or_create_uncategorized(ledger_id)
        return cache[name]
    cat = Category.query.filter_by(ledger_id=ledger_id, name=name).first()
    if not cat:
        max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=ledger_id).scalar() or 0
        existing_colors = [c.color for c in Category.query.filter_by(ledger_id=ledger_id).all() if c.color]
        cat = Category(ledger_id=ledger_id, name=name, is_default=False, sort_order=max_order + 1, color=pick_random_color(existing_colors))
        db.session.add(cat)
        db.session.flush()
    cache[name] = cat.id
    return cache[name]


def _flag(value):
    return str(value).strip() in ('1', 'True', 'true')


def _tx_key(dt, tx_type, title, amount, transactor):
    return (dt.strftime('%Y-%m-%d %H:%M'), tx_type, title, amount, transactor)


def _import_tx(user, ledger, cats_cache, existing_keys, date_s, time_s, tx_type, transactor, cat_name, title, memo,
               amount_s, exclude_analysis=False, exclude_budget=False):
    """CSV 내역 한 줄을 검증해 추가한다. 'added' / 'dup' / 'bad' 중 하나를 돌려준다."""
    dt = parse_datetime(date_s, time_s or '00:00')
    amount = parse_amount(amount_s)
    tx_type = (tx_type or '').strip()
    if dt is None or amount is None or tx_type not in TX_TYPES:
        return 'bad'
    title = clean_text(title, MAX_TITLE_LEN)
    transactor_name, transactor_user_id = resolve_transactor(ledger, transactor, user)
    key = _tx_key(dt, tx_type, title, amount, transactor_name)
    if key in existing_keys:
        return 'dup'
    db.session.add(Transaction(
        ledger_id=ledger.id, user_id=user.id, tx_type=tx_type,
        transactor=transactor_name, transactor_user_id=transactor_user_id,
        title=title, memo=clean_text(memo, MAX_MEMO_LEN), amount=amount,
        exclude_analysis=exclude_analysis, exclude_budget=exclude_budget,
        category_id=_resolve_category_id(ledger.id, cat_name, cats_cache), datetime_val=dt))
    return 'added'


@settings_bp.route('/import', methods=['POST'])
@require_ledger
def import_csv():
    user, ledger = g.user, g.ledger
    file = request.files.get('csv_file')
    if not file:
        return spa_redirect(url_for('settings.mypage', msg='import_nofile'))

    try:
        text = file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return spa_redirect(url_for('settings.mypage', msg='import_encoding'))

    # 이미 있는 내역과 똑같은 줄(날짜·시간·구분·제목·금액·거래자 일치)은 건너뛴다 → 같은 파일을 두 번 불러와도 중복되지 않음.
    # 파일 안에서 같은 내용이 여러 줄인 경우(같은 시각에 같은 걸 두 번 산 경우 등)는 모두 추가한다.
    existing_keys = {_tx_key(t.datetime_val, t.tx_type, t.title, t.amount, t.transactor)
                     for t in Transaction.query.filter_by(ledger_id=ledger.id).all()}
    cats_cache = {}
    counts = {'added': 0, 'dup': 0, 'bad': 0}

    try:
        for row in csv.reader(io.StringIO(text, newline=None)):
            if not row or not row[0]:
                continue
            kind = row[0]
            try:
                if kind == '#LEDGER_META' and len(row) >= 3:
                    name = clean_text(row[1], MAX_LEDGER_NAME_LEN)
                    if name:
                        ledger.name = name
                    budget = parse_amount(row[2])
                    if budget is not None:
                        ledger.monthly_budget = budget
                elif kind == '#CATEGORY_ROW' and len(row) >= 5:
                    name = clean_text(row[1], MAX_CATEGORY_NAME_LEN)
                    if not name:
                        continue
                    cat = Category.query.filter_by(ledger_id=ledger.id, name=name).first()
                    is_new = not cat
                    if not cat:
                        cat = Category(ledger_id=ledger.id, name=name)
                        db.session.add(cat)
                    cat.is_default = _flag(row[2])
                    cat.budget = parse_amount(row[3]) or 0
                    cat.sort_order = parse_int(row[4]) or 0
                    # color는 이후에 추가된 컬럼이라 예전 백업 파일엔 없을 수 있다 (그때는 새 분류에만 랜덤 배정)
                    if len(row) >= 6 and norm_color(row[5], None):
                        cat.color = norm_color(row[5])
                    elif is_new:
                        existing_colors = [c.color for c in Category.query.filter_by(ledger_id=ledger.id).all() if c.color]
                        cat.color = pick_random_color(existing_colors)
                    db.session.flush()
                    cats_cache[cat.name] = cat.id
                elif kind == '#TX_ROW' and len(row) >= 11:
                    # exclude_budget은 이후에 추가된 컬럼이라 예전 백업 파일엔 없을 수 있다 (그때는 False로 취급)
                    counts[_import_tx(user, ledger, cats_cache, existing_keys, row[1], row[2], row[3], row[4], row[5],
                                      row[6], row[7], row[8], exclude_analysis=_flag(row[9]),
                                      exclude_budget=_flag(row[11]) if len(row) >= 12 else False)] += 1
                elif not kind.startswith('#') and len(row) >= 8 and kind != '일자':
                    counts[_import_tx(user, ledger, cats_cache, existing_keys, row[0], row[1], row[2], row[3], row[4],
                                      row[5], row[6], row[7])] += 1
            except (ValueError, IndexError):
                counts['bad'] += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        return spa_redirect(url_for('settings.mypage', msg='import_failed'))

    return spa_redirect(url_for('settings.mypage', msg='imported', imported=counts['added'],
                                skipped_dup=counts['dup'], skipped_bad=counts['bad']))
