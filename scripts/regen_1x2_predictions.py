#!/usr/bin/env python3
"""Regenerate 1X2 predictions for all upcoming fixtures using the improved engine."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
os.environ['VERCEL'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    from app.models.fixture import Fixture
    from app.models.prediction import Prediction
    from app.services.prediction_engine import FootballPredictionEngine

    # Delete existing upcoming 1X2 predictions
    upcoming_ids = [f.id for f in Fixture.query.filter_by(status='upcoming').all()]
    deleted = Prediction.query.filter(
        Prediction.fixture_id.in_(upcoming_ids)
    ).delete(synchronize_session=False)
    db.session.commit()
    print(f'Deleted {deleted} existing upcoming 1X2 predictions')

    engine = FootballPredictionEngine()
    generated = engine.generate_predictions_for_upcoming(premium_threshold=0.72)
    print(f'Generated {generated} 1X2 predictions')

    # Summary stats
    total = Prediction.query.filter(Prediction.fixture_id.in_(upcoming_ids)).count()
    value = Prediction.query.filter(
        Prediction.fixture_id.in_(upcoming_ids),
        Prediction.is_value_bet == True
    ).count()
    print(f'Total predictions: {total}  |  Value bets: {value}')
