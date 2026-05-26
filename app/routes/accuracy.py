"""Accuracy statistics routes."""
from flask import Blueprint, request
from sqlalchemy import func, case
from ..extensions import cache, db
from ..models.accuracy_log import AccuracyLog
from ..models.prediction import Prediction
from ..models.fixture import Fixture
from ..models.league import League
from ..models.sport import Sport
from ..utils.helpers import json_success, json_error

accuracy_bp = Blueprint('accuracy', __name__)


@accuracy_bp.route('/', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def get_accuracy_stats():
    """
    Get comprehensive accuracy statistics.

    Query params:
    - period: today, week, month, all (default: all)
    """
    from datetime import datetime, timedelta

    period = request.args.get('period', 'all')

    # Calculate date range
    now = datetime.utcnow()
    if period == 'today':
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start_date = now - timedelta(days=7)
    elif period == 'month':
        start_date = now - timedelta(days=30)
    else:
        start_date = None

    # Base query
    query = db.session.query(AccuracyLog)
    if start_date:
        query = query.filter(AccuracyLog.logged_at >= start_date)

    total = query.count()
    correct = query.filter(AccuracyLog.was_correct == True).count()

    # Overall accuracy
    overall = {
        'total_predictions': total,
        'correct_predictions': correct,
        'incorrect_predictions': total - correct,
        'accuracy_percentage': round((correct / total * 100), 1) if total > 0 else 0,
        'period': period
    }

    # Per-sport accuracy
    sports = Sport.query.all()
    by_sport = {}
    for sport in sports:
        sport_query = query.join(Prediction).join(Fixture).join(League).filter(
            League.sport_id == sport.id
        )
        sport_total = sport_query.count()
        sport_correct = sport_query.filter(AccuracyLog.was_correct == True).count()

        if sport_total > 0:
            by_sport[sport.name] = {
                'total_predictions': sport_total,
                'correct_predictions': sport_correct,
                'accuracy_percentage': round((sport_correct / sport_total * 100), 1)
            }

    # By outcome type
    by_outcome = {}
    for outcome in ['home', 'draw', 'away']:
        outcome_query = query.join(Prediction).filter(Prediction.predicted_outcome == outcome)
        outcome_total = outcome_query.count()
        outcome_correct = outcome_query.filter(AccuracyLog.was_correct == True).count()

        if outcome_total > 0:
            by_outcome[outcome] = {
                'total': outcome_total,
                'correct': outcome_correct,
                'accuracy_percentage': round((outcome_correct / outcome_total * 100), 1)
            }

    # By confidence level
    by_confidence = []
    confidence_ranges = [
        ('high', 0.75, 1.0),
        ('medium', 0.60, 0.75),
        ('low', 0.0, 0.60)
    ]

    for label, min_conf, max_conf in confidence_ranges:
        conf_query = query.join(Prediction).filter(
            Prediction.confidence_score >= min_conf,
            Prediction.confidence_score < max_conf
        )
        conf_total = conf_query.count()
        conf_correct = conf_query.filter(AccuracyLog.was_correct == True).count()

        if conf_total > 0:
            by_confidence.append({
                'level': label,
                'range': f'{int(min_conf*100)}-{int(max_conf*100)}%',
                'total': conf_total,
                'correct': conf_correct,
                'accuracy_percentage': round((conf_correct / conf_total * 100), 1)
            })

    # Value bets accuracy (from market predictions with is_value_bet=True)
    from ..models.market_accuracy_log import MarketAccuracyLog
    from ..models.market_prediction import MarketPrediction

    value_query = (
        db.session.query(MarketAccuracyLog)
        .join(MarketPrediction, MarketPrediction.id == MarketAccuracyLog.market_prediction_id)
        .filter(MarketPrediction.is_value_bet == True)
    )
    if start_date:
        value_query = value_query.filter(MarketAccuracyLog.logged_at >= start_date)

    value_total = value_query.count()
    value_correct = value_query.filter(MarketAccuracyLog.was_correct == True).count()

    value_bets = {
        'total': value_total,
        'correct': value_correct,
        'accuracy_percentage': round((value_correct / value_total * 100), 1) if value_total > 0 else 0
    }

    return json_success(data={
        'overall': overall,
        'by_sport': by_sport,
        'by_outcome': by_outcome,
        'by_confidence': by_confidence,
        'value_bets': value_bets
    })


@accuracy_bp.route('/<sport_name>', methods=['GET'])
@cache.cached(timeout=3600)
def get_sport_accuracy(sport_name):
    """Get accuracy statistics for a specific sport."""
    sport = Sport.query.filter_by(name=sport_name.lower()).first()

    if not sport:
        from ..utils.helpers import json_error
        return json_error('Sport not found', 404)

    stats = AccuracyLog.get_accuracy_stats(sport_id=sport.id)

    return json_success(data={
        'sport': sport.to_dict(),
        'accuracy': stats
    })


@accuracy_bp.route('/recent', methods=['GET'])
@cache.cached(timeout=300, query_string=True)
def get_recent_accuracy():
    """Get recent prediction results."""
    limit = request.args.get('limit', 20, type=int)

    # Get recent logged predictions
    recent_logs = AccuracyLog.query.order_by(
        AccuracyLog.logged_at.desc()
    ).limit(min(limit, 50)).all()

    results = []
    for log in recent_logs:
        prediction = log.prediction
        fixture = prediction.fixture if prediction else None

        results.append({
            'prediction_id': log.prediction_id,
            'predicted_outcome': prediction.predicted_outcome if prediction else None,
            'confidence_score': round(prediction.confidence_score * 100, 1) if prediction else None,
            'actual_outcome': log.actual_outcome,
            'was_correct': log.was_correct,
            'fixture': {
                'id': fixture.id,
                'home_team': fixture.home_team.name if fixture and fixture.home_team else None,
                'away_team': fixture.away_team.name if fixture and fixture.away_team else None,
                'home_score': fixture.home_score if fixture else None,
                'away_score': fixture.away_score if fixture else None,
                'league': fixture.league.name if fixture and fixture.league else None,
                'kickoff_at': fixture.kickoff_at.isoformat() if fixture else None
            } if fixture else None,
            'logged_at': log.logged_at.isoformat()
        })

    # Calculate streak
    streak = 0
    streak_type = None
    for log in recent_logs:
        if streak_type is None:
            streak_type = log.was_correct
            streak = 1
        elif log.was_correct == streak_type:
            streak += 1
        else:
            break

    return json_success(data={
        'recent': results,
        'current_streak': {
            'type': 'winning' if streak_type else 'losing',
            'count': streak
        } if recent_logs else None
    })


@accuracy_bp.route('/trends', methods=['GET'])
@cache.cached(timeout=600)
def get_accuracy_trends():
    """Get accuracy trends over time (last 30 days)."""
    from datetime import datetime, timedelta

    # Get daily accuracy for last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    daily_stats = db.session.query(
        func.date(AccuracyLog.logged_at).label('date'),
        func.count(AccuracyLog.id).label('total'),
        func.sum(case((AccuracyLog.was_correct == True, 1), else_=0)).label('correct')
    ).filter(
        AccuracyLog.logged_at >= thirty_days_ago
    ).group_by(
        func.date(AccuracyLog.logged_at)
    ).order_by(
        func.date(AccuracyLog.logged_at)
    ).all()

    trends = []
    for stat in daily_stats:
        accuracy = round((stat.correct / stat.total * 100), 1) if stat.total > 0 else 0
        trends.append({
            'date': str(stat.date),
            'total_predictions': stat.total,
            'correct_predictions': stat.correct,
            'accuracy_percentage': accuracy
        })

    # Calculate moving average (7-day)
    if len(trends) >= 7:
        for i in range(6, len(trends)):
            window = trends[i-6:i+1]
            total_correct = sum(d['correct_predictions'] for d in window)
            total_preds = sum(d['total_predictions'] for d in window)
            trends[i]['moving_avg_7d'] = round((total_correct / total_preds * 100), 1) if total_preds > 0 else 0

    return json_success(data={'trends': trends})


