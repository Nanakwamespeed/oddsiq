"""Market predictions routes for multiple betting markets."""
from datetime import datetime
from flask import Blueprint, request
from flask_jwt_extended import verify_jwt_in_request, get_jwt
from sqlalchemy import func, and_

from ..extensions import db
from ..models.market_prediction import MarketPrediction
from ..models.market_odds import MarketOdds
from ..models.fixture import Fixture
from ..models.league import League
from ..models.sport import Sport
from ..utils.helpers import json_error, json_success, get_date_range, parse_sport_filter

market_predictions_bp = Blueprint('market_predictions', __name__)


def get_user_premium_status():
    """Check if current user has premium access."""
    try:
        verify_jwt_in_request(optional=True)
        claims = get_jwt()
        if claims:
            role = claims.get('role', 'free')
            return role in ['premium', 'admin']
    except Exception:
        pass
    return False


def _best_per_fixture_subq(market_type, line_value=None):
    """Subquery: max confidence score per fixture for a given market/line."""
    q = db.session.query(
        MarketPrediction.fixture_id.label('fixture_id'),
        func.max(MarketPrediction.confidence_score).label('max_conf')
    ).filter(MarketPrediction.market_type == market_type)
    if line_value is not None:
        q = q.filter(MarketPrediction.line_value == line_value)
    return q.group_by(MarketPrediction.fixture_id).subquery('best_mkt')


def _all_outcomes_for_fixtures(fixture_ids, market_type, line_value=None):
    """Return all outcomes for a list of fixture IDs, keyed by fixture_id."""
    if not fixture_ids:
        return {}
    q = MarketPrediction.query.filter(
        MarketPrediction.fixture_id.in_(fixture_ids),
        MarketPrediction.market_type == market_type
    )
    if line_value is not None:
        q = q.filter(MarketPrediction.line_value == line_value)
    grouped = {}
    for p in q.all():
        grouped.setdefault(p.fixture_id, []).append({
            'outcome': p.predicted_outcome,
            'probability': round(p.model_probability * 100, 1) if p.model_probability else None,
            'confidence_score': round(p.confidence_score * 100, 1),
        })
    # Sort each group highest confidence first
    for fid in grouped:
        grouped[fid].sort(key=lambda x: x['confidence_score'], reverse=True)
    return grouped


@market_predictions_bp.route('/', methods=['GET'])
def get_market_predictions():
    """
    Get market predictions with filters.

    Query params:
    - market: market type (over_under, btts, double_chance, corners, ht_ft)
    - sport: football, basketball
    - date: today, tomorrow, week, or specific date
    - line: for over/under markets (e.g., 2.5)
    - value_bets_only: true/false
    - page, per_page: pagination
    """
    is_premium = get_user_premium_status()

    market_type = request.args.get('market')
    sport = parse_sport_filter(request.args.get('sport'))
    date_str = request.args.get('date')
    line = request.args.get('line', type=float)
    value_bets_only = request.args.get('value_bets_only', 'false').lower() == 'true'
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Build query
    query = MarketPrediction.query.join(Fixture).join(League).filter(
        Fixture.status == 'upcoming',
        Fixture.kickoff_at >= datetime.utcnow()
    )

    # Apply filters
    if market_type:
        query = query.filter(MarketPrediction.market_type == market_type)

    if sport:
        query = query.join(Sport).filter(Sport.name == sport)

    if line is not None:
        query = query.filter(MarketPrediction.line_value == line)

    if value_bets_only:
        query = query.filter(MarketPrediction.is_value_bet == True)

    # Apply date filter
    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    # Order by kickoff time
    query = query.order_by(Fixture.kickoff_at)

    # Premium gating
    if not is_premium:
        predictions = query.limit(5).all()
        total = min(query.count(), 5)
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total = pagination.total

    # Serialize with odds
    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        pred_data['market_name'] = MarketPrediction.get_market_display_name(pred.market_type)
        pred_data['outcome_display'] = MarketPrediction.get_outcome_display(
            pred.market_type, pred.predicted_outcome, pred.line_value
        )

        # Get best odds for this prediction
        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id,
            pred.market_type,
            pred.predicted_outcome,
            pred.line_value
        )
        if best_odds:
            pred_data['best_odds'] = {
                'odds': best_odds,
                'bookmaker': bookmaker,
                'affiliate_url': affiliate_url
            }

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': total,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/fixture/<int:fixture_id>', methods=['GET'])
def get_fixture_markets(fixture_id):
    """
    Get all market predictions for a specific fixture.

    Groups predictions by market type with corresponding odds.
    """
    is_premium = get_user_premium_status()

    fixture = Fixture.query.get(fixture_id)
    if not fixture:
        return json_error('Fixture not found', 404)

    predictions = MarketPrediction.query.filter_by(fixture_id=fixture_id).all()

    # Get all market odds for this fixture
    all_odds = MarketOdds.query.filter_by(fixture_id=fixture_id).all()

    # Group odds by market type
    odds_by_market = {}
    for odds in all_odds:
        key = (odds.market_type, odds.line_value)
        if key not in odds_by_market:
            odds_by_market[key] = []
        odds_by_market[key].append(odds.to_dict())

    # Group predictions by market type
    markets = {}
    for pred in predictions:
        market_type = pred.market_type
        if market_type not in markets:
            markets[market_type] = {
                'market_name': MarketPrediction.get_market_display_name(market_type),
                'predictions': [],
                'all_odds': []
            }

        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['outcome_display'] = MarketPrediction.get_outcome_display(
            pred.market_type, pred.predicted_outcome, pred.line_value
        )

        # Get best odds for this prediction
        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            fixture_id,
            pred.market_type,
            pred.predicted_outcome,
            pred.line_value
        )
        if best_odds:
            pred_data['best_odds'] = {
                'odds': best_odds,
                'bookmaker': bookmaker,
                'affiliate_url': affiliate_url
            }

        markets[market_type]['predictions'].append(pred_data)

        # Add all odds for this market/line combination
        key = (pred.market_type, pred.line_value)
        if key in odds_by_market:
            markets[market_type]['all_odds'] = odds_by_market[key]

    return json_success(data={
        'fixture': fixture.to_dict(),
        'markets': markets
    })


