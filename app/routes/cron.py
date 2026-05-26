"""
Cron job endpoints triggered by Vercel Cron.

Vercel sends: Authorization: Bearer <CRON_SECRET>
All endpoints return 200 on success, 401 if secret is wrong.

Schedule (configured in vercel.json):
  - /api/cron/ingest        every 6h  — fixtures, form, odds, basketball, tennis
  - /api/cron/predict       every 6h  — 1X2 + market predictions
  - /api/cron/accuracy      every 3h  — log outcomes vs predictions
  - /api/cron/newsletter    daily 7AM — email digest to subscribers
"""
import os
import logging
from flask import Blueprint, request, jsonify

cron_bp = Blueprint('cron', __name__)
logger = logging.getLogger(__name__)

CRON_SECRET = os.getenv('CRON_SECRET', '')


def _verify():
    # If no secret configured, allow all (Vercel controls who can call these endpoints)
    if not CRON_SECRET:
        return True
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {CRON_SECRET}'


@cron_bp.route('/ingest', methods=['POST'])
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

    logger.info(f'Cron ingest complete: {results}')
    return jsonify({'ok': True, 'results': results})


@cron_bp.route('/predict', methods=['POST'])
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


@cron_bp.route('/accuracy', methods=['POST'])
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

        # ── 1X2 predictions ──────────────────────────────────────────
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

        # ── Market predictions (BTTS, O/U, Double Chance) ────────────
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
            fixture = mp.fixture
            actual = _market_actual_outcome(mp, fixture)
            if actual is None:
                continue  # Can't verify (corners, HT/FT — no score data)
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


def _market_actual_outcome(mp, fixture):
    """
    Derive the actual outcome for a market prediction from final scores.
    Returns the outcome string, or None if we can't verify (e.g. corners).
    """
    home, away = fixture.home_score, fixture.away_score

    if mp.market_type == 'btts':
        return 'yes' if (home > 0 and away > 0) else 'no'

    if mp.market_type in ('over_under', 'corners'):
        line = mp.line_value
        if line is None:
            return None
        if mp.market_type == 'over_under':
            return 'over' if (home + away) > line else 'under'
        # Corners: no data available
        return None

    if mp.market_type == 'double_chance':
        if home > away:
            result = 'home'
        elif away > home:
            result = 'away'
        else:
            result = 'draw'
        if mp.predicted_outcome == '1X':
            actual = '1X' if result in ('home', 'draw') else 'X2'
        elif mp.predicted_outcome == 'X2':
            actual = 'X2' if result in ('draw', 'away') else '1X'
        elif mp.predicted_outcome == '12':
            actual = '12' if result in ('home', 'away') else 'draw_draw'
        else:
            return None
        # Simplify: just return whether the predicted DC outcome was correct
        if mp.predicted_outcome == '1X':
            return '1X' if result in ('home', 'draw') else 'not_1X'
        if mp.predicted_outcome == 'X2':
            return 'X2' if result in ('draw', 'away') else 'not_X2'
        if mp.predicted_outcome == '12':
            return '12' if result in ('home', 'away') else 'not_12'

    # HT/FT: can't verify from full-time scores alone
    return None


@cron_bp.route('/newsletter', methods=['POST'])
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
