"""Predictions routes with premium gating."""
from datetime import datetime
from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt, verify_jwt_in_request
from ..extensions import db, cache
from sqlalchemy.orm import aliased, subqueryload
from ..models.prediction import Prediction
from ..models.fixture import Fixture
from ..models.league import League
from ..models.sport import Sport
from ..models.user import User
from ..models.team import Team
from ..utils.decorators import premium_required
from ..utils.helpers import json_error, json_success, get_date_range, parse_sport_filter

predictions_bp = Blueprint('predictions', __name__)


def add_h2h_and_form_data(pred_data, fixture):
    """Add H2H summary and form data to a prediction dict."""
    from ..models.h2h_record import H2HRecord

    home_team = fixture.home_team
    away_team = fixture.away_team

    if not home_team or not away_team:
        return

    # Add H2H summary
    h2h_records = H2HRecord.get_h2h_records(home_team.id, away_team.id, limit=5)
    home_h2h_wins = 0
    away_h2h_wins = 0
    h2h_draws = 0

    for record in h2h_records:
        if record.team1_id == home_team.id:
            if record.result_for_team1 == 'W':
                home_h2h_wins += 1
            elif record.result_for_team1 == 'L':
                away_h2h_wins += 1
            else:
                h2h_draws += 1
        else:
            if record.result_for_team1 == 'W':
                away_h2h_wins += 1
            elif record.result_for_team1 == 'L':
                home_h2h_wins += 1
            else:
                h2h_draws += 1

    pred_data['h2h_summary'] = {
        'total_matches': len(h2h_records),
        'home_wins': home_h2h_wins,
        'away_wins': away_h2h_wins,
        'draws': h2h_draws
    }

    # Add form summary (last 5 matches)
    home_form_records = home_team.get_recent_form(limit=5)
    away_form_records = away_team.get_recent_form(limit=5)

    pred_data['home_form'] = {
        'form_string': ''.join(r.result for r in home_form_records),
        'wins': sum(1 for r in home_form_records if r.result == 'W'),
        'draws': sum(1 for r in home_form_records if r.result == 'D'),
        'losses': sum(1 for r in home_form_records if r.result == 'L')
    }

    pred_data['away_form'] = {
        'form_string': ''.join(r.result for r in away_form_records),
        'wins': sum(1 for r in away_form_records if r.result == 'W'),
        'draws': sum(1 for r in away_form_records if r.result == 'D'),
        'losses': sum(1 for r in away_form_records if r.result == 'L')
    }


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


def parse_league_type_filter(type_param):
    """
    Parse league type filter parameter.

    Accepts:
    - 'domestic' or 'league' -> domestic leagues only
    - 'international' -> all international (club + national)
    - 'international_club' -> Champions League, Europa League, etc.
    - 'international_national' or 'national' -> World Cup, AFCON, Friendlies, etc.
    - None or 'all' -> no filter

    Returns list of league_type values to filter by, or None for no filter.
    """
    if not type_param or type_param.lower() == 'all':
        return None

    type_param = type_param.lower()

    if type_param in ['domestic', 'league', 'leagues']:
        return ['domestic']
    elif type_param == 'international':
        return ['international_club', 'international_national']
    elif type_param in ['international_club', 'club']:
        return ['international_club']
    elif type_param in ['international_national', 'national', 'friendlies']:
        return ['international_national']

    return None