@market_predictions_bp.route('/over-under', methods=['GET'])
def get_over_under_predictions():
    """
    Get Over/Under goals predictions.

    Query params:
    - line: goal line (default 2.5)
    - sport: football, basketball
    - date: today, tomorrow, week
    """
    is_premium = get_user_premium_status()
    line = request.args.get('line', 2.5, type=float)
    sport = parse_sport_filter(request.args.get('sport'))
    date_str = request.args.get('date')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    subq = _best_per_fixture_subq('over_under', line_value=line)
    query = (
        MarketPrediction.query
        .join(subq, and_(
            MarketPrediction.fixture_id == subq.c.fixture_id,
            MarketPrediction.confidence_score == subq.c.max_conf
        ))
        .filter(MarketPrediction.market_type == 'over_under', MarketPrediction.line_value == line)
        .join(Fixture)
        .join(League)
        .filter(Fixture.status == 'upcoming', Fixture.kickoff_at >= datetime.utcnow())
    )

    if sport:
        query = query.join(Sport).filter(Sport.name == sport)

    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    query = query.order_by(MarketPrediction.confidence_score.desc())

    if not is_premium:
        predictions = query.limit(5).all()
        total, total_pages = min(query.count(), 5), 1
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total, total_pages = pagination.total, pagination.pages

    fixture_ids = [p.fixture_id for p in predictions]
    all_outcomes_map = _all_outcomes_for_fixtures(fixture_ids, 'over_under', line)

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        pred_data['outcome_display'] = f"{'Over' if pred.predicted_outcome == 'over' else 'Under'} {line}"
        pred_data['all_outcomes'] = all_outcomes_map.get(pred.fixture_id, [])

        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id, 'over_under', pred.predicted_outcome, line
        )
        if best_odds:
            pred_data['best_odds'] = {'odds': best_odds, 'bookmaker': bookmaker, 'affiliate_url': affiliate_url}

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'line': line,
        'total': total,
        'page': page if is_premium else 1,
        'per_page': per_page if is_premium else 5,
        'total_pages': total_pages,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/btts', methods=['GET'])
def get_btts_predictions():
    """
    Get Both Teams To Score predictions.

    Query params:
    - sport: football (BTTS is mainly for football)
    - date: today, tomorrow, week
    """
    is_premium = get_user_premium_status()
    date_str = request.args.get('date')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    subq = _best_per_fixture_subq('btts')
    query = (
        MarketPrediction.query
        .join(subq, and_(
            MarketPrediction.fixture_id == subq.c.fixture_id,
            MarketPrediction.confidence_score == subq.c.max_conf
        ))
        .filter(MarketPrediction.market_type == 'btts')
        .join(Fixture)
        .join(League)
        .filter(Fixture.status == 'upcoming', Fixture.kickoff_at >= datetime.utcnow())
    )

    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    query = query.order_by(MarketPrediction.confidence_score.desc())

    if not is_premium:
        predictions = query.limit(5).all()
        total, total_pages = min(query.count(), 5), 1
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total, total_pages = pagination.total, pagination.pages

    fixture_ids = [p.fixture_id for p in predictions]
    all_outcomes_map = _all_outcomes_for_fixtures(fixture_ids, 'btts')

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        pred_data['outcome_display'] = 'Yes' if pred.predicted_outcome == 'yes' else 'No'
        pred_data['all_outcomes'] = all_outcomes_map.get(pred.fixture_id, [])

        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id, 'btts', pred.predicted_outcome
        )
        if best_odds:
            pred_data['best_odds'] = {'odds': best_odds, 'bookmaker': bookmaker, 'affiliate_url': affiliate_url}

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': total,
        'page': page if is_premium else 1,
        'per_page': per_page if is_premium else 5,
        'total_pages': total_pages,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/double-chance', methods=['GET'])
