"""Base class for market-specific prediction strategies."""
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseMarketStrategy(ABC):
    """
    Base class for market-specific prediction strategies.

    Each market type (Over/Under, BTTS, Double Chance, etc.) implements
    its own strategy for calculating confidence scores and predictions.
    """

    VALUE_BET_THRESHOLD = 0.05  # 5% edge required for value bet

    @property
    @abstractmethod
    def market_type(self) -> str:
        """Return the market type identifier (e.g., 'over_under', 'btts')."""
        pass

    @property
    @abstractmethod
    def market_name(self) -> str:
        """Return human-readable market name."""
        pass

    @abstractmethod
    def get_valid_outcomes(self) -> list:
        """Return list of valid outcomes for this market."""
        pass

    @abstractmethod
    def calculate_prediction(self, fixture, **kwargs) -> dict:
        """
        Calculate prediction for this market.

        Args:
            fixture: Fixture model instance
            **kwargs: Market-specific parameters (e.g., line_value for O/U)

        Returns:
            dict with keys:
            - predicted_outcome: str
            - confidence_score: float (0.0 to 1.0)
            - model_probability: float (optional)
            - line_value: float (optional, for O/U markets)
            - extra_data: dict (optional, for additional info)
        """
        pass

    def detect_value_bet(self, fixture_id, predicted_outcome, model_probability, line_value=None):
        """
        Detect if prediction represents a value bet.

        Compares model probability against bookmaker implied probability.

        Args:
            fixture_id: ID of the fixture
            predicted_outcome: The predicted outcome
            model_probability: Model's calculated probability (0.0 to 1.0)
            line_value: Line value for O/U markets (optional)

        Returns:
            dict with:
            - is_value_bet: bool
            - edge: float (model_prob - implied_prob)
            - best_odds: float
            - bookmaker: str
        """
        from ...models.market_odds import MarketOdds

        odds_records = MarketOdds.query.filter_by(
            fixture_id=fixture_id,
            market_type=self.market_type
        )

        if line_value is not None:
            odds_records = odds_records.filter_by(line_value=line_value)

        odds_records = odds_records.all()

        if not odds_records:
            return {
                'is_value_bet': False,
                'edge': None,
                'best_odds': None,
                'bookmaker': None
            }

        best_odds = 0
        best_bookmaker = None

        for odds_record in odds_records:
            outcome_odds = odds_record.get_odds_for_outcome(predicted_outcome)
            if outcome_odds and outcome_odds > best_odds:
                best_odds = outcome_odds
                best_bookmaker = odds_record.bookmaker_name

        if best_odds == 0:
            return {
                'is_value_bet': False,
                'edge': None,
                'best_odds': None,
                'bookmaker': None
            }

        implied_probability = 1 / best_odds
        edge = model_probability - implied_probability

        return {
            'is_value_bet': edge > self.VALUE_BET_THRESHOLD,
            'edge': round(edge, 4),
            'best_odds': best_odds,
            'bookmaker': best_bookmaker
        }

    def generate_prediction(self, fixture, is_premium=False, **kwargs):
        """
        Generate and store a prediction for this market.

        Args:
            fixture: Fixture model instance
            is_premium: Whether to mark as premium prediction
            **kwargs: Market-specific parameters

        Returns:
            MarketPrediction instance or None if prediction couldn't be generated
        """
        from ...extensions import db
        from ...models.market_prediction import MarketPrediction

        try:
            # Calculate prediction
            result = self.calculate_prediction(fixture, **kwargs)

            if not result or not result.get('predicted_outcome'):
                return None

            predicted_outcome = result['predicted_outcome']
            confidence_score = result.get('confidence_score', 0.5)
            model_probability = result.get('model_probability', confidence_score)
            line_value = result.get('line_value')

            # Check for existing prediction
            existing = MarketPrediction.query.filter_by(
                fixture_id=fixture.id,
                market_type=self.market_type,
                line_value=line_value,
                predicted_outcome=predicted_outcome
            ).first()

            # Detect value bet
            value_bet_result = self.detect_value_bet(
                fixture.id,
                predicted_outcome,
                model_probability,
                line_value
            )

            if existing:
                existing.confidence_score = confidence_score
                existing.model_probability = model_probability
                existing.is_value_bet = value_bet_result['is_value_bet']
                existing.value_edge = value_bet_result['edge']
                existing.is_premium = is_premium or confidence_score >= 0.75
                return existing

            # Create prediction
            prediction = MarketPrediction(
                fixture_id=fixture.id,
                market_type=self.market_type,
                predicted_outcome=predicted_outcome,
                line_value=line_value,
                confidence_score=confidence_score,
                model_probability=model_probability,
                is_value_bet=value_bet_result['is_value_bet'],
                value_edge=value_bet_result['edge'],
                is_premium=is_premium or confidence_score >= 0.75  # High confidence = premium
            )

            db.session.add(prediction)
            return prediction

        except Exception as e:
            logger.error(f"Failed to generate {self.market_type} prediction: {e}")
            return None

    def generate_all_predictions(self, fixture, is_premium=False, **kwargs):
        """
        Generate and store predictions for ALL outcomes of this market.

        Requires the strategy to implement calculate_all_outcomes() method.

        Args:
            fixture: Fixture model instance
            is_premium: Whether to mark as premium prediction
            **kwargs: Market-specific parameters

        Returns:
            List of MarketPrediction instances
        """
        from ...extensions import db
        from ...models.market_prediction import MarketPrediction

        if not hasattr(self, 'calculate_all_outcomes'):
            # Fallback to single prediction
            pred = self.generate_prediction(fixture, is_premium=is_premium, **kwargs)
            return [pred] if pred else []

        try:
            # Calculate predictions for all outcomes
            results = self.calculate_all_outcomes(fixture, **kwargs)

            if not results:
                return []

            predictions = []
            for result in results:
                predicted_outcome = result['predicted_outcome']
                confidence_score = result.get('confidence_score', 0.5)
                model_probability = result.get('model_probability', confidence_score)
                line_value = result.get('line_value')

                # Check for existing prediction for this specific outcome
                existing = MarketPrediction.query.filter_by(
                    fixture_id=fixture.id,
                    market_type=self.market_type,
                    line_value=line_value,
                    predicted_outcome=predicted_outcome
                ).first()

                # Detect value bet
                value_bet_result = self.detect_value_bet(
                    fixture.id,
                    predicted_outcome,
                    model_probability,
                    line_value
                )

                if existing:
                    existing.confidence_score = confidence_score
                    existing.model_probability = model_probability
                    existing.is_value_bet = value_bet_result['is_value_bet']
                    existing.value_edge = value_bet_result['edge']
                    existing.is_premium = is_premium or confidence_score >= 0.75
                    predictions.append(existing)
                    continue

                # Create prediction
                prediction = MarketPrediction(
                    fixture_id=fixture.id,
                    market_type=self.market_type,
                    predicted_outcome=predicted_outcome,
                    line_value=line_value,
                    confidence_score=confidence_score,
                    model_probability=model_probability,
                    is_value_bet=value_bet_result['is_value_bet'],
                    value_edge=value_bet_result['edge'],
                    is_premium=is_premium or confidence_score >= 0.75
                )

                db.session.add(prediction)
                predictions.append(prediction)

            return predictions

        except Exception as e:
            logger.error(f"Failed to generate all {self.market_type} predictions: {e}")
            return []

    def get_team_stats(self, team_id, season='2024-25'):
        """
        Get team statistics for prediction calculations.

        Returns default values if no stats exist.
        """
        from ...models.team_stats import TeamStats

        stats = TeamStats.query.filter_by(team_id=team_id, season=season).first()

        if stats:
            return stats

        # Return default stats object with proper method signatures
        class DefaultStats:
            matches_played = 0
            goals_scored = 0
            goals_conceded = 0
            avg_goals_scored = 1.3  # League average
            avg_goals_conceded = 1.3
            btts_yes_count = 0
            btts_percentage = 50.0
            clean_sheets = 0
            failed_to_score = 0
            over_2_5_count = 0
            over_1_5_count = 0
            avg_corners_for = 5.0
            avg_corners_against = 5.0
            ht_winning_count = 0
            ht_drawing_count = 0
            ht_losing_count = 0

            def get_scoring_rate(self):
                return 70.0

            def get_clean_sheet_rate(self):
                return 30.0

            def get_over_percentage(self, line):
                return 50.0

            def get_ht_lead_rate(self):
                return 30.0

        return DefaultStats()