@predictions_bp.route('/', methods=['GET'])
# @cache.cached(timeout=300, query_string=True)  # Disabled - cache doesn't account for user premium status
def get_predictions():
    """
    Get predictions list.
    Free users: max 3 results with premium fields hidden
    Premium users: all results with full details

    Query params:
    - sport: football, basketball, tennis
    - date: today, tomorrow, week, or specific date
    - league: league ID
    - type: domestic, international, international_club, international_national
    """
    is_premium = get_user_premium_status()

    # Parse filters
    sport = parse_sport_filter(request.args.get('sport'))
    date_str = request.args.get('date')  # None means all dates
    league_id = request.args.get('league', type=int)
    league_types = parse_league_type_filter(request.args.get('type'))
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Build query - only upcoming games (status = 'upcoming' and kickoff_at >= now)
    _eager = [
        subqueryload('fixture').subqueryload('home_team'),
        subqueryload('fixture').subqueryload('away_team'),
        subqueryload('fixture').subqueryload('league'),
    ]
    query = Prediction.query.join(Fixture).join(League).options(*_eager).filter(
        Fixture.status == 'upcoming',
        Fixture.kickoff_at >= datetime.utcnow()
    )

    # Apply sport filter
    if sport:
        query = query.join(Sport).filter(Sport.name == sport)

    # Apply league filter
    if league_id:
        query = query.filter(League.id == league_id)

    # Apply league type filter (domestic vs international)
    if league_types:
        query = query.filter(League.league_type.in_(league_types))

    # Apply date filter (only if specified and not 'all')
    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    # Order by kickoff time
    query = query.order_by(Fixture.kickoff_at)

    total_available = query.count()

    # Free users limited to 3 results
    if not is_premium:
        predictions = query.limit(3).all()
        total = 3
    else:
        # Paginate for premium users
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        predictions = pagination.items
        total = pagination.total

    # Serialize with premium field gating and H2H/form data
    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        add_h2h_and_form_data(pred_data, pred.fixture)
        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': total,
        'total_available': total_available,
        'is_premium_user': is_premium
    })