def get_double_chance_predictions():
    """
    Get Double Chance predictions (1X, X2, 12).

    Query params:
    - sport: football
    - date: today, tomorrow, week
    """
    is_premium = get_user_premium_status()
    date_str = request.args.get('date')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    subq = _best_per_fixture_subq('double_chance')
    query = (
        MarketPrediction.query
        .join(subq, and_(
            MarketPrediction.fixture_id == subq.c.fixture_id,
            MarketPrediction.confidence_score == subq.c.max_conf
        ))
        .filter(MarketPrediction.market_type == 'double_chance')
        .join(Fixture)
        .join(League)
        .filter(Fixture.status == 'upcoming', Fixture.kickoff_at >= datetime.utcnow())
    )

    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    query = query.order_by(MarketPrediction.confidence_score.desc())

    if not is_premium:
        predictions = query.limit(5).all()
        total, total_pages = min(query.count(), 5), 1
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total, total_pages = pagination.total, pagination.pages

    fixture_ids = [p.fixture_id for p in predictions]
    all_outcomes_map = _all_outcomes_for_fixtures(fixture_ids, 'double_chance')

    results = []
    dc_names = {'1X': 'Home or Draw', 'X2': 'Draw or Away', '12': 'Home or Away'}
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        pred_data['outcome_display'] = dc_names.get(pred.predicted_outcome, pred.predicted_outcome)
        pred_data['all_outcomes'] = all_outcomes_map.get(pred.fixture_id, [])

        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id, 'double_chance', pred.predicted_outcome
        )
        if best_odds:
            pred_data['best_odds'] = {'odds': best_odds, 'bookmaker': bookmaker, 'affiliate_url': affiliate_url}

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': total,
        'page': page if is_premium else 1,
        'per_page': per_page if is_premium else 5,
        'total_pages': total_pages,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/corners', methods=['GET'])
def get_corners_predictions():
    """
    Get Corners Over/Under predictions.

    Query params:
    - line: corner line (default 9.5)
    - date: today, tomorrow, week
    """
    is_premium = get_user_premium_status()
    line = request.args.get('line', 9.5, type=float)
    date_str = request.args.get('date')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    subq = _best_per_fixture_subq('corners', line_value=line)
    query = (
        MarketPrediction.query
        .join(subq, and_(
            MarketPrediction.fixture_id == subq.c.fixture_id,
            MarketPrediction.confidence_score == subq.c.max_conf
        ))
        .filter(MarketPrediction.market_type == 'corners', MarketPrediction.line_value == line)
        .join(Fixture)
        .join(League)
        .filter(Fixture.status == 'upcoming', Fixture.kickoff_at >= datetime.utcnow())
    )

    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    query = query.order_by(MarketPrediction.confidence_score.desc())

    if not is_premium:
        predictions = query.limit(5).all()
        total, total_pages = min(query.count(), 5), 1
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total, total_pages = pagination.total, pagination.pages

    fixture_ids = [p.fixture_id for p in predictions]
    all_outcomes_map = _all_outcomes_for_fixtures(fixture_ids, 'corners', line)

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        pred_data['outcome_display'] = f"{'Over' if pred.predicted_outcome == 'over' else 'Under'} {line} Corners"
        pred_data['all_outcomes'] = all_outcomes_map.get(pred.fixture_id, [])

        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id, 'corners', pred.predicted_outcome, line
        )
        if best_odds:
            pred_data['best_odds'] = {'odds': best_odds, 'bookmaker': bookmaker, 'affiliate_url': affiliate_url}

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'line': line,
        'total': total,
        'page': page if is_premium else 1,
        'per_page': per_page if is_premium else 5,
        'total_pages': total_pages,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/ht-ft', methods=['GET'])
