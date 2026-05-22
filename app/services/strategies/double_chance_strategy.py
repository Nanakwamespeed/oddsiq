"""Double Chance prediction strategy."""
import logging
from .base_market_strategy import BaseMarketStrategy
from ..prediction_engine import FootballPredictionEngine

logger = logging.getLogger(__name__)

_engine = FootballPredictionEngine()


class DoubleChanceStrategy(BaseMarketStrategy):
    """
    Strategy for Double Chance predictions.

    Double Chance covers two of three outcomes:
    - 1X: Home win OR Draw
    - X2: Draw OR Away win
    - 12: Home win OR Away win (no draw)

    Uses the existing 1X2 prediction logic to calculate
    individual probabilities, then combines them.
    """

    @property
    def market_type(self) -> str:
        return 'double_chance'

    @property
    def market_name(self) -> str:
        return 'Double Chance'

    def get_valid_outcomes(self) -> list:
        return ['1X', 'X2', '12']

    def get_1x2_probabilities(self, fixture):
        """
        Return calibrated H/D/A probabilities from the Poisson engine.
        """
        try:
            result = _engine.predict(fixture)
            probs = result['probabilities']
            return {
                'home': probs.get('home', 0.40),
                'draw': probs.get('draw', 0.25),
                'away': probs.get('away', 0.35),
            }
        except Exception as e:
            logger.error(f"Failed to get 1X2 probabilities: {e}")
            return {'home': 0.40, 'draw': 0.25, 'away': 0.35}

    def _calculate_confidence_for_probability(self, probability):
        """Convert raw probability to confidence score."""
        # Double chance typically has high confidence since it covers 2 outcomes
        if probability >= 0.70:
            confidence_score = 0.70 + (probability - 0.70) * 0.5
        elif probability >= 0.60:
            confidence_score = 0.60 + (probability - 0.60)
        else:
            confidence_score = 0.50 + (probability - 0.50) * 0.8

        # Cap between 0.55 and 0.85
        return max(0.55, min(0.85, confidence_score))

    def calculate_prediction(self, fixture, outcome=None, **kwargs):
        """
        Calculate Double Chance prediction.

        Args:
            fixture: Fixture model instance
            outcome: Specific outcome to predict ('1X', 'X2', '12'). If None, predicts the most likely.

        Returns:
            dict with predicted_outcome, confidence_score, etc.
        """
        probs = self.get_1x2_probabilities(fixture)

        # Calculate double chance probabilities
        dc_1x = probs['home'] + probs['draw']  # Home or Draw
        dc_x2 = probs['draw'] + probs['away']  # Draw or Away
        dc_12 = probs['home'] + probs['away']  # Home or Away

        double_chances = {
            '1X': dc_1x,
            'X2': dc_x2,
            '12': dc_12
        }

        extra_data = {
            '1X_probability': round(dc_1x * 100, 1),
            'X2_probability': round(dc_x2 * 100, 1),
            '12_probability': round(dc_12 * 100, 1),
            'home_probability': round(probs['home'] * 100, 1),
            'draw_probability': round(probs['draw'] * 100, 1),
            'away_probability': round(probs['away'] * 100, 1)
        }

        # If specific outcome requested, return that
        if outcome in double_chances:
            probability = double_chances[outcome]
            confidence_score = self._calculate_confidence_for_probability(probability)
            return {
                'predicted_outcome': outcome,
                'confidence_score': confidence_score,
                'model_probability': probability,
                'line_value': None,
                'extra_data': extra_data
            }

        # Default: return the most likely outcome
        best_outcome = max(double_chances, key=double_chances.get)
        best_probability = double_chances[best_outcome]
        confidence_score = self._calculate_confidence_for_probability(best_probability)

        return {
            'predicted_outcome': best_outcome,
            'confidence_score': confidence_score,
            'model_probability': best_probability,
            'line_value': None,
            'extra_data': extra_data
        }

    def calculate_all_outcomes(self, fixture):
        """
        Calculate predictions for ALL three double chance options.

        Returns:
            list of dicts with predictions for 1X, X2, and 12
        """
        probs = self.get_1x2_probabilities(fixture)

        # Calculate double chance probabilities
        dc_1x = probs['home'] + probs['draw']  # Home or Draw
        dc_x2 = probs['draw'] + probs['away']  # Draw or Away
        dc_12 = probs['home'] + probs['away']  # Home or Away

        double_chances = {
            '1X': dc_1x,
            'X2': dc_x2,
            '12': dc_12
        }

        extra_data = {
            '1X_probability': round(dc_1x * 100, 1),
            'X2_probability': round(dc_x2 * 100, 1),
            '12_probability': round(dc_12* 100, 1),
            'home_probability': round(probs['home'] * 100, 1),
            'draw_probability': round(probs['draw'] * 100, 1),
            'away_probability': round(probs['away'] * 100, 1)
        }

        results = []
        for outcome, probability in double_chances.items():
            confidence_score = self._calculate_confidence_for_probability(probability)
            results.append({
                'predicted_outcome': outcome,
                'confidence_score': confidence_score,
                'model_probability': probability,
                'line_value': None,
                'extra_data': extra_data
            })

        return results

    def get_outcome_description(self, outcome):
        """Get human-readable description of the outcome."""
        descriptions = {
            '1X': 'Home Win or Draw',
            'X2': 'Draw or Away Win',
            '12': 'Home Win or Away Win'
        }
        return descriptions.get(outcome, outcome)
