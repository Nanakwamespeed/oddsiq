"""Database models."""
from .user import User
from .token import RefreshToken
from .sport import Sport
from .league import League
from .team import Team
from .fixture import Fixture
from .prediction import Prediction
from .odds import Odds
from .form_record import FormRecord
from .h2h_record import H2HRecord
from .newsletter import Newsletter
from .subscription import Subscription
from .accuracy_log import AccuracyLog
from .guide import Guide

# Market prediction models
from .market_prediction import MarketPrediction
from .market_odds import MarketOdds
from .team_stats import TeamStats
from .market_accuracy_log import MarketAccuracyLog
from .team_xg_stats import TeamXGStats

__all__ = [
    'User',
    'RefreshToken',
    'Sport',
    'League',
    'Team',
    'Fixture',
    'Prediction',
    'Odds',
    'FormRecord',
    'H2HRecord',
    'Newsletter',
    'Subscription',
    'AccuracyLog',
    'Guide',
    # Market prediction models
    'MarketPrediction',
    'MarketOdds',
    'TeamStats',
    'MarketAccuracyLog',
    'TeamXGStats',
]