@predictions_bp.route('/<int:prediction_id>', methods=['GET'])
def get_prediction(prediction_id):
    """
    Get single prediction with comprehensive details.

    Returns:
    - Prediction data with confidence score
    - Fixture details with odds
    - Home team form (last 5 matches)
    - Away team form (last 5 matches)
    - Head-to-head records
    - Prediction analysis breakdown
    """
    from ..models.form_record import FormRecord
    from ..models.h2h_record import H2HRecord
    from ..models.odds import Odds
    from ..services.prediction_service import PredictionService

    is_premium = get_user_premium_status()

    prediction = Prediction.query.get(prediction_id)
    if not prediction:
        # Treat as fixture_id for stable daily links (prediction IDs change on regeneration)
        prediction = Prediction.query.filter_by(fixture_id=prediction_id).order_by(Prediction.id.desc()).first()
    if not prediction:
        return json_error('Prediction not found', 404)

    # Check if premium prediction and user doesn't have access
    if prediction.is_premium and not is_premium:
        return json_error('Premium subscription required', 403)

    fixture = prediction.fixture
    home_team = fixture.home_team
    away_team = fixture.away_team

    # Basic prediction data
    pred_data = prediction.to_dict(is_premium_user=is_premium)
    pred_data['fixture'] = fixture.to_dict(include_odds=True)

    # Get home team form (last 5 matches)
    home_form_records = home_team.get_recent_form(limit=5) if home_team else []
    home_form = []
    for record in home_form_records:
        home_form.append({
            'date': record.match_date.isoformat(),
            'result': record.result,
            'goals_scored': record.goals_scored,
            'goals_conceded': record.goals_conceded
        })

    # Calculate home team stats
    home_wins = sum(1 for r in home_form_records if r.result == 'W')
    home_draws = sum(1 for r in home_form_records if r.result == 'D')
    home_losses = sum(1 for r in home_form_records if r.result == 'L')
    home_goals_scored = sum(r.goals_scored for r in home_form_records)
    home_goals_conceded = sum(r.goals_conceded for r in home_form_records)
    home_form_score = FormRecord.calculate_form_score(home_form_records)

    # Get away team form (last 5 matches)
    away_form_records = away_team.get_recent_form(limit=5) if away_team else []
    away_form = []
    for record in away_form_records:
        away_form.append({
            'date': record.match_date.isoformat(),
            'result': record.result,
            'goals_scored': record.goals_scored,
            'goals_conceded': record.goals_conceded
        })

    # Calculate away team stats
    away_wins = sum(1 for r in away_form_records if r.result == 'W')
    away_draws = sum(1 for r in away_form_records if r.result == 'D')
    away_losses = sum(1 for r in away_form_records if r.result == 'L')
    away_goals_scored = sum(r.goals_scored for r in away_form_records)
    away_goals_conceded = sum(r.goals_conceded for r in away_form_records)
    away_form_score = FormRecord.calculate_form_score(away_form_records)

    # Get head-to-head records
    h2h_records = H2HRecord.get_h2h_records(home_team.id, away_team.id, limit=5) if home_team and away_team else []
    h2h_data = []
    home_h2h_wins = 0
    away_h2h_wins = 0
    h2h_draws = 0

    for record in h2h_records:
        result_for_home = record.result_for_team1 if record.team1_id == home_team.id else (
            'L' if record.result_for_team1 == 'W' else ('W' if record.result_for_team1 == 'L' else 'D')
        )

        if result_for_home == 'W':
            home_h2h_wins += 1
        elif result_for_home == 'L':
            away_h2h_wins += 1
        else:
            h2h_draws += 1

        h2h_data.append({
            'date': record.match_date.isoformat(),
            'result_for_home': result_for_home
        })

    home_h2h_score = H2HRecord.calculate_h2h_score(h2h_records, home_team.id) if home_team and h2h_records else 0.5
    away_h2h_score = H2HRecord.calculate_h2h_score(h2h_records, away_team.id) if away_team and h2h_records else 0.5

    # Get odds from all bookmakers
    odds_list = Odds.query.filter_by(fixture_id=fixture.id).all()
    odds_comparison = []
    for odd in odds_list:
        odds_comparison.append({
            'bookmaker': odd.bookmaker_name,
            'home_odds': odd.home_win_odds,
            'draw_odds': odd.draw_odds,
            'away_odds': odd.away_win_odds,
            'affiliate_url': odd.affiliate_url
        })

    # Get market odds (Over/Under, Double Chance, etc.)
    from ..models.market_odds import MarketOdds
    market_odds_list = MarketOdds.query.filter_by(fixture_id=fixture.id).all()

    # Group market odds by type
    market_odds_by_type = {}
    for mo in market_odds_list:
        if mo.market_type not in market_odds_by_type:
            market_odds_by_type[mo.market_type] = []
        market_odds_by_type[mo.market_type].append({
            'bookmaker': mo.bookmaker_name,
            'line_value': mo.line_value,
            'odds': mo.odds_data,
            'affiliate_url': mo.affiliate_url
        })

    # Generate Double Chance odds from 1X2 odds (calculated)
    double_chance = []
    for odd in odds_list:
        if odd.home_win_odds and odd.draw_odds and odd.away_win_odds:
            # DC 1X = 1 / (1/home + 1/draw)
            dc_1x = round(1 / (1/odd.home_win_odds + 1/odd.draw_odds), 2) if odd.draw_odds else None
            # DC X2 = 1 / (1/draw + 1/away)
            dc_x2 = round(1 / (1/odd.draw_odds + 1/odd.away_win_odds), 2) if odd.draw_odds else None
            # DC 12 = 1 / (1/home + 1/away)
            dc_12 = round(1 / (1/odd.home_win_odds + 1/odd.away_win_odds), 2)

            double_chance.append({
                'bookmaker': odd.bookmaker_name,
                'odds': {'1X': dc_1x, 'X2': dc_x2, '12': dc_12},
                'affiliate_url': odd.affiliate_url
            })

    # Build prediction analysis
    sport_name = fixture.league.sport.name if fixture.league and fixture.league.sport else 'football'
    allows_draws = sport_name == 'football'

    analysis = {
        'home_form_score': round(home_form_score * 100, 1),
        'away_form_score': round(away_form_score * 100, 1),
        'home_h2h_score': round(home_h2h_score * 100, 1),
        'away_h2h_score': round(away_h2h_score * 100, 1),
        'home_advantage': 60.0,
        'away_advantage': 40.0,
        'allows_draws': allows_draws,
        'factors': [
            {'name': 'Recent Form', 'weight': '30%', 'description': 'Performance in last 5 matches'},
            {'name': 'Head-to-Head', 'weight': '20%', 'description': 'Historical matchups between teams'},
            {'name': 'Home Advantage', 'weight': '20%', 'description': 'Playing at home gives advantage'},
            {'name': 'Other Factors', 'weight': '30%', 'description': 'Base probability and variance'}
        ]
    }

    # ── Poisson expected goals (λ) ──────────────────────────────
    lambda_home = lambda_away = None
    if home_team and away_team:
        try:
            from ..services.prediction_engine import FootballPredictionEngine
            _pe = FootballPredictionEngine()
            lh, la = _pe.expected_goals(home_team.id, away_team.id)
            lambda_home = round(lh, 2)
            lambda_away = round(la, 2)
        except Exception:
            pass

    analysis['lambda_home'] = lambda_home
    analysis['lambda_away'] = lambda_away

    # ── Auto-generated explanation ──────────────────────────────
    auto_explanation = None
    if lambda_home is not None and lambda_away is not None:
        home_name = home_team.name if home_team else 'Home'
        away_name = away_team.name if away_team else 'Away'
        total_xg = round(lambda_home + lambda_away, 1)

        if lambda_home > lambda_away * 1.35:
            xg_line = f"Strong home attack expected ({lambda_home} xG vs {lambda_away} xG away)."
        elif lambda_away > lambda_home * 1.35:
            xg_line = f"Away side projects as the sharper attack ({lambda_away} xG vs {lambda_home} xG)."
        elif total_xg >= 3.0:
            xg_line = f"High-scoring game likely — model projects {total_xg} total expected goals."
        elif total_xg <= 1.8:
            xg_line = f"Tight, low-scoring affair expected — only {total_xg} combined xG projected."
        else:
            xg_line = f"Closely contested match — {lambda_home} vs {lambda_away} expected goals."

        form_parts = []
        if home_form_score > 0.72:
            form_parts.append(f"{home_name} arrive in excellent form")
        elif home_form_score < 0.28:
            form_parts.append(f"{home_name} are struggling for form")
        if away_form_score > 0.72:
            form_parts.append(f"{away_name} hitting their stride recently")
        elif away_form_score < 0.28:
            form_parts.append(f"{away_name} are in poor recent form")

        h2h_line = ''
        if len(h2h_records) >= 3:
            if home_h2h_wins > away_h2h_wins + 1:
                h2h_line = (f" {home_name} have historically dominated this fixture "
                            f"({home_h2h_wins}W-{h2h_draws}D-{away_h2h_wins}L).")
            elif away_h2h_wins > home_h2h_wins + 1:
                h2h_line = (f" {away_name} hold a strong head-to-head edge "
                            f"({away_h2h_wins}W-{h2h_draws}D-{home_h2h_wins}L).")

        auto_explanation = xg_line
        if form_parts:
            auto_explanation += ' ' + '. '.join(form_parts) + '.'
        auto_explanation += h2h_line

    analysis['auto_explanation'] = auto_explanation

    # ── Historical calibration for this confidence band ─────────
    calibration = None
    try:
        from ..models.accuracy_log import AccuracyLog
        band_lo = max(0.0, prediction.confidence_score - 0.05)
        band_hi = min(1.0, prediction.confidence_score + 0.05)
        band_q = db.session.query(AccuracyLog).join(Prediction, AccuracyLog.prediction_id == Prediction.id).filter(
            Prediction.confidence_score.between(band_lo, band_hi)
        )
        band_total = band_q.count()
        band_correct = band_q.filter(AccuracyLog.was_correct == True).count()
        if band_total >= 10:
            calibration = {
                'band': f"{round(band_lo * 100)}-{round(band_hi * 100)}%",
                'total': band_total,
                'correct': band_correct,
                'accuracy': round(band_correct / band_total * 100, 1)
            }
    except Exception:
        pass

    analysis['calibration'] = calibration

    # ── Market consensus (de-vigged bookmaker implied probabilities) ──
    market_consensus = None
    try:
        best_row = Odds.query.filter_by(fixture_id=fixture.id).first()
        if best_row and best_row.home_win_odds and best_row.away_win_odds:
            inv_h = 1.0 / best_row.home_win_odds
            inv_d = (1.0 / best_row.draw_odds) if best_row.draw_odds else 0.0
            inv_a = 1.0 / best_row.away_win_odds
            total_inv = inv_h + inv_d + inv_a
            if total_inv > 0:
                market_consensus = {
                    'home':  round(inv_h / total_inv * 100, 1),
                    'draw':  round(inv_d / total_inv * 100, 1) if inv_d else None,
                    'away':  round(inv_a / total_inv * 100, 1),
                    'bookmaker': best_row.bookmaker_name,
                }
    except Exception:
        pass

    analysis['market_consensus'] = market_consensus

    # Build response
    response_data = {
        **pred_data,
        'home_team_form': {
            'team': home_team.to_dict() if home_team else None,
            'recent_matches': home_form,
            'form_string': ''.join(r['result'] for r in home_form),  # e.g., "WDWLW"
            'stats': {
                'matches_played': len(home_form_records),
                'wins': home_wins,
                'draws': home_draws,
                'losses': home_losses,
                'goals_scored': home_goals_scored,
                'goals_conceded': home_goals_conceded,
                'form_score': round(home_form_score * 100, 1)
            }
        },
        'away_team_form': {
            'team': away_team.to_dict() if away_team else None,
            'recent_matches': away_form,
            'form_string': ''.join(r['result'] for r in away_form),
            'stats': {
                'matches_played': len(away_form_records),
                'wins': away_wins,
                'draws': away_draws,
                'losses': away_losses,
                'goals_scored': away_goals_scored,
                'goals_conceded': away_goals_conceded,
                'form_score': round(away_form_score * 100, 1)
            }
        },
        'head_to_head': {
            'matches': h2h_data,
            'total_matches': len(h2h_records),
            'home_wins': home_h2h_wins,
            'away_wins': away_h2h_wins,
            'draws': h2h_draws,
            'summary': f"{home_team.name if home_team else 'Home'}: {home_h2h_wins}W, {away_team.name if away_team else 'Away'}: {away_h2h_wins}W, Draws: {h2h_draws}"
        },
        'odds_comparison': odds_comparison,
        'market_odds': {
            'over_under': market_odds_by_type.get('over_under', []),
            'double_chance': double_chance,
            'btts': market_odds_by_type.get('btts', []),
        },
        'analysis': analysis
    }

    return json_success(data=response_data)


