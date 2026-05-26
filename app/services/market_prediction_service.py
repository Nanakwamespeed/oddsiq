"""Market prediction service factory."""
import logging
from datetime import datetime
from ..extensions import db
from ..models.fixture import Fixture
from ..models.market_prediction import MarketPrediction
from ..models.team_stats import TeamStats
from ..models.form_record import FormRecord

from .strategies.over_under_strategy import OverUnderStrategy
from .strategies.btts_strategy import BTTSStrategy
from .strategies.double_chance_strategy import DoubleChanceStrategy
from .strategies.corners_strategy import CornersStrategy
from .strategies.ht_ft_strategy import HTFTStrategy

logger = logging.getLogger(__name__)


class MarketPredictionService:
    """
    Factory service for generating predictions across all betting markets.

    Supports:
    - Over/Under Goals (multiple lines: 1.5, 2.5, 3.5)
    - Both Teams To Score (BTTS)
    - Double Chance (1X, X2, 12)
    - Corners Over/Under
    - Half-time/Full-time

    Usage:
        service = MarketPredictionService()
        service.generate_all_predictions_for_upcoming()
    """

    def __init__(self):
        self.strategies = {
            'over_under': OverUnderStrategy(),
            'btts': BTTSStrategy(),
            'double_chance': DoubleChanceStrategy(),
            'corners': CornersStrategy(),
            'ht_ft': HTFTStrategy(),
        }

    def get_strategy(self, market_type):
        """Get strategy for a specific market type."""
        return self.strategies.get(market_type)

    def generate_predictions_for_fixture(self, fixture, markets=None, is_premium=False):
        """
        Generate predictions for all markets for a single fixture.

        Args:
            fixture: Fixture model instance
            markets: List of market types to generate (default: all)
            is_premium: Whether to mark predictions as premium

        Returns:
            dict with market_type -> prediction mappings
        """
        if markets is None:
            markets = list(self.strategies.keys())

        predictions = {}

        for market_type in markets:
            strategy = self.get_strategy(market_type)
            if not strategy:
                continue

            try:
                if market_type == 'over_under':
                    # Generate ALL outcomes (over AND under) for multiple lines
                    all_preds = []
                    for line in [1.5, 2.5, 3.5]:
                        preds = strategy.generate_all_predictions(
                            fixture, is_premium=is_premium, line_value=line
                        )
                        all_preds.extend(preds)
                    predictions[market_type] = all_preds
                elif market_type == 'corners':
                    # Generate ALL outcomes for multiple lines
                    all_preds = []
                    for line in [8.5, 9.5, 10.5]:
                        preds = strategy.generate_all_predictions(
                            fixture, is_premium=is_premium, line_value=line
                        )
                        all_preds.extend(preds)
                    predictions[market_type] = all_preds
                elif market_type in ['btts', 'double_chance']:
                    # Generate ALL outcomes (yes/no for BTTS, 1X/X2/12 for DC)
                    preds = strategy.generate_all_predictions(fixture, is_premium=is_premium)
                    predictions[market_type] = preds
                else:
                    # Single prediction for other markets
                    pred = strategy.generate_prediction(fixture, is_premium=is_premium)
                    if pred:
                        predictions[market_type] = pred
            except Exception as e:
                logger.error(f"Failed to generate {market_type} prediction for fixture {fixture.id}: {e}")

        return predictions

    def generate_all_predictions_for_upcoming(self, days_ahead=3, markets=None, premium_threshold=0.75):
        """
        Generate predictions for all upcoming fixtures.

        Args:
            days_ahead: Number of days to look ahead
            markets: List of market types to generate (default: all)
            premium_threshold: Confidence threshold for premium predictions

        Returns:
            int: Number of predictions generated
        """
        from datetime import timedelta

        # Get upcoming fixtures without market predictions
        upcoming = Fixture.query.filter(
            Fixture.status == 'upcoming',
            Fixture.kickoff_at >= datetime.utcnow(),
            Fixture.kickoff_at <= datetime.utcnow() + timedelta(days=days_ahead)
        ).all()

        total_generated = 0

        for fixture in upcoming:
            try:
                predictions = self.generate_predictions_for_fixture(
                    fixture, markets=markets, is_premium=False
                )
                for market_type, pred_or_list in predictions.items():
                    if isinstance(pred_or_list, list):
                        total_generated += len(pred_or_list)
                    elif pred_or_list:
                        total_generated += 1
                db.session.commit()
            except Exception as e:
                logger.error(f"Failed to generate predictions for fixture {fixture.id}: {e}")
                db.session.rollback()
                continue

        logger.info(f"Generated {total_generated} market predictions for {len(upcoming)} fixtures")
        return total_generated

    def populate_team_stats(self, season='2024-25'):
        """
        Calculate and populate TeamStats from existing FormRecords.

        This should be run periodically to update team statistics
        used by the prediction strategies.
        """
        from ..models.team import Team

        teams = Team.query.all()
        stats_updated = 0

        for team in teams:
            # Get recent form records
            form_records = FormRecord.query.filter_by(team_id=team.id).order_by(
                FormRecord.match_date.desc()
            ).limit(20).all()

            if not form_records:
                continue

            # Get or create stats
            stats = TeamStats.query.filter_by(team_id=team.id, season=season).first()
            if not stats:
                stats = TeamStats(team_id=team.id, season=season)
                db.session.add(stats)

            # Calculate stats
            matches = len(form_records)
            goals_scored = sum(r.goals_scored for r in form_records)
            goals_conceded = sum(r.goals_conceded for r in form_records)

            # BTTS count (both teams scored)
            btts_count = sum(1 for r in form_records if r.goals_scored > 0 and r.goals_conceded > 0)

            # Clean sheets and failed to score
            clean_sheets = sum(1 for r in form_records if r.goals_conceded == 0)
            failed_to_score = sum(1 for r in form_records if r.goals_scored == 0)

            # Over/Under counts
            over_2_5 = sum(1 for r in form_records if (r.goals_scored + r.goals_conceded) > 2.5)
            over_1_5 = sum(1 for r in form_records if (r.goals_scored + r.goals_conceded) > 1.5)
            over_0_5 = sum(1 for r in form_records if (r.goals_scored + r.goals_conceded) > 0.5)

            # Update stats
            stats.matches_played = matches
            stats.goals_scored = goals_scored
            stats.goals_conceded = goals_conceded
            stats.avg_goals_scored = goals_scored / matches if matches > 0 else 0
            stats.avg_goals_conceded = goals_conceded / matches if matches > 0 else 0
            stats.btts_yes_count = btts_count
            stats.btts_percentage = (btts_count / matches * 100) if matches > 0 else 0
            stats.clean_sheets = clean_sheets
            stats.failed_to_score = failed_to_score
            stats.over_2_5_count = over_2_5
            stats.over_1_5_count = over_1_5
            stats.over_0_5_count = over_0_5

            # Default corners (would need external data for real values)
            stats.avg_corners_for = 5.0
            stats.avg_corners_against = 5.0

            stats.updated_at = datetime.utcnow()
            stats_updated += 1

        db.session.commit()
        logger.info(f"Updated stats for {stats_updated} teams")
        return stats_updated

    def get_predictions_for_fixture(self, fixture_id, market_type=None):
        """
        Get all market predictions for a fixture.

        Args:
            fixture_id: ID of the fixture
            market_type: Filter by market type (optional)

        Returns:
            dict with market_type -> predictions mapping
        """
        query = MarketPrediction.query.filter_by(fixture_id=fixture_id)

        if market_type:
            query = query.filter_by(market_type=market_type)

        predictions = query.all()

        # Group by market type
        grouped = {}
        for pred in predictions:
            if pred.market_type not in grouped:
                grouped[pred.market_type] = []
            grouped[pred.market_type].append(pred)

        return grouped

    def get_value_bets(self, market_type=None, limit=20):
        """
        Get value bet predictions across all markets.

        Args:
            market_type: Filter by market type (optional)
            limit: Maximum number of results

        Returns:
            List of MarketPrediction instances
        """
        query = MarketPrediction.query.filter_by(is_value_bet=True).join(Fixture).filter(
            Fixture.status == 'upcoming',
            Fixture.kickoff_at >= datetime.utcnow()
        )

        if market_type:
            query = query.filter(MarketPrediction.market_type == market_type)

        return query.order_by(
            MarketPrediction.value_edge.desc()
        ).limit(limit).all()
