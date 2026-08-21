import csv
import io
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, Response

from models import db, User, Ledger, Category, Transaction
from helpers import spa_redirect

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings')
def settings():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    categories = Category.query.filter_by(ledger_id=ledger.id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return render_template('settings.html', ledger=ledger, current_user=user, categories=categories, current_tab='settings')


@settings_bp.route('/mypage')
def mypage():
    user = User.query.get(request.user_id)
    if not user: return spa_redirect(url_for('auth.logout'))
    if not user.ledger_id: return redirect(url_for('auth.onboarding'))
    ledger = Ledger.query.get(user.ledger_id)
    return render_template('mypage.html', ledger=ledger, current_user=user, current_tab='settings')


@settings_bp.route('/update_nickname', methods=['POST'])
def update_nickname():
    user = User.query.get(request.user_id)
    new_nickname = request.form.get('nickname')
    update_past = request.form.get('update_past') == 'on'

    if new_nickname:
        old_nickname = user.nickname
        user.nickname = new_nickname
        if update_past:
            Transaction.query.filter_by(ledger_id=user.ledger_id, transactor=old_nickname).update({'transactor': new_nickname})
        db.session.commit()
    return spa_redirect(url_for('settings.settings'))


@settings_bp.route('/update_ledger_name', methods=['POST'])
def update_ledger_name():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    new_name = request.form.get('name')
    if new_name:
        ledger.name = new_name
        db.session.commit()
    return spa_redirect(url_for('settings.settings'))


@settings_bp.route('/set_budget', methods=['POST'])
def set_budget():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)

    tb_str = request.form.get('total_budget', '').replace(',', '')
    ledger.monthly_budget = int(tb_str) if tb_str.isdigit() else 0

    for key, val in request.form.items():
        if key.startswith('cat_budget_'):
            cat_id = int(key.replace('cat_budget_', ''))
            cat = Category.query.get(cat_id)
            if cat and cat.ledger_id == ledger.id and cat.name != '미분류':
                val_str = val.replace(',', '') if val else ''
                cat.budget = int(val_str) if val_str.isdigit() else 0

    db.session.commit()
    return spa_redirect(url_for('settings.settings'))


@settings_bp.route('/api/categories', methods=['GET'])
def api_get_categories():
    user = User.query.get(request.user_id)
    cats = Category.query.filter_by(ledger_id=user.ledger_id).order_by(Category.sort_order.asc(), Category.id.asc()).all()
    return jsonify([{'id': c.id, 'name': c.name, 'is_default': c.is_default} for c in cats])


@settings_bp.route('/api/category/add', methods=['POST'])
def api_add_category():
    user = User.query.get(request.user_id)
    name = request.json.get('name')
    if name:
        max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=user.ledger_id).scalar() or 0
        db.session.add(Category(ledger_id=user.ledger_id, name=name, sort_order=max_order + 1))
        db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/api/category/<int:cat_id>/edit', methods=['POST'])
def api_edit_category(cat_id):
    user = User.query.get(request.user_id)
    cat = Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first()
    name = request.json.get('name')
    if cat and name and cat.name != '미분류':
        cat.name = name
        db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/api/category/<int:cat_id>/delete', methods=['POST'])
def api_delete_category(cat_id):
    user = User.query.get(request.user_id)
    cat = Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first()
    if cat and cat.name != '미분류':
        db.session.delete(cat)
        db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/api/category/<int:cat_id>/move', methods=['POST'])
def api_move_category(cat_id):
    user = User.query.get(request.user_id)
    direction = request.json.get('dir')
    cat = Category.query.filter_by(id=cat_id, ledger_id=user.ledger_id).first()
    if not cat or cat.name == '미분류': return jsonify({'success': False})

    cats = Category.query.filter(Category.ledger_id==user.ledger_id, Category.name!='미분류').order_by(Category.sort_order.asc(), Category.id.asc()).all()
    if cat not in cats: return jsonify({'success': False})

    idx = cats.index(cat)

    if direction == 'up' and idx > 0:
        cats[idx].sort_order, cats[idx-1].sort_order = cats[idx-1].sort_order, cats[idx].sort_order
    elif direction == 'down' and idx < len(cats) - 1:
        cats[idx].sort_order, cats[idx+1].sort_order = cats[idx+1].sort_order, cats[idx].sort_order

    db.session.commit()
    return jsonify({'success': True})