@predictions_bp.route('/top-picks', methods=['GET'])
def get_top_picks():
    """
    Get top predictions by confidence score (public).

    Query params:
    - limit: number of results (default 3)
    - type: domestic, international, international_club, international_national
    """
    is_premium = get_user_premium_status()
    limit = request.args.get('limit', 3, type=int)
    league_types = parse_league_type_filter(request.args.get('type'))

    cache_key = f"top_picks_{limit}_{is_premium}_{request.args.get('type', '')}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Get predictions ordered by confidence - today only
    start_date, end_date = get_date_range('today')
    _eager = [
        subqueryload('fixture').subqueryload('home_team'),
        subqueryload('fixture').subqueryload('away_team'),
        subqueryload('fixture').subqueryload('league'),
    ]
    query = Prediction.query.join(Fixture).join(League).options(*_eager).filter(
        Fixture.status == 'upcoming',
        Fixture.kickoff_at >= datetime.utcnow(),
        Fixture.kickoff_at.between(start_date, end_date)
    )

    # Apply league type filter
    if league_types:
        query = query.filter(League.league_type.in_(league_types))

    query = query.order_by(Prediction.confidence_score.desc()).limit(limit)

    predictions = query.all()

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        add_h2h_and_form_data(pred_data, pred.fixture)
        results.append(pred_data)

    response = json_success(data={
        'predictions': results,
        'total': len(results)
    })
    cache.set(cache_key, response, timeout=300)
    return response


