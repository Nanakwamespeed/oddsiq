"""
APScheduler job definitions for data ingestion and processing.

Jobs:
1. ingest_football_fixtures - Every 6 hours
2. ingest_football_form - Every 6 hours
3. ingest_odds - Every 6 hours (conserve 500 req/month free tier)
4. ingest_basketball - Every 6 hours
5. ingest_tennis - Every 6 hours
6. generate_predictions - Every 6 hours (1X2)
7. generate_market_predictions - Every 6 hours (O/U, BTTS, DC, corners, HT/FT)
8. send_newsletter_digest - Daily at 7AM UTC
9. log_accuracy - Every 3 hours
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def register_jobs(scheduler, app):
    """Register all scheduled jobs with the APScheduler."""

    # Job 1: Ingest football fixtures (every 6 hours)
    @scheduler.scheduled_job('interval', hours=6, id='ingest_football_fixtures', next_run_time=datetime.now())
    def ingest_football_fixtures():
        """Fetch upcoming fixtures from API-Football."""
        with app.app_context():
            try:
                from ..services.football_service import FootballService
                service = FootballService()
                service.ingest_leagues()
                count = service.ingest_fixtures(days_ahead=7)
                logger.info(f'Ingested {count} football fixtures')
            except Exception as e:
                logger.error(f'Failed to ingest football fixtures: {e}')

    # Job 2: Ingest football team form (every 6 hours)
    @scheduler.scheduled_job('interval', hours=6, id='ingest_football_form')
    def ingest_football_form():
        """Fetch last 5 match results per team."""
        with app.app_context():
            try:
                from ..services.football_service import FootballService
                from ..models.team import Team
                from ..models.league import League
                from ..models.sport import Sport

                service = FootballService()

                # Get all football teams
                football_sport = Sport.query.filter_by(name='football').first()
                if not football_sport:
                    return

                leagues = League.query.filter_by(sport_id=football_sport.id).all()
                total_form_records = 0

                for league in leagues:
                    teams = Team.query.filter_by(league_id=league.id).all()
                    for team in teams:
                        if team.external_id:
                            count = service.ingest_team_form(team.external_id, limit=5)
                            total_form_records += count

                logger.info(f'Ingested {total_form_records} football form records')
            except Exception as e:
                logger.error(f'Failed to ingest football form: {e}')

    # Job 3: Ingest odds (every 6 hours — conserve 500 req/month free tier)
    @scheduler.scheduled_job('interval', hours=6, id='ingest_odds', next_run_time=datetime.now())
    def ingest_odds():
        """Fetch latest odds from The Odds API."""
        with app.app_context():
            try:
                from ..services.odds_service import OddsService
                service = OddsService()

                # Football odds
                football_count = service.ingest_football_odds()

                # Basketball odds
                basketball_count = service.ingest_basketball_odds()

                logger.info(f'Ingested odds: {football_count} football, {basketball_count} basketball')
            except Exception as e:
                logger.error(f'Failed to ingest odds: {e}')

    # Job 4: Ingest basketball data (every 6 hours)
    @scheduler.scheduled_job('interval', hours=6, id='ingest_basketball', next_run_time=datetime.now())
    def ingest_basketball():
        """Fetch upcoming basketball games from ESPN."""
        with app.app_context():
            try:
                from ..services.basketball_service import BasketballService
                service = BasketballService()

                # Ensure leagues exist
                service.ingest_leagues()

                # Ingest fixtures
                count = service.ingest_fixtures(days_ahead=7)
                logger.info(f'Ingested {count} basketball fixtures')
            except Exception as e:
                logger.error(f'Failed to ingest basketball data: {e}')

    # Job 5: Ingest tennis data (every 6 hours)
    @scheduler.scheduled_job('interval', hours=6, id='ingest_tennis', next_run_time=datetime.now())
    def ingest_tennis():
        """Fetch upcoming ATP/WTA matches from ESPN."""
        with app.app_context():
            try:
                from ..services.tennis_service import TennisService
                service = TennisService()

                # Ensure leagues exist
                service.ingest_leagues()

                # Ingest fixtures
                count = service.ingest_fixtures(days_ahead=7)
                logger.info(f'Ingested {count} tennis fixtures')
            except Exception as e:
                logger.error(f'Failed to ingest tennis data: {e}')

    # Job 6: Generate predictions (every 6 hours)
    @scheduler.scheduled_job('interval', hours=6, id='generate_predictions', next_run_time=datetime.now())
    def generate_predictions():
        """Run prediction engine on all upcoming fixtures without predictions."""
        with app.app_context():
            try:
                from ..services.prediction_service import PredictionService
                service = PredictionService()

                count = service.generate_predictions_for_upcoming(premium_threshold=0.7)
                logger.info(f'Generated {count} new predictions')
            except Exception as e:
                logger.error(f'Failed to generate predictions: {e}')

    # Job 7: Generate market predictions (every 6 hours, runs after 1X2 predictions)
    @scheduler.scheduled_job('interval', hours=6, id='generate_market_predictions', next_run_time=datetime.now())
    def generate_market_predictions():
        """Run market prediction engine (O/U, BTTS, Double Chance, Corners, HT/FT)."""
        with app.app_context():
            try:
                from ..services.market_prediction_service import MarketPredictionService
                service = MarketPredictionService()
                count = service.generate_all_predictions_for_upcoming(days_ahead=3)
                logger.info(f'Generated {count} market predictions')
            except Exception as e:
                logger.error(f'Failed to generate market predictions: {e}')

    # Job 8: Send newsletter digest (daily at 7AM UTC)
    @scheduler.scheduled_job('cron', hour=7, minute=0, id='send_newsletter_digest')
    def send_newsletter_digest():
        """Email top 3 picks to all active newsletter subscribers."""
        with app.app_context():
            try:
                from ..services.mail_service import MailService
                service = MailService()

                result = service.send_newsletter_digest()
                logger.info(f'Newsletter digest sent: {result["sent"]} emails')
            except Exception as e:
                logger.error(f'Failed to send newsletter digest: {e}')

    # Job 9: Log accuracy (every 3 hours)
    @scheduler.scheduled_job('interval', hours=3, id='log_accuracy')
    def log_accuracy():
        """Check finished fixtures and log actual outcomes vs predictions."""
        with app.app_context():
            try:
                from ..extensions import db
                from ..models.fixture import Fixture
                from ..models.prediction import Prediction
                from ..models.accuracy_log import AccuracyLog

                # Get finished fixtures with predictions but no accuracy log
                finished_fixtures = Fixture.query.filter_by(status='finished').join(
                    Prediction
                ).filter(
                    ~Prediction.id.in_(
                        db.session.query(AccuracyLog.prediction_id)
                    )
                ).all()

                logged = 0
                for fixture in finished_fixtures:
                    actual_outcome = fixture.get_actual_outcome()
                    if not actual_outcome:
                        continue

                    prediction = fixture.predictions.first()
                    if not prediction:
                        continue

                    was_correct = prediction.predicted_outcome == actual_outcome

                    accuracy_log = AccuracyLog(
                        prediction_id=prediction.id,
                        actual_outcome=actual_outcome,
                        was_correct=was_correct
                    )
                    db.session.add(accuracy_log)
                    logged += 1

                db.session.commit()
                logger.info(f'Logged accuracy for {logged} predictions')
            except Exception as e:
                logger.error(f'Failed to log accuracy: {e}')

    logger.info('All scheduler jobs registered')


def run_job_manually(job_id, app):
    """
    Run a specific job manually for testing/debugging.

    Usage:
        from app.tasks.scheduler import run_job_manually
        run_job_manually('ingest_football_fixtures', app)
    """
    job_functions = {
        'ingest_football_fixtures': lambda: _run_ingest_football_fixtures(app),
        'ingest_football_form': lambda: _run_ingest_football_form(app),
        'ingest_odds': lambda: _run_ingest_odds(app),
        'ingest_basketball': lambda: _run_ingest_basketball(app),
        'ingest_tennis': lambda: _run_ingest_tennis(app),
        'generate_predictions': lambda: _run_generate_predictions(app),
        'generate_market_predictions': lambda: _run_generate_market_predictions(app),
        'send_newsletter_digest': lambda: _run_send_newsletter(app),
        'log_accuracy': lambda: _run_log_accuracy(app),
    }

    if job_id not in job_functions:
        raise ValueError(f'Unknown job: {job_id}')

    return job_functions[job_id]()


def _run_ingest_football_fixtures(app):
    with app.app_context():
        from ..services.football_service import FootballService
        service = FootballService()
        service.ingest_leagues()
        return service.ingest_fixtures(days_ahead=7)


def _run_ingest_football_form(app):
    with app.app_context():
        from ..services.football_service import FootballService
        from ..models.team import Team
        from ..models.league import League
        from ..models.sport import Sport

        service = FootballService()
        football_sport = Sport.query.filter_by(name='football').first()
        if not football_sport:
            return 0

        total = 0
        leagues = League.query.filter_by(sport_id=football_sport.id).all()
        for league in leagues:
            teams = Team.query.filter_by(league_id=league.id).all()
            for team in teams:
                if team.external_id:
                    total += service.ingest_team_form(team.external_id)
        return total


def _run_ingest_odds(app):
    with app.app_context():
        from ..services.odds_service import OddsService
        service = OddsService()
        return service.ingest_football_odds() + service.ingest_basketball_odds()


def _run_ingest_basketball(app):
    with app.app_context():
        from ..services.basketball_service import BasketballService
        service = BasketballService()
        service.ingest_leagues()
        return service.ingest_fixtures(days_ahead=7)


def _run_ingest_tennis(app):
    with app.app_context():
        from ..services.tennis_service import TennisService
        service = TennisService()
        service.ingest_leagues()
        return service.ingest_fixtures(days_ahead=7)


def _run_generate_predictions(app):
    with app.app_context():
        from ..services.prediction_service import PredictionService
        service = PredictionService()
        return service.generate_predictions_for_upcoming()


def _run_generate_market_predictions(app):
    with app.app_context():
        from ..services.market_prediction_service import MarketPredictionService
        service = MarketPredictionService()
        return service.generate_all_predictions_for_upcoming(days_ahead=3)


def _run_send_newsletter(app):
    with app.app_context():
        from ..services.mail_service import MailService
        service = MailService()
        return service.send_newsletter_digest()


def _run_log_accuracy(app):
    with app.app_context():
        from ..extensions import db
        from ..models.fixture import Fixture
        from ..models.prediction import Prediction
        from ..models.accuracy_log import AccuracyLog

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

            log = AccuracyLog(
                prediction_id=prediction.id,
                actual_outcome=outcome,
                was_correct=prediction.predicted_outcome == outcome
            )
            db.session.add(log)
            logged += 1

        db.session.commit()
        return logged
