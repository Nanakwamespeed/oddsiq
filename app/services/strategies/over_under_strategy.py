"""Over/Under goals prediction strategy."""
import logging
from .base_market_strategy import BaseMarketStrategy
from ..prediction_engine import FootballPredictionEngine, poisson_cdf

logger = logging.getLogger(__name__)

_engine = FootballPredictionEngine()


class OverUnderStrategy(BaseMarketStrategy):
    """
    Strategy for Over/Under goals predictions.

    Uses team scoring/conceding averages and historical data
    to predict expected total goals in a match.

    Supported lines: 0.5, 1.5, 2.5, 3.5, 4.5
    """

    SUPPORTED_LINES = [0.5, 1.5, 2.5, 3.5, 4.5]
    DEFAULT_LEAGUE_AVG = 2.5  # Average goals per match

    @property
    def market_type(self) -> str:
        return 'over_under'

    @property
    def market_name(self) -> str:
        return 'Over/Under Goals'

    def get_valid_outcomes(self) -> list:
        return ['over', 'under']

    def calculate_expected_goals(self, fixture):
        """
        Calculate expected goals via the Poisson engine (attack/defense ratings
        normalized against league baselines with home advantage).
        """
        lambda_home, lambda_away = _engine.expected_goals(
            fixture.home_team_id, fixture.away_team_id
        )
        return {
            'expected_total': lambda_home + lambda_away,
            'home_expected': lambda_home,
            'away_expected': lambda_away,
            'home_stats': self.get_team_stats(fixture.home_team_id),
            'away_stats': self.get_team_stats(fixture.away_team_id),
        }

    def calculate_prediction(self, fixture, line_value=2.5, outcome=None, **kwargs):
        """
        Calculate Over/Under prediction for a specific line.

        Args:
            fixture: Fixture model instance
            line_value: The goal line (default 2.5)
            outcome: Specific outcome to predict ('over' or 'under'). If None, predicts the most likely.

        Returns:
            dict with predicted_outcome, confidence_score, etc.
        """
        if line_value not in self.SUPPORTED_LINES:
            line_value = 2.5

        goals_data = self.calculate_expected_goals(fixture)
        expected_total = goals_data['expected_total']

        # Exact Poisson probability: P(total goals > line) = 1 - P(X ≤ floor(line))
        # For half-ball lines (0.5, 1.5 …) floor == int cast is exact.
        p_over = 1.0 - poisson_cdf(int(line_value), expected_total)
        p_under = 1.0 - p_over

        # Optional blend with historical over-rates if available
        home_stats = goals_data['home_stats']
        away_stats = goals_data['away_stats']
        if hasattr(home_stats, 'get_over_percentage'):
            home_over_pct = home_stats.get_over_percentage(line_value) / 100
            away_over_pct = away_stats.get_over_percentage(line_value) / 100
            historical_factor = (home_over_pct + away_over_pct) / 2
            p_over = p_over * 0.70 + historical_factor * 0.30
            p_under = 1.0 - p_over

        over_confidence = max(0.25, min(0.90, p_over))
        under_confidence = max(0.25, min(0.90, p_under))

        # If specific outcome requested, return that
        if outcome == 'over':
            return {
                'predicted_outcome': 'over',
                'confidence_score': over_confidence,
                'model_probability': over_confidence,
                'line_value': line_value,
                'extra_data': {
                    'expected_total': round(expected_total, 2),
                    'over_confidence': round(over_confidence, 3),
                    'under_confidence': round(under_confidence, 3)
                }
            }
        elif outcome == 'under':
            return {
                'predicted_outcome': 'under',
                'confidence_score': under_confidence,
                'model_probability': under_confidence,
                'line_value': line_value,
                'extra_data': {
                    'expected_total': round(expected_total, 2),
                    'over_confidence': round(over_confidence, 3),
                    'under_confidence': round(under_confidence, 3)
                }
            }

        # Default: return the most likely outcome
        if over_confidence > under_confidence:
            predicted_outcome = 'over'
            confidence_score = over_confidence
        else:
            predicted_outcome = 'under'
            confidence_score = under_confidence

        return {
            'predicted_outcome': predicted_outcome,
            'confidence_score': confidence_score,
            'model_probability': confidence_score,
            'line_value': line_value,
            'extra_data': {
                'expected_total': round(expected_total, 2),
                'home_expected': round(goals_data['home_expected'], 2),
                'away_expected': round(goals_data['away_expected'], 2),
                'over_confidence': round(over_confidence, 3),
                'under_confidence': round(under_confidence, 3)
            }
        }

    def calculate_all_outcomes(self, fixture, line_value=2.5):
        """
        Calculate predictions for BOTH over and under for a specific line.

        Returns:
            list of dicts with predictions for both outcomes
        """
        goals_data = self.calculate_expected_goals(fixture)
        expected_total = goals_data['expected_total']

        p_over = 1.0 - poisson_cdf(int(line_value), expected_total)
        p_under = 1.0 - p_over

        home_stats = goals_data['home_stats']
        away_stats = goals_data['away_stats']
        if hasattr(home_stats, 'get_over_percentage'):
            home_over_pct = home_stats.get_over_percentage(line_value) / 100
            away_over_pct = away_stats.get_over_percentage(line_value) / 100
            historical_factor = (home_over_pct + away_over_pct) / 2
            p_over = p_over * 0.70 + historical_factor * 0.30
            p_under = 1.0 - p_over

        over_confidence = max(0.25, min(0.90, p_over))
        under_confidence = max(0.25, min(0.90, p_under))

        return [
            {
                'predicted_outcome': 'over',
                'confidence_score': over_confidence,
                'model_probability': over_confidence,
                'line_value': line_value,
                'extra_data': {'expected_total': round(expected_total, 2)}
            },
            {
                'predicted_outcome': 'under',
                'confidence_score': under_confidence,
                'model_probability': under_confidence,
                'line_value': line_value,
                'extra_data': {'expected_total': round(expected_total, 2)}
            }
        ]

    def generate_predictions_for_all_lines(self, fixture, is_premium=False, lines=None):
        """
        Generate predictions for multiple lines.

        Args:
            fixture: Fixture model instance
            is_premium: Whether to mark as premium
            lines: List of lines to generate (default: [1.5, 2.5, 3.5])

        Returns:
            List of MarketPrediction instances
        """
        if lines is None:
            lines = [1.5, 2.5, 3.5]

        predictions = []
        for line in lines:
            prediction = self.generate_prediction(fixture, is_premium=is_premium, line_value=line)
            if prediction:
                predictions.append(prediction)

        return predictions
