"""
PredictionService — thin wrapper around FootballPredictionEngine.

All existing callers (routes, scheduler, strategies) import PredictionService
and call its public methods.  Internally every call delegates to the new
Poisson-based engine so no call-sites need to change.
"""
import logging
from .prediction_engine import FootballPredictionEngine

logger = logging.getLogger(__name__)

_engine = FootballPredictionEngine()


class PredictionService:
    """
    Public facade for the prediction pipeline.

    Delegates to FootballPredictionEngine for all statistical work.
    Preserved for backward compatibility with routes, scheduler, and strategies.
    """

    def __init__(self):
        self._engine = _engine  # shared stateless instance

    # ── Compatibility shims used by strategies ─────────────────

    def calculate_form_score(self, team_id: int, limit: int = 5) -> float:
        """
        Return a 0-1 form score.

        Used by double_chance_strategy and ht_ft_strategy via
        `pred_service.calculate_form_score(team_id)`.
        Delegates to the engine's recency-weighted attack rating,
        then normalises against the league baseline.
        """
        attack = self._engine.attack_rating(team_id)
        from .prediction_engine import _HOME_BASELINE
        # Normalise: league-average attack → 0.5
        score = attack / (_HOME_BASELINE * 2)
        return round(max(0.0, min(score, 1.0)), 4)

    def calculate_h2h_score(self, home_team_id: int, away_team_id: int, limit: int = 5):
        """
        Return (home_h2h_score, away_h2h_score) in [0, 1].

        Used by double_chance_strategy and ht_ft_strategy.
        """
        from ..models.h2h_record import H2HRecord
        records = H2HRecord.get_h2h_records(home_team_id, away_team_id, limit=limit)
        if not records:
            return 0.5, 0.5
        home_h2h = H2HRecord.calculate_h2h_score(records, home_team_id)
        away_h2h = H2HRecord.calculate_h2h_score(records, away_team_id)
        return home_h2h, away_h2h

    def calculate_confidence_score(self, fixture) -> dict:
        """
        Backward-compat wrapper used by the admin route.

        Returns the same dict shape as the old implementation.
        """
        result = self._engine.predict(fixture)
        probs = result['probabilities']
        return {
            'predicted_outcome': result['predicted_outcome'],
            'confidence_score': result['confidence_score'],
            'home_score': probs.get('home', 0.0),
            'away_score': probs.get('away', 0.0),
        }

    def detect_value_bet(
        self, fixture_id: int, predicted_outcome: str, model_probability: float
    ) -> dict:
        """Backward-compat wrapper."""
        return self._engine.detect_value_bet(fixture_id, predicted_outcome, model_probability)

    # ── Main DB-writing methods ────────────────────────────────

    def generate_prediction(self, fixture, is_premium: bool = False):
        return self._engine.generate_prediction(fixture, is_premium=is_premium)

    def regenerate_prediction(self, fixture, is_premium: bool = False):
        return self._engine.regenerate_prediction(fixture, is_premium=is_premium)

    def generate_predictions_for_upcoming(self, premium_threshold: float = 0.72) -> int:
        return self._engine.generate_predictions_for_upcoming(
            premium_threshold=premium_threshold
        )