@predictions_bp.route('/ticker', methods=['GET'])
def get_ticker_predictions():
    """
    Lightweight ticker feed — all of today's predictions regardless of kickoff time.
    Single joined query, no H2H/form data. Public, cached 10 min.
    """
    cached = cache.get('ticker_today')
    if cached is not None:
        return cached

    start_date, end_date = get_date_range('today')

    HomeTeam = aliased(Team, name='ht')
    AwayTeam = aliased(Team, name='at')

    rows = (
        db.session.query(
            Prediction.id,
            Prediction.predicted_outcome,
            Prediction.confidence_score,
            Fixture.kickoff_at,
            HomeTeam.name.label('home_name'),
            AwayTeam.name.label('away_name'),
        )
        .join(Fixture, Prediction.fixture_id == Fixture.id)
        .join(HomeTeam, Fixture.home_team_id == HomeTeam.id)
        .join(AwayTeam, Fixture.away_team_id == AwayTeam.id)
        .filter(Fixture.kickoff_at.between(start_date, end_date))
        .order_by(Fixture.kickoff_at)
        .limit(30)
        .all()
    )

    results = [
        {
            'id': r.id,
            'predicted_outcome': r.predicted_outcome,
            'confidence_score': round(r.confidence_score * 100, 1) if r.confidence_score <= 1 else round(r.confidence_score, 1),
            'fixture': {
                'home_team': {'name': r.home_name},
                'away_team': {'name': r.away_name},
                'kickoff_at': r.kickoff_at.isoformat() if r.kickoff_at else None,
            }
        }
        for r in rows
    ]

    response = json_success(data={'predictions': results, 'total': len(results)})
    cache.set('ticker_today', response, timeout=600)
    return response


