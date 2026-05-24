#!/usr/bin/env python3
"""Regenerate market predictions (value bets need real odds in DB first)."""
import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

os.environ['VERCEL'] = '1'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    from app.models.fixture import Fixture
    from app.models.market_prediction import MarketPrediction

    # Delete existing upcoming predictions so they get regenerated with fresh value bet detection
    upcoming_fixture_ids = [
        f.id for f in Fixture.query.filter_by(status='upcoming').all()
    ]
    deleted = MarketPrediction.query.filter(
        MarketPrediction.fixture_id.in_(upcoming_fixture_ids)
    ).delete(synchronize_session=False)
    db.session.commit()
    print(f'Deleted {deleted} existing upcoming market predictions')

    from app.services.market_prediction_service import MarketPredictionService
    result = MarketPredictionService().generate_all_predictions_for_upcoming(days_ahead=7)
    print(f'Generated: {result}')
