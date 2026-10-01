from flask import Blueprint, render_template, request, jsonify, g

from analytics import home_data, analysis_data
from helpers import get_target_date, require_ledger, json_error, parse_year_month

home_bp = Blueprint('home', __name__)


@home_bp.route('/')
@home_bp.route('/home')
@require_ledger
def home():
    t_year, t_month, *_ = get_target_date()
    return render_template('home.html', ledger=g.ledger, current_user=g.user,
                           initial_data=home_data(g.ledger, t_year, t_month),
                           t_year=t_year, t_month=t_month, current_tab='home')


@home_bp.route('/api/home_data')
@require_ledger
def api_home_data():
    ym = parse_year_month(request.args.get('year'), request.args.get('month'))
    if not ym:
        return json_error('연/월이 올바르지 않습니다.')
    return jsonify(home_data(g.ledger, *ym))


@home_bp.route('/analysis')
@require_ledger
def analysis():
    t_year, t_month, *_ = get_target_date()
    return render_template('analysis.html', ledger=g.ledger, current_user=g.user,
                           initial_data=analysis_data(g.ledger, t_year, t_month),
                           t_year=t_year, t_month=t_month, current_tab='analysis')


@home_bp.route('/api/analysis_data')
@require_ledger
def api_analysis_data():
    ym = parse_year_month(request.args.get('year'), request.args.get('month'))
    if not ym:
        return json_error('연/월이 올바르지 않습니다.')
    return jsonify(analysis_data(g.ledger, *ym))
