"""
Cron job endpoints triggered by Vercel Cron.

Vercel sends: Authorization: Bearer <CRON_SECRET>
All endpoints return 200 on success, 401 if secret is wrong.

Schedule (configured in vercel.json) — each endpoint does one thing so it
completes well within Vercel's 10-second serverless function timeout:

  0:00 UTC  — ingest/football, ingest/basketball, ingest/tennis, ingest/stats
  0:05 UTC  — ingest/odds  (slight offset so football data is in DB first)
  1:00 UTC  — predict/1x2, predict/markets
  6:00 UTC  — accuracy
  7:00 UTC  — newsletter

The legacy /ingest endpoint is kept for manual one-shot runs.
"""
import os
import logging
from flask import Blueprint, request, jsonify

cron_bp = Blueprint('cron', __name__)
logger = logging.getLogger(__name__)

CRON_SECRET = os.getenv('CRON_SECRET', '')


def _verify():
    if not CRON_SECRET:
        return True
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {CRON_SECRET}'


# ── Split ingest endpoints ────────────────────────────────────────────────────

@cron_bp.route('/ingest/football', methods=['GET', 'POST'])
def ingest_football():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.football_service import FootballService
        svc = FootballService()
        svc.ingest_leagues()
        count = svc.ingest_fixtures(days_ahead=7)
        logger.info(f'Cron ingest/football: {count} fixtures')
        return jsonify({'ok': True, 'fixtures': count})
    except Exception as e:
        logger.error(f'Cron ingest/football error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@cron_bp.route('/ingest/basketball', methods=['GET', 'POST'])
def ingest_basketball():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.basketball_service import BasketballService
        svc = BasketballService()
        svc.ingest_leagues()
        count = svc.ingest_fixtures(days_ahead=7)
        logger.info(f'Cron ingest/basketball: {count} fixtures')
        return jsonify({'ok': True, 'fixtures': count})
    except Exception as e:
        logger.error(f'Cron ingest/basketball error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@cron_bp.route('/ingest/tennis', methods=['GET', 'POST'])
def ingest_tennis():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.tennis_service import TennisService
        svc = TennisService()
        svc.ingest_leagues()
        count = svc.ingest_fixtures(days_ahead=7)
        logger.info(f'Cron ingest/tennis: {count} fixtures')
        return jsonify({'ok': True, 'fixtures': count})
    except Exception as e:
        logger.error(f'Cron ingest/tennis error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@cron_bp.route('/ingest/odds', methods=['GET', 'POST'])
def ingest_odds():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.odds_service import OddsService
        svc = OddsService()
        football_count = svc.ingest_football_odds()
        basketball_count = svc.ingest_basketball_odds()
        logger.info(f'Cron ingest/odds: {football_count} football, {basketball_count} basketball')
        return jsonify({'ok': True, 'odds_football': football_count, 'odds_basketball': basketball_count})
    except Exception as e:
        logger.error(f'Cron ingest/odds error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@cron_bp.route('/ingest/stats', methods=['GET', 'POST'])
def ingest_stats():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.understat_service import UnderstatService
        count = UnderstatService().ingest_xg_stats()
        logger.info(f'Cron ingest/stats: {count}')
        return jsonify({'ok': True, 'elo_stats': count})
    except Exception as e:
        logger.error(f'Cron ingest/stats error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Split predict endpoints ───────────────────────────────────────────────────

@cron_bp.route('/predict/1x2', methods=['GET', 'POST'])
def predict_1x2():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.prediction_service import PredictionService
        count = PredictionService().generate_predictions_for_upcoming(premium_threshold=0.7)
        logger.info(f'Cron predict/1x2: {count} predictions')
        return jsonify({'ok': True, 'predictions': count})
    except Exception as e:
        logger.error(f'Cron predict/1x2 error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@cron_bp.route('/predict/markets', methods=['GET', 'POST'])
def predict_markets():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.market_prediction_service import MarketPredictionService
        count = MarketPredictionService().generate_all_predictions_for_upcoming(days_ahead=3)
        logger.info(f'Cron predict/markets: {count} market predictions')
        return jsonify({'ok': True, 'market_predictions': count})
    except Exception as e:
        logger.error(f'Cron predict/markets error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Accuracy ──────────────────────────────────────────────────────────────────

@cron_bp.route('/accuracy', methods=['GET', 'POST'])
def accuracy():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..extensions import db
        from ..models.fixture import Fixture
        from ..models.prediction import Prediction
        from ..models.accuracy_log import AccuracyLog
        from ..models.market_prediction import MarketPrediction
        from ..models.market_accuracy_log import MarketAccuracyLog

        finished = Fixture.query.filter_by(status='finished').join(Prediction).filter(
            ~Prediction.id.in_(db.session.query(AccuracyLog.prediction_id))
        ).all()

        logged = 0
        for fixture in finished:
            outcome = fixture.get_actual_outcome()
            if not outcome:
                continue
            prediction = fixture.predictions.first()
            if not prediction:
                continue
            db.session.add(AccuracyLog(
                prediction_id=prediction.id,
                actual_outcome=outcome,
                was_correct=prediction.predicted_outcome == outcome
            ))
            logged += 1

        already_logged = db.session.query(MarketAccuracyLog.market_prediction_id).subquery()
        market_preds = (
            MarketPrediction.query
            .join(Fixture, Fixture.id == MarketPrediction.fixture_id)
            .filter(
                Fixture.status == 'finished',
                Fixture.home_score != None,
                Fixture.away_score != None,
                ~MarketPrediction.id.in_(already_logged)
            )
            .all()
        )

        market_logged = 0
        for mp in market_preds:
            actual = _market_actual_outcome(mp, mp.fixture)
            if actual is None:
                continue
            db.session.add(MarketAccuracyLog(
                market_prediction_id=mp.id,
                actual_outcome=actual,
                was_correct=(mp.predicted_outcome == actual)
            ))
            market_logged += 1

        db.session.commit()
        logger.info(f'Cron accuracy: 1X2={logged}, market={market_logged}')
        return jsonify({'ok': True, 'logged': logged, 'market_logged': market_logged})
    except Exception as e:
        logger.error(f'Accuracy cron error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Newsletter ────────────────────────────────────────────────────────────────

@cron_bp.route('/newsletter', methods=['GET', 'POST'])
def newsletter():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from ..services.mail_service import MailService
        result = MailService().send_newsletter_digest()
        logger.info(f'Cron newsletter: {result}')
        return jsonify({'ok': True, 'result': result})
    except Exception as e:
        logger.error(f'Newsletter cron error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Legacy combined endpoint (kept for manual one-shot runs) ──────────────────

@cron_bp.route('/ingest', methods=['GET', 'POST'])
def ingest():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    results = {}
    try:
        from ..services.football_service import FootballService
        svc = FootballService()
        svc.ingest_leagues()
        results['fixtures'] = svc.ingest_fixtures(days_ahead=7)
    except Exception as e:
        logger.error(f'Ingest fixtures error: {e}')
        results['fixtures'] = str(e)

    try:
        from ..services.odds_service import OddsService
        svc = OddsService()
        results['odds_football'] = svc.ingest_football_odds()
        results['odds_basketball'] = svc.ingest_basketball_odds()
    except Exception as e:
        logger.error(f'Ingest odds error: {e}')
        results['odds'] = str(e)

    try:
        from ..services.basketball_service import BasketballService
        svc = BasketballService()
        svc.ingest_leagues()
        results['basketball'] = svc.ingest_fixtures(days_ahead=7)
    except Exception as e:
        logger.error(f'Ingest basketball error: {e}')
        results['basketball'] = str(e)

    try:
        from ..services.tennis_service import TennisService
        svc = TennisService()
        svc.ingest_leagues()
        results['tennis'] = svc.ingest_fixtures(days_ahead=7)
    except Exception as e:
        logger.error(f'Ingest tennis error: {e}')
        results['tennis'] = str(e)

    try:
        from ..services.understat_service import UnderstatService
        results['elo_stats'] = UnderstatService().ingest_xg_stats()
    except Exception as e:
        logger.error(f'Ingest Elo stats error: {e}')
        results['elo_stats'] = str(e)

    logger.info(f'Cron ingest complete: {results}')
    return jsonify({'ok': True, 'results': results})


@cron_bp.route('/predict', methods=['GET', 'POST'])
def predict():
    if not _verify():
        return jsonify({'error': 'Unauthorized'}), 401
    results = {}
    try:
        from ..services.prediction_service import PredictionService
        results['predictions'] = PredictionService().generate_predictions_for_upcoming(premium_threshold=0.7)
    except Exception as e:
        logger.error(f'Generate predictions error: {e}')
        results['predictions'] = str(e)

    try:
        from ..services.market_prediction_service import MarketPredictionService
        results['market_predictions'] = MarketPredictionService().generate_all_predictions_for_upcoming(days_ahead=3)
    except Exception as e:
        logger.error(f'Generate market predictions error: {e}')
        results['market_predictions'] = str(e)

    logger.info(f'Cron predict complete: {results}')
    return jsonify({'ok': True, 'results': results})


# ── Helper ────────────────────────────────────────────────────────────────────

def _market_actual_outcome(mp, fixture):
    home, away = fixture.home_score, fixture.away_score

    if mp.market_type == 'btts':
        return 'yes' if (home > 0 and away > 0) else 'no'

    if mp.market_type in ('over_under', 'corners'):
        line = mp.line_value
        if line is None:
            return None
        if mp.market_type == 'over_under':
            return 'over' if (home + away) > line else 'under'
        return None

    if mp.market_type == 'double_chance':
        if home > away:
            result = 'home'
        elif away > home:
            result = 'away'
        else:
            result = 'draw'
        if mp.predicted_outcome == '1X':
            return '1X' if result in ('home', 'draw') else 'not_1X'
        if mp.predicted_outcome == 'X2':
            return 'X2' if result in ('draw', 'away') else 'not_X2'
        if mp.predicted_outcome == '12':
            return '12' if result in ('home', 'away') else 'not_12'

    return None