def get_ht_ft_predictions():
    """
    Get Half-time/Full-time predictions.

    Query params:
    - date: today, tomorrow, week
    """
    is_premium = get_user_premium_status()
    date_str = request.args.get('date')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    subq = _best_per_fixture_subq('ht_ft')
    query = (
        MarketPrediction.query
        .join(subq, and_(
            MarketPrediction.fixture_id == subq.c.fixture_id,
            MarketPrediction.confidence_score == subq.c.max_conf
        ))
        .filter(MarketPrediction.market_type == 'ht_ft')
        .join(Fixture)
        .join(League)
        .filter(Fixture.status == 'upcoming', Fixture.kickoff_at >= datetime.utcnow())
    )

    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    query = query.order_by(MarketPrediction.confidence_score.desc())

    if not is_premium:
        predictions = query.limit(5).all()
        total, total_pages = min(query.count(), 5), 1
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total, total_pages = pagination.total, pagination.pages

    fixture_ids = [p.fixture_id for p in predictions]
    all_outcomes_map = _all_outcomes_for_fixtures(fixture_ids, 'ht_ft')

    results = []
    names = {'home': 'Home', 'draw': 'Draw', 'away': 'Away'}
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()

        if '_' in pred.predicted_outcome:
            ht, ft = pred.predicted_outcome.split('_')
            pred_data['outcome_display'] = f"{names.get(ht, ht)} / {names.get(ft, ft)}"
            pred_data['ht_label'] = names.get(ht, ht)
            pred_data['ft_label'] = names.get(ft, ft)
        else:
            pred_data['outcome_display'] = pred.predicted_outcome

        pred_data['all_outcomes'] = all_outcomes_map.get(pred.fixture_id, [])

        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id, 'ht_ft', pred.predicted_outcome
        )
        if best_odds:
            pred_data['best_odds'] = {'odds': best_odds, 'bookmaker': bookmaker, 'affiliate_url': affiliate_url}

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': total,
        'page': page if is_premium else 1,
        'per_page': per_page if is_premium else 5,
        'total_pages': total_pages,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/value-bets', methods=['GET'])
def get_market_value_bets():
    """
    Get value bet predictions across all markets.

    Query params:
    - market: filter by market type
    - sport: football, basketball
    - date: today, tomorrow, week
    """
    is_premium = get_user_premium_status()
    market_type = request.args.get('market')
    sport = parse_sport_filter(request.args.get('sport'))
    date_str = request.args.get('date')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    query = MarketPrediction.query.filter_by(is_value_bet=True).join(Fixture).join(League).filter(
        Fixture.status == 'upcoming',
        Fixture.kickoff_at >= datetime.utcnow()
    )

    if market_type:
        query = query.filter(MarketPrediction.market_type == market_type)

    if sport:
        query = query.join(Sport).filter(Sport.name == sport)

    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    query = query.order_by(MarketPrediction.value_edge.desc())

    if not is_premium:
        predictions = query.limit(5).all()
        total, total_pages = min(query.count(), 5), 1
    else:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total, total_pages = pagination.total, pagination.pages

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        pred_data['market_name'] = MarketPrediction.get_market_display_name(pred.market_type)
        pred_data['outcome_display'] = MarketPrediction.get_outcome_display(
            pred.market_type, pred.predicted_outcome, pred.line_value
        )

        best_odds, bookmaker, affiliate_url = MarketOdds.get_best_odds_for_market(
            pred.fixture_id, pred.market_type, pred.predicted_outcome, pred.line_value
        )
        if best_odds:
            pred_data['best_odds'] = {'odds': best_odds, 'bookmaker': bookmaker, 'affiliate_url': affiliate_url}

        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': total,
        'page': page if is_premium else 1,
        'per_page': per_page if is_premium else 5,
        'total_pages': total_pages,
        'is_premium_user': is_premium
    })


@market_predictions_bp.route('/available', methods=['GET'])
def get_available_markets():
    """Get list of available betting markets."""
    markets = [
        {
            'type': 'over_under',
            'name': 'Over/Under Goals',
            'description': 'Predict if total goals will be over or under a specific line',
            'lines': [0.5, 1.5, 2.5, 3.5, 4.5]
        },
        {
            'type': 'btts',
            'name': 'Both Teams To Score',
            'description': 'Predict if both teams will score in the match',
            'outcomes': ['yes', 'no']
        },
        {
            'type': 'double_chance',
            'name': 'Double Chance',
            'description': 'Cover two possible outcomes in one bet',
            'outcomes': [
                {'code': '1X', 'name': 'Home or Draw'},
                {'code': 'X2', 'name': 'Draw or Away'},
                {'code': '12', 'name': 'Home or Away'}
            ]
        },
        {
            'type': 'corners',
            'name': 'Corners Over/Under',
            'description': 'Predict if total corners will be over or under a specific line',
            'lines': [8.5, 9.5, 10.5, 11.5]
        },
        {
            'type': 'ht_ft',
            'name': 'Half-time/Full-time',
            'description': 'Predict both half-time and full-time results',
            'outcomes': ['home_home', 'home_draw', 'home_away', 'draw_home', 'draw_draw', 'draw_away', 'away_home', 'away_draw', 'away_away']
        }
    ]

    return json_success(data={'markets': markets})