@predictions_bp.route('/today', methods=['GET'])
# @cache.cached(timeout=300, query_string=True)  # Disabled - cache doesn't account for user premium status
def get_today_predictions():
    """
    Get today's predictions (public).

    Query params:
    - type: domestic, international, international_club, international_national
    """
    is_premium = get_user_premium_status()
    league_types = parse_league_type_filter(request.args.get('type'))

    start_date, end_date = get_date_range('today')
    now = datetime.utcnow()

    _eager = [
        subqueryload('fixture').subqueryload('home_team'),
        subqueryload('fixture').subqueryload('away_team'),
        subqueryload('fixture').subqueryload('league'),
    ]
    # Only show today's games that haven't started yet
    query = Prediction.query.join(Fixture).join(League).options(*_eager).filter(
        Fixture.status == 'upcoming',
        Fixture.kickoff_at.between(start_date, end_date),
        Fixture.kickoff_at >= now  # Exclude past games
    )

    # Apply league type filter
    if league_types:
        query = query.filter(League.league_type.in_(league_types))

    query = query.order_by(Fixture.kickoff_at)

    if not is_premium:
        predictions = query.limit(3).all()
    else:
        predictions = query.all()

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict()
        add_h2h_and_form_data(pred_data, pred.fixture)
        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': len(results)
    })


@predictions_bp.route('/value-bets', methods=['GET'])
# @cache.cached(timeout=300, query_string=True)  # Disabled for debugging
def get_value_bets():
    """
    Get value bet predictions (limited for free users).

    Query params:
    - sport: football, basketball, tennis
    - date: today, tomorrow, week, or specific date
    - type: domestic, international, international_club, international_national
    """
    is_premium = get_user_premium_status()
    sport = parse_sport_filter(request.args.get('sport'))
    date_str = request.args.get('date')  # None means all dates
    league_types = parse_league_type_filter(request.args.get('type'))

    _eager = [
        subqueryload('fixture').subqueryload('home_team'),
        subqueryload('fixture').subqueryload('away_team'),
        subqueryload('fixture').subqueryload('league'),
    ]
    # Build query for value bets only - exclude past games
    query = Prediction.query.filter_by(is_value_bet=True).join(Fixture).join(League).options(*_eager).filter(
        Fixture.status == 'upcoming',
        Fixture.kickoff_at >= datetime.utcnow()
    )

    # Apply sport filter
    if sport:
        query = query.join(Sport).filter(Sport.name == sport)

    # Apply league type filter
    if league_types:
        query = query.filter(League.league_type.in_(league_types))

    # Apply date filter (only if specified and not 'all')
    if date_str and date_str.lower() != 'all':
        start_date, end_date = get_date_range(date_str)
        if start_date and end_date:
            query = query.filter(Fixture.kickoff_at.between(start_date, end_date))

    # Order by confidence score (highest first)
    query = query.order_by(Prediction.confidence_score.desc())

    # Limit for free users
    if not is_premium:
        predictions = query.limit(3).all()
    else:
        predictions = query.all()

    results = []
    for pred in predictions:
        pred_data = pred.to_dict(is_premium_user=is_premium)
        pred_data['fixture'] = pred.fixture.to_dict(include_odds=is_premium)
        add_h2h_and_form_data(pred_data, pred.fixture)
        results.append(pred_data)

    return json_success(data={
        'predictions': results,
        'total': len(results),
        'is_premium_user': is_premium
    })