@settings_bp.route('/export')
def export_csv():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    transactions = Transaction.query.filter_by(ledger_id=user.ledger_id).order_by(Transaction.datetime_val.desc()).all()
    categories = Category.query.filter_by(ledger_id=user.ledger_id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(['#LEDGER_META', ledger.name, ledger.monthly_budget])
    writer.writerow(['#CATEGORY_META', 'name', 'is_default', 'budget', 'sort_order'])
    for cat in categories:
        writer.writerow(['#CATEGORY_ROW', cat.name, int(cat.is_default), cat.budget, cat.sort_order])

    writer.writerow(['#TX_META', 'date', 'time', 'tx_type', 'transactor', 'category', 'title', 'memo', 'amount', 'exclude_analysis', 'nickname', 'exclude_budget'])
    for tx in transactions:
        writer.writerow(['#TX_ROW', tx.datetime_val.strftime('%Y-%m-%d'), tx.datetime_val.strftime('%H:%M'),
                         tx.tx_type, tx.transactor, tx.category.name, tx.title, tx.memo, tx.amount, int(tx.exclude_analysis), tx.user.nickname, int(tx.exclude_budget)])

    csv_data = output.getvalue().encode('utf-8-sig')
    response = Response(csv_data, mimetype="application/octet-stream")
    response.headers["Content-Disposition"] = 'attachment; filename="ledger.csv"'
    return response


def _resolve_category_id(ledger_id, name, cache):
    if name in cache:
        return cache[name]
    cat = Category.query.filter_by(ledger_id=ledger_id, name=name).first()
    if not cat:
        max_order = db.session.query(db.func.max(Category.sort_order)).filter_by(ledger_id=ledger_id).scalar() or 0
        cat = Category(ledger_id=ledger_id, name=name, is_default=False, sort_order=max_order + 1)
        db.session.add(cat)
        db.session.flush()
    cache[name] = cat.id
    return cache[name]


@settings_bp.route('/import', methods=['POST'])
def import_csv():
    user = User.query.get(request.user_id)
    ledger = Ledger.query.get(user.ledger_id)
    file = request.files.get('csv_file')

    if file:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
        reader = csv.reader(stream)

        cats_cache = {}
        for row in reader:
            if not row: continue

            if row[0] == '#LEDGER_META' and len(row) >= 3:
                ledger.name = row[1]
                ledger.monthly_budget = int(row[2])
            elif row[0] == '#CATEGORY_ROW' and len(row) >= 5:
                cat = Category.query.filter_by(ledger_id=user.ledger_id, name=row[1]).first()
                if not cat:
                    cat = Category(ledger_id=user.ledger_id, name=row[1])
                    db.session.add(cat)
                cat.is_default = bool(int(row[2]))
                cat.budget = int(row[3])
                cat.sort_order = int(row[4])
                db.session.flush()
                cats_cache[cat.name] = cat.id
            elif row[0] == '#TX_ROW' and len(row) >= 11:
                cat_id = _resolve_category_id(user.ledger_id, row[5], cats_cache)
                dt = datetime.strptime(f"{row[1]} {row[2]}", "%Y-%m-%d %H:%M")
                # exclude_budget은 이후에 추가된 컬럼이라 예전 백업 파일엔 없을 수 있다 (그때는 False로 취급)
                exclude_budget = bool(int(row[11])) if len(row) >= 12 else False
                new_tx = Transaction(ledger_id=user.ledger_id, user_id=user.id, tx_type=row[3], transactor=row[4], title=row[6], memo=row[7], amount=int(row[8]), exclude_analysis=bool(int(row[9])), exclude_budget=exclude_budget, category_id=cat_id, datetime_val=dt)
                db.session.add(new_tx)
            elif not row[0].startswith('#') and len(row) >= 8 and row[0] != '일자':
                cat_id = _resolve_category_id(user.ledger_id, row[4], cats_cache)
                dt = datetime.strptime(f"{row[0]} {row[1]}", "%Y-%m-%d %H:%M")
                new_tx = Transaction(ledger_id=user.ledger_id, user_id=user.id, tx_type=row[2], transactor=row[3], title=row[5], memo=row[6], amount=int(row[7]), category_id=cat_id, datetime_val=dt)
                db.session.add(new_tx)

        db.session.commit()
    return spa_redirect(url_for('settings.mypage'))
