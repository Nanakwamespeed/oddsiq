"""
Football Prediction Engine — Poisson goal model with Dixon-Coles correction.

Reference:
  Dixon & Coles (1997): "Modelling association football scores and
  inefficiencies in the football betting market."
  Applied Statistics, 46(2), 265-280.

Pipeline:
  1. Exponentially-weighted attack / defense ratings from FormRecord
  2. Normalised expected goals (λ_home, λ_away)
  3. Bivariate Poisson → all scoreline probabilities
  4. Dixon-Coles low-score correlation correction
  5. Sum into H / D / A probabilities
  6. Blend with bookmaker-implied probs (removes overround first)
  7. H2H momentum micro-adjustment
  8. Confidence score + value-bet flag
"""
import math
import logging

from ..extensions import db
from ..models.prediction import Prediction
from ..models.form_record import FormRecord
from ..models.h2h_record import H2HRecord
from ..models.odds import Odds
from ..models.team import Team

logger = logging.getLogger(__name__)

# ── Empirical football baselines (European league averages) ───
_HOME_BASELINE = 1.50   # avg home goals per game
_AWAY_BASELINE = 1.15   # avg away goals per game

# ── Model hyper-parameters ────────────────────────────────────
_RECENCY_DECAY  = 0.87   # weight multiplier per match; newest match = 1.0
_MAX_GOALS      = 10     # sum scorelines 0..10 × 0..10
_DC_RHO         = -0.10  # Dixon-Coles low-score correlation (empirically ~-0.1)
_DRAW_UPSCALE   = 1.08   # Poisson underestimates draws by ~8%; empirical correction
_ODDS_WEIGHT    = 0.30   # blending weight for bookmaker-implied probs
_H2H_MAX_SHIFT  = 0.04   # max probability shift from H2H history
_MIN_FORM_GAMES = 1      # fall back to baseline below this threshold
_VALUE_EDGE_MIN = 0.04   # model_prob − market_implied to flag a value bet


# ════════════════════════════════════════════════════════════════
# Pure-math helpers (no DB access)
# ════════════════════════════════════════════════════════════════

def poisson_pmf(k: int, lam: float) -> float:
    """Probability mass function  P(X = k)  for Poisson(λ)."""
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    if k < 0:
        return 0.0
    try:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def poisson_cdf(n: int, lam: float) -> float:
    """Cumulative probability  P(X ≤ n)  for Poisson(λ)."""
    return sum(poisson_pmf(k, lam) for k in range(n + 1))


def dc_tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    """
    Dixon-Coles correction factor τ(x, y).

    Adjusts joint probability for correlated low scores, which pure
    independent-Poisson over-/under-estimates:
      (0,0)  →  1 − λh·λa·ρ
      (1,0)  →  1 + λa·ρ
      (0,1)  →  1 + λh·ρ
      (1,1)  →  1 − ρ
      else   →  1
    """
    if x == 0 and y == 0:
        return 1.0 - lh * la * rho
    elif x == 1 and y == 0:
        return 1.0 + la * rho
    elif x == 0 and y == 1:
        return 1.0 + lh * rho
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def match_probabilities(
    lambda_home: float,
    lambda_away: float,
    rho: float = _DC_RHO,
    allows_draws: bool = True,
) -> dict:
    """
    Compute H / D / A win probabilities from expected-goals parameters.

    Uses bivariate Poisson with Dixon-Coles low-score correction.
    Applies an empirical upscale for draws (Poisson consistently
    underestimates draws by ~8 % in real match data).

    Returns:
        {'home': float, 'draw': float, 'away': float}  (sum = 1.0)
    """
    p_home = p_draw = p_away = 0.0

    for i in range(_MAX_GOALS + 1):
        for j in range(_MAX_GOALS + 1):
            p = (
                poisson_pmf(i, lambda_home)
                * poisson_pmf(j, lambda_away)
                * dc_tau(i, j, lambda_home, lambda_away, rho)
            )
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p

    p_draw *= _DRAW_UPSCALE  # empirical correction

    total = p_home + p_draw + p_away
    if total <= 0.0:
        return {'home': 0.45, 'draw': 0.25, 'away': 0.30}

    if not allows_draws:
        # 2-outcome sport: collapse draw mass proportionally into home/away
        scale = (p_home + p_away) / total
        return {
            'home': p_home / (p_home + p_away),
            'draw': 0.0,
            'away': p_away / (p_home + p_away),
        }

    return {
        'home': p_home / total,
        'draw': p_draw / total,
        'away': p_away / total,
    }


