"""Both Teams To Score (BTTS) prediction strategy."""
import math
import logging
from .base_market_strategy import BaseMarketStrategy
from ..prediction_engine import FootballPredictionEngine

logger = logging.getLogger(__name__)

_engine = FootballPredictionEngine()


class BTTSStrategy(BaseMarketStrategy):
    """
    Strategy for Both Teams To Score predictions.

    Calculates probability based on:
    - Team scoring rates (% of matches where team scores)
    - Team clean sheet rates (% of matches with no goals conceded)
    - Historical BTTS percentages
    """

    @property
    def market_type(self) -> str:
        return 'btts'

    @property
    def market_name(self) -> str:
        return 'Both Teams To Score'

    def get_valid_outcomes(self) -> list:
        return ['yes', 'no']

    def calculate_btts_probability(self, fixture):
        """
        Calculate BTTS probability using Poisson expected-goals model.

        P(home scores ≥ 1) = 1 − e^{−λ_home}
        P(away scores ≥ 1) = 1 − e^{−λ_away}
        P(BTTS) = P(home scores) × P(away scores)

        Optionally blended with historical BTTS rates when available.
        """
        lambda_home, lambda_away = _engine.expected_goals(
            fixture.home_team_id, fixture.away_team_id
        )

        p_home_scores = 1.0 - math.exp(-lambda_home)
        p_away_scores = 1.0 - math.exp(-lambda_away)
        btts_probability = p_home_scores * p_away_scores

        # Optional blend with historical BTTS rates
        home_stats = self.get_team_stats(fixture.home_team_id)
        away_stats = self.get_team_stats(fixture.away_team_id)
        if hasattr(home_stats, 'btts_percentage') and getattr(home_stats, 'matches_played', 0) > 0:
            home_btts_rate = home_stats.btts_percentage / 100
            away_btts_rate = getattr(away_stats, 'btts_percentage', 50) / 100
            historical_btts = (home_btts_rate + away_btts_rate) / 2
            btts_probability = btts_probability * 0.65 + historical_btts * 0.35

        return {
            'btts_probability': btts_probability,
            'home_scoring_rate': p_home_scores,
            'away_scoring_rate': p_away_scores,
        }

    def _calculate_confidence_from_probability(self, probability, outcome):
        """Convert raw probability to confidence score based on outcome."""
        if outcome == 'yes':
            if probability > 0.5:
                raw_confidence = 0.50 + (probability - 0.5) * 0.70
            else:
                raw_confidence = 0.40 + probability * 0.20
        else:  # 'no'
            no_probability = 1 - probability
            if no_probability > 0.5:
                raw_confidence = 0.50 + (no_probability - 0.5) * 0.70
            else:
                raw_confidence = 0.40 + no_probability * 0.20

        # Cap confidence between 0.40 and 0.80
        return max(0.40, min(0.80, raw_confidence))

    def calculate_prediction(self, fixture, outcome=None, **kwargs):
        """
        Calculate BTTS prediction.

        Args:
            fixture: Fixture model instance
            outcome: Specific outcome to predict ('yes' or 'no'). If None, predicts the most likely.

        Returns:
            dict with predicted_outcome ('yes' or 'no'), confidence_score, etc.
        """
        btts_data = self.calculate_btts_probability(fixture)
        btts_prob = btts_data['btts_probability']

        extra_data = {
            'btts_probability': round(btts_prob * 100, 1),
            'no_btts_probability': round((1 - btts_prob) * 100, 1),
            'home_scoring_chance': round(btts_data['home_scoring_rate'] * 100, 1),
            'away_scoring_chance': round(btts_data['away_scoring_rate'] * 100, 1)
        }

        # If specific outcome requested, return that
        if outcome == 'yes':
            confidence_score = self._calculate_confidence_from_probability(btts_prob, 'yes')
            return {
                'predicted_outcome': 'yes',
                'confidence_score': confidence_score,
                'model_probability': btts_prob,
                'line_value': None,
                'extra_data': extra_data
            }
        elif outcome == 'no':
            confidence_score = self._calculate_confidence_from_probability(btts_prob, 'no')
            return {
                'predicted_outcome': 'no',
                'confidence_score': confidence_score,
                'model_probability': 1 - btts_prob,
                'line_value': None,
                'extra_data': extra_data
            }

        # Default: return the most likely outcome
        if btts_prob > 0.5:
            predicted_outcome = 'yes'
            confidence_score = self._calculate_confidence_from_probability(btts_prob, 'yes')
            model_probability = btts_prob
        else:
            predicted_outcome = 'no'
            confidence_score = self._calculate_confidence_from_probability(btts_prob, 'no')
            model_probability = 1 - btts_prob

        return {
            'predicted_outcome': predicted_outcome,
            'confidence_score': confidence_score,
            'model_probability': model_probability,
            'line_value': None,
            'extra_data': extra_data
        }

    def calculate_all_outcomes(self, fixture):
        """
        Calculate predictions for BOTH BTTS yes and no.

        Returns:
            list of dicts with predictions for both outcomes
        """
        btts_data = self.calculate_btts_probability(fixture)
        btts_prob = btts_data['btts_probability']

        extra_data = {
            'btts_probability': round(btts_prob * 100, 1),
            'no_btts_probability': round((1 - btts_prob) * 100, 1),
            'home_scoring_chance': round(btts_data['home_scoring_rate'] * 100, 1),
            'away_scoring_chance': round(btts_data['away_scoring_rate'] * 100, 1)
        }

        yes_confidence = self._calculate_confidence_from_probability(btts_prob, 'yes')
        no_confidence = self._calculate_confidence_from_probability(btts_prob, 'no')

        return [
            {
                'predicted_outcome': 'yes',
                'confidence_score': yes_confidence,
                'model_probability': btts_prob,
                'line_value': None,
                'extra_data': extra_data
            },
            {
                'predicted_outcome': 'no',
                'confidence_score': no_confidence,
                'model_probability': 1 - btts_prob,
                'line_value': None,
                'extra_data': extra_data
            }
        ]