@accuracy_bp.route('/leagues', methods=['GET'])
@cache.cached(timeout=600)
def get_league_accuracy():
    """Get accuracy statistics by league."""
    league_stats = db.session.query(
        League.id,
        League.name,
        League.league_type,
        func.count(AccuracyLog.id).label('total'),
        func.sum(case((AccuracyLog.was_correct == True, 1), else_=0)).label('correct')
    ).join(
        Fixture, League.id == Fixture.league_id
    ).join(
        Prediction, Fixture.id == Prediction.fixture_id
    ).join(
        AccuracyLog, Prediction.id == AccuracyLog.prediction_id
    ).group_by(
        League.id, League.name, League.league_type
    ).having(
        func.count(AccuracyLog.id) >= 5  # Minimum 5 predictions
    ).order_by(
        func.count(AccuracyLog.id).desc()
    ).all()

    leagues = []
    for stat in league_stats:
        accuracy = round((stat.correct / stat.total * 100), 1) if stat.total > 0 else 0
        leagues.append({
            'league_id': stat.id,
            'league_name': stat.name,
            'league_type': stat.league_type,
            'total_predictions': stat.total,
            'correct_predictions': stat.correct,
            'accuracy_percentage': accuracy
        })

    return json_success(data={'leagues': leagues})


@accuracy_bp.route('/summary', methods=['GET'])
@cache.cached(timeout=300)
def get_accuracy_summary():
    """Get a quick accuracy summary for display."""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def get_stats(start_date=None):
        query = db.session.query(AccuracyLog)
        if start_date:
            query = query.filter(AccuracyLog.logged_at >= start_date)
        total = query.count()
        correct = query.filter(AccuracyLog.was_correct == True).count()
        return {
            'total': total,
            'correct': correct,
            'accuracy': round((correct / total * 100), 1) if total > 0 else 0
        }

    return json_success(data={
        'today': get_stats(today_start),
        'this_week': get_stats(week_ago),
        'this_month': get_stats(month_ago),
        'all_time': get_stats()
    })