def remove_overround(home_odds: float, draw_odds: float, away_odds: float):
    """
    Convert decimal odds to true implied probabilities by removing vig.

    Returns dict or None if odds are invalid.
    """
    try:
        if not (home_odds and draw_odds and away_odds):
            return None
        total = 1 / home_odds + 1 / draw_odds + 1 / away_odds
        if total <= 0.0:
            return None
        return {
            'home': (1 / home_odds) / total,
            'draw': (1 / draw_odds) / total,
            'away': (1 / away_odds) / total,
        }
    except (ZeroDivisionError, TypeError):
        return None


# ════════════════════════════════════════════════════════════════
# Main engine class
# ════════════════════════════════════════════════════════════════

class FootballPredictionEngine:
    """
    Stateless prediction engine.  All DB reads are done per call; the
    instance holds no mutable state so it is safe to reuse across requests.

    Public interface
    ────────────────
    expected_goals(home_id, away_id)  → (λ_home, λ_away)
    predict(fixture)                  → full result dict
    generate_prediction(fixture)      → Prediction ORM object (DB write)
    regenerate_prediction(fixture)    → delete existing + re-create
    generate_predictions_for_upcoming() → int (count)
    """

    # ── Attack / defense rating helpers ───────────────────────

    def _form_records(self, team_id: int, limit: int = 10):
        team = Team.query.get(team_id)
        if not team:
            return []
        return team.get_recent_form(limit=limit)

    def _weighted_average(self, records, attr: str) -> float | None:
        """
        Exponentially-weighted mean of `attr` over form records.

        Most recent match → weight 1.0.
        Each prior match → weight *= _RECENCY_DECAY.
        """
        if not records:
            return None
        w = 1.0
        wsum = wcount = 0.0
        for rec in records:
            val = getattr(rec, attr, None) or 0
            wsum += val * w
            wcount += w
            w *= _RECENCY_DECAY
        return wsum / wcount if wcount > 0 else None

    def attack_rating(self, team_id: int) -> float:
        """
        Recency-weighted average goals scored per game.
        Falls back to home/away baseline when data is sparse.
        """
        records = self._form_records(team_id, limit=10)
        if len(records) < _MIN_FORM_GAMES:
            return _HOME_BASELINE
        avg = self._weighted_average(records, 'goals_scored')
        return avg if avg is not None else _HOME_BASELINE

    def defense_rating(self, team_id: int) -> float:
        """
        Recency-weighted average goals conceded per game.
        Lower = better defensive record.
        """
        records = self._form_records(team_id, limit=10)
        if len(records) < _MIN_FORM_GAMES:
            return _AWAY_BASELINE
        avg = self._weighted_average(records, 'goals_conceded')
        return avg if avg is not None else _AWAY_BASELINE

    # ── Expected goals ─────────────────────────────────────────

    def expected_goals(self, home_id: int, away_id: int) -> tuple[float, float]:
        """
        Estimate expected goals for home and away teams.

        Normalised attack-defense model (Dixon-Coles style):

          λ_home = (home_attack / H_base) × (away_defense / A_base) × H_base
          λ_away = (away_attack / A_base) × (home_defense / H_base) × A_base

        The baseline division + multiplication keeps a league-average team
        producing the historical league average.  Home advantage is baked
        into the separate baselines (_HOME_BASELINE > _AWAY_BASELINE).
        """
        ha = self.attack_rating(home_id)
        hd = self.defense_rating(home_id)
        aa = self.attack_rating(away_id)
        ad = self.defense_rating(away_id)

        lambda_home = (ha / _HOME_BASELINE) * (ad / _AWAY_BASELINE) * _HOME_BASELINE
        lambda_away = (aa / _AWAY_BASELINE) * (hd / _HOME_BASELINE) * _AWAY_BASELINE

        # Clamp to a realistic range
        lambda_home = max(0.30, min(lambda_home, 5.0))
        lambda_away = max(0.20, min(lambda_away, 5.0))

        return round(lambda_home, 3), round(lambda_away, 3)

    # ── H2H momentum adjustment ────────────────────────────────

    def _h2h_delta(self, home_id: int, away_id: int) -> dict:
        """
        Small probability delta derived from H2H history.

        h2h_score ∈ [0, 1], 0.5 = neutral.
        Maps to probability shift in [-H2H_MAX_SHIFT, +H2H_MAX_SHIFT].
        """
        records = H2HRecord.get_h2h_records(home_id, away_id, limit=8)
        if not records:
            return {'home': 0.0, 'draw': 0.0, 'away': 0.0}
        score = H2HRecord.calculate_h2h_score(records, home_id)
        shift = (score - 0.5) * 2 * _H2H_MAX_SHIFT
        return {'home': shift, 'draw': 0.0, 'away': -shift}

    # ── Bookmaker odds blending ────────────────────────────────

    def _blend_with_market(self, probs: dict, fixture_id: int) -> dict:
        """
        Bayesian blend of model probs and bookmaker-implied probs.

        Best (highest) odds for each outcome are selected across all
        available bookmakers, overround is removed, then linearly blended
        with the model output at weight _ODDS_WEIGHT.
        """
        rows = Odds.query.filter_by(fixture_id=fixture_id).all()
        if not rows:
            return probs

        best = {'home': 0.0, 'draw': 0.0, 'away': 0.0}
        for o in rows:
            if o.home_win_odds and o.home_win_odds > best['home']:
                best['home'] = o.home_win_odds
            if o.draw_odds and o.draw_odds > best['draw']:
                best['draw'] = o.draw_odds
            if o.away_win_odds and o.away_win_odds > best['away']:
                best['away'] = o.away_win_odds

        market = remove_overround(best['home'], best['draw'], best['away'])
        if not market:
            return probs

        w = _ODDS_WEIGHT
        blended = {
            k: probs[k] * (1.0 - w) + market[k] * w
            for k in ('home', 'draw', 'away')
        }
        total = sum(blended.values())
        return {k: v / total for k, v in blended.items()}

    # ── Value-bet detection ────────────────────────────────────

    def detect_value_bet(
        self, fixture_id: int, predicted_outcome: str, model_prob: float
    ) -> dict:
        """
        Compare model probability against best available odds.

        A value bet exists when:
            model_prob  >  (1 / best_odds)  +  _VALUE_EDGE_MIN

        i.e. the model believes the true probability is meaningfully
        higher than the bookmaker's implied probability.
        """
        result = {
            'is_value_bet': False,
            'best_odds': None,
            'bookmaker': None,
            'implied_probability': None,
            'edge': None,
        }

        rows = Odds.query.filter_by(fixture_id=fixture_id).all()
        if not rows:
            return result

        best_val, best_bm = 0.0, None
        for o in rows:
            cand = (
                o.home_win_odds if predicted_outcome == 'home'
                else o.draw_odds if predicted_outcome == 'draw'
                else o.away_win_odds
            )
            if cand and cand > best_val:
                best_val = cand
                best_bm = o.bookmaker_name

        if best_val <= 1.0:
            return result

        implied = 1.0 / best_val
        edge = model_prob - implied

        result.update({
            'best_odds': best_val,
            'bookmaker': best_bm,
            'implied_probability': round(implied, 4),
            'edge': round(edge, 4),
            'is_value_bet': edge > _VALUE_EDGE_MIN,
        })
        return result

    # ── Main prediction pipeline ───────────────────────────────

    def predict(self, fixture) -> dict:
        """
        Full prediction pipeline for a single fixture.

        Returns
        -------
        dict
            predicted_outcome  : 'home' | 'draw' | 'away'
            confidence_score   : float  0.0 – 1.0
            probabilities      : {'home': p, 'draw': p, 'away': p}
            lambda_home        : expected home goals
            lambda_away        : expected away goals
            is_value_bet       : bool
            value_edge         : float | None
        """
        sport = (
            fixture.league.sport.name
            if fixture.league and fixture.league.sport
            else 'football'
        )
        allows_draws = sport == 'football'

        # 1. Expected goals
        lh, la = self.expected_goals(fixture.home_team_id, fixture.away_team_id)

        # 2. Bivariate Poisson → H/D/A probabilities
        probs = match_probabilities(lh, la, allows_draws=allows_draws)

        # 3. H2H momentum adjustment
        delta = self._h2h_delta(fixture.home_team_id, fixture.away_team_id)
        for k in ('home', 'draw', 'away'):
            probs[k] = max(0.01, probs[k] + delta[k])
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()}

        # 4. Blend with bookmaker market
        probs = self._blend_with_market(probs, fixture.id)

        # 5. Predicted outcome = highest probability
        predicted = max(probs, key=probs.get)
        if not allows_draws and predicted == 'draw':
            predicted = 'home' if probs['home'] >= probs['away'] else 'away'

        model_prob = probs[predicted]

        # 6. Confidence score
        #    Map winning probability onto [0.50, 0.95].
        #    Baseline (random chance) → 0.50.
        #    At 100% probability → 0.95.
        baseline = 1 / 3 if allows_draws else 0.5
        span = 1.0 - baseline
        confidence = 0.50 + ((model_prob - baseline) / span) * 0.45
        confidence = round(max(0.50, min(confidence, 0.95)), 4)

        # 7. Value bet
        vb = self.detect_value_bet(fixture.id, predicted, model_prob)

        return {
            'predicted_outcome': predicted,
            'confidence_score': confidence,
            'probabilities': {k: round(v, 4) for k, v in probs.items()},
            'lambda_home': lh,
            'lambda_away': la,
            'is_value_bet': vb['is_value_bet'],
            'value_edge': vb['edge'],
        }

    # ── DB lifecycle ───────────────────────────────────────────

    def generate_prediction(self, fixture, is_premium: bool = False) -> Prediction:
        existing = Prediction.query.filter_by(fixture_id=fixture.id).first()
        if existing:
            return existing

        result = self.predict(fixture)

        pred = Prediction(
            fixture_id=fixture.id,
            predicted_outcome=result['predicted_outcome'],
            confidence_score=result['confidence_score'],
            is_value_bet=result['is_value_bet'],
            is_premium=is_premium,
        )
        db.session.add(pred)
        db.session.commit()

        logger.info(
            '[Engine] fixture=%d  %s @ %.1f%%  λ=(%.2f, %.2f)  value=%s',
            fixture.id,
            result['predicted_outcome'],
            result['confidence_score'] * 100,
            result['lambda_home'],
            result['lambda_away'],
            result['is_value_bet'],
        )
        return pred

    def regenerate_prediction(self, fixture, is_premium: bool = False) -> Prediction:
        """Delete existing prediction and produce a fresh one."""
        Prediction.query.filter_by(fixture_id=fixture.id).delete()
        db.session.commit()
        return self.generate_prediction(fixture, is_premium=is_premium)

    def generate_predictions_for_upcoming(
        self, premium_threshold: float = 0.72
    ) -> int:
        """Generate predictions for all upcoming fixtures lacking one."""
        from ..models.fixture import Fixture

        upcoming = Fixture.query.filter_by(status='upcoming').filter(
            ~Fixture.id.in_(db.session.query(Prediction.fixture_id))
        ).all()

        generated = 0
        for fixture in upcoming:
            try:
                result = self.predict(fixture)
                is_premium = result['confidence_score'] >= premium_threshold
                self.generate_prediction(fixture, is_premium=is_premium)
                generated += 1
            except Exception as exc:
                logger.error('[Engine] fixture=%d failed: %s', fixture.id, exc)

        logger.info('[Engine] generated %d predictions', generated)
        return generated
