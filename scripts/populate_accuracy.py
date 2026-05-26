#!/usr/bin/env python3
"""Populate accuracy_log for all finished fixtures that have predictions."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
os.environ['VERCEL'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.fixture import Fixture
from app.models.prediction import Prediction
from app.models.accuracy_log import AccuracyLog

app = create_app()

with app.app_context():
    # Find finished fixtures that have predictions but no accuracy log yet
    logged_ids = db.session.query(AccuracyLog.prediction_id).subquery()
    fixtures = (
        Fixture.query
        .filter_by(status='finished')
        .join(Prediction)
        .filter(~Prediction.id.in_(db.session.query(AccuracyLog.prediction_id)))
        .all()
    )

    print(f'Found {len(fixtures)} finished fixtures with unlogged predictions')

    logged = 0
    skipped = 0
    for fixture in fixtures:
        outcome = fixture.get_actual_outcome()
        if not outcome:
            skipped += 1
            continue
        prediction = fixture.predictions.first()
        if not prediction:
            skipped += 1
            continue
        db.session.add(AccuracyLog(
            prediction_id=prediction.id,
            actual_outcome=outcome,
            was_correct=(prediction.predicted_outcome == outcome)
        ))
        logged += 1

    db.session.commit()

    total = AccuracyLog.query.count()
    correct = AccuracyLog.query.filter_by(was_correct=True).count()
    pct = round(correct / total * 100, 1) if total > 0 else 0

    print(f'Logged: {logged} | Skipped (no score/prediction): {skipped}')
    print(f'Total accuracy logs: {total}')
    print(f'Accuracy: {correct}/{total} = {pct}%')
