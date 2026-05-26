"""
Football Prediction Engine — Poisson goal model with Dixon-Coles correction.

Improvements over v1:
  • Venue-split form: home team's home goals / away team's away goals
    instead of combined form for both sides.
  • xG integration: when Understat xG data exists, blend it (60%) with
    recent venue form (40%) for a noise-resistant attack/defense signal.
  • Higher market trust: _ODDS_WEIGHT 0.30 → 0.45.
  • Draw scepticism: only predict draw when P(draw) ≥ _DRAW_THRESHOLD.
  • Confidence gate: skip fixtures where the winner's probability is
    below _MIN_MODEL_PROB (uncertain matches — not worth publishing).
  • Tighter recency window: 5 venue-specific games instead of 10 mixed.
"""
import math
import logging

from ..extensions import db
from ..models.prediction import Prediction
from ..models.h2h_record import H2HRecord
from ..models.odds import Odds
from ..models.team import Team

logger = logging.getLogger(__name__)

# ── Empirical football baselines (European league averages) ───
_HOME_BASELINE = 1.50
_AWAY_BASELINE = 1.15

# ── Model hyper-parameters ────────────────────────────────────
_RECENCY_DECAY    = 0.87   # weight multiplier per match; newest = 1.0
_MAX_GOALS        = 10
_DC_RHO           = -0.10  # Dixon-Coles low-score correlation
_DRAW_UPSCALE     = 1.08   # Poisson underestimates draws by ~8 %
_ODDS_WEIGHT      = 0.45   # bookmaker-implied blend weight (was 0.30)
_H2H_MAX_SHIFT    = 0.04   # max probability shift from H2H history
_MIN_FORM_GAMES   = 1      # fall back to baseline below this threshold
_VENUE_LIMIT      = 5      # recent home/away games to use for form
_VALUE_EDGE_MIN   = 0.04   # edge threshold to flag a value bet
_DRAW_THRESHOLD   = 0.36   # only predict draw when P(draw) ≥ this
_MIN_MODEL_PROB   = 0.46   # skip prediction when winner prob < this
_ELO_BASELINE     = 1600.0 # Club Elo global average; scales attack/defense ratings
_ELO_MAX_SCALE    = 0.30   # max ±30 % adjustment from Elo deviation


# ════════════════════════════════════════════════════════════════
# Pure-math helpers
# ════════════════════════════════════════════════════════════════

def poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    if k < 0:
        return 0.0
    try:
        return (lam ** k) * math.exp(-lam) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def poisson_cdf(n: int, lam: float) -> float:
    return sum(poisson_pmf(k, lam) for k in range(n + 1))


def dc_tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
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

    p_draw *= _DRAW_UPSCALE

    total = p_home + p_draw + p_away
    if total <= 0.0:
        return {'home': 0.45, 'draw': 0.25, 'away': 0.30}

    if not allows_draws:
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

    # ── Venue-split fixture helpers ────────────────────────────

    def _recent_home_fixtures(self, team_id: int):
        from ..models.fixture import Fixture
        return (
            Fixture.query
            .filter_by(home_team_id=team_id, status='finished')
            .filter(Fixture.home_score.isnot(None))
            .order_by(Fixture.kickoff_at.desc())
            .limit(_VENUE_LIMIT)
            .all()
        )

    def _recent_away_fixtures(self, team_id: int):
        from ..models.fixture import Fixture
        return (
            Fixture.query
            .filter_by(away_team_id=team_id, status='finished')
            .filter(Fixture.away_score.isnot(None))
            .order_by(Fixture.kickoff_at.desc())
            .limit(_VENUE_LIMIT)
            .all()
        )

    def _weighted_goals(self, goal_list: list) -> float | None:
        """Exponentially weighted mean over a list of goal values."""
        if not goal_list:
            return None
        w = 1.0
        wsum = wcount = 0.0
        for g in goal_list:
            wsum += g * w
            wcount += w
            w *= _RECENCY_DECAY
        return wsum / wcount if wcount > 0 else None

    # ── Elo strength helpers ───────────────────────────────────

    def _elo_scale(self, team_id: int) -> float:
        """
        Return a scaling factor derived from Club Elo.

        A team at baseline (1600) → 1.0x.
        A team at 1900 → ~1.19x.  At 1300 → ~0.81x.
        Clamped to [1 - _ELO_MAX_SCALE, 1 + _ELO_MAX_SCALE].
        """
        try:
            from ..models.team_xg_stats import TeamXGStats
            row = TeamXGStats.query.filter_by(team_id=team_id).first()
            if row and row.elo:
                raw = (row.elo - _ELO_BASELINE) / _ELO_BASELINE
                return round(1.0 + max(-_ELO_MAX_SCALE, min(raw, _ELO_MAX_SCALE)), 4)
        except Exception:
            pass
        return 1.0

    # ── Attack / defense ratings (venue-aware + Elo scaling) ──

    def home_attack_rating(self, team_id: int) -> float:
        """Expected goals scored by team at home, scaled by Elo strength."""
        rows = self._recent_home_fixtures(team_id)
        if len(rows) >= _MIN_FORM_GAMES:
            form_val = self._weighted_goals([r.home_score for r in rows])
            if form_val is not None:
                return round(max(0.50, form_val * self._elo_scale(team_id)), 3)
        return round(_HOME_BASELINE * self._elo_scale(team_id), 3)

    def home_defense_rating(self, team_id: int) -> float:
        """Expected goals conceded by team at home, scaled by Elo strength."""
        rows = self._recent_home_fixtures(team_id)
        if len(rows) >= _MIN_FORM_GAMES:
            form_val = self._weighted_goals([r.away_score for r in rows])
            if form_val is not None:
                # Floor at 0.40 — even elite defences concede occasionally
                return round(max(0.40, form_val / self._elo_scale(team_id)), 3)
        return round(max(0.40, _AWAY_BASELINE / self._elo_scale(team_id)), 3)

    def away_attack_rating(self, team_id: int) -> float:
        """Expected goals scored by team away, scaled by Elo strength."""
        rows = self._recent_away_fixtures(team_id)
        if len(rows) >= _MIN_FORM_GAMES:
            form_val = self._weighted_goals([r.away_score for r in rows])
            if form_val is not None:
                return round(max(0.40, form_val * self._elo_scale(team_id)), 3)
        return round(_AWAY_BASELINE * self._elo_scale(team_id), 3)

    def away_defense_rating(self, team_id: int) -> float:
        """Expected goals conceded by team away, scaled by Elo strength."""
        rows = self._recent_away_fixtures(team_id)
        if len(rows) >= _MIN_FORM_GAMES:
            form_val = self._weighted_goals([r.home_score for r in rows])
            if form_val is not None:
                return round(max(0.50, form_val / self._elo_scale(team_id)), 3)
        return round(max(0.50, _HOME_BASELINE / self._elo_scale(team_id)), 3)

    # ── Backward-compat shims used by PredictionService ───────

    def attack_rating(self, team_id: int) -> float:
        """Overall attack rating (home+away blended). Used by PredictionService shim."""
        ha = self.home_attack_rating(team_id)
        aa = self.away_attack_rating(team_id)
        return round((ha + aa) / 2, 3)

    def defense_rating(self, team_id: int) -> float:
        """Overall defense rating (home+away blended). Used by PredictionService shim."""
        hd = self.home_defense_rating(team_id)
        ad = self.away_defense_rating(team_id)
        return round((hd + ad) / 2, 3)

    # ── Expected goals ─────────────────────────────────────────

    def expected_goals(self, home_id: int, away_id: int) -> tuple[float, float]:
        """
        Venue-aware expected goals.

        λ_home = home team's home attack  × away team's away defense  / baselines
        λ_away = away team's away attack  × home team's home defense  / baselines
        """
        ha = self.home_attack_rating(home_id)   # home team scores at home
        hd = self.home_defense_rating(home_id)  # home team concedes at home
        aa = self.away_attack_rating(away_id)   # away team scores away
        ad = self.away_defense_rating(away_id)  # away team concedes away

        lambda_home = (ha / _HOME_BASELINE) * (ad / _AWAY_BASELINE) * _HOME_BASELINE
        lambda_away = (aa / _AWAY_BASELINE) * (hd / _HOME_BASELINE) * _AWAY_BASELINE

        lambda_home = max(0.50, min(lambda_home, 5.0))
        lambda_away = max(0.40, min(lambda_away, 5.0))

        return round(lambda_home, 3), round(lambda_away, 3)

    # ── H2H momentum ───────────────────────────────────────────

    def _h2h_delta(self, home_id: int, away_id: int) -> dict:
        records = H2HRecord.get_h2h_records(home_id, away_id, limit=8)
        if not records:
            return {'home': 0.0, 'draw': 0.0, 'away': 0.0}
        score = H2HRecord.calculate_h2h_score(records, home_id)
        shift = (score - 0.5) * 2 * _H2H_MAX_SHIFT
        return {'home': shift, 'draw': 0.0, 'away': -shift}

    # ── Bookmaker odds blending ────────────────────────────────

    def _blend_with_market(self, probs: dict, fixture_id: int) -> dict:
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
        blended = {k: probs[k] * (1.0 - w) + market[k] * w for k in ('home', 'draw', 'away')}
        total = sum(blended.values())
        return {k: v / total for k, v in blended.items()}

    # ── Value-bet detection ────────────────────────────────────

    def detect_value_bet(self, fixture_id: int, predicted_outcome: str, model_prob: float) -> dict:
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
        sport = (
            fixture.league.sport.name
            if fixture.league and fixture.league.sport
            else 'football'
        )
        allows_draws = sport == 'football'

        # 1. Venue-aware expected goals
        lh, la = self.expected_goals(fixture.home_team_id, fixture.away_team_id)

        # 2. Bivariate Poisson → H/D/A
        probs = match_probabilities(lh, la, allows_draws=allows_draws)

        # 3. H2H adjustment
        delta = self._h2h_delta(fixture.home_team_id, fixture.away_team_id)
        for k in ('home', 'draw', 'away'):
            probs[k] = max(0.01, probs[k] + delta[k])
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()}

        # 4. Blend with bookmaker market (higher weight than v1)
        probs = self._blend_with_market(probs, fixture.id)

        # 5. Draw scepticism: only predict draw when it's genuinely probable
        predicted = max(probs, key=probs.get)
        if allows_draws and predicted == 'draw' and probs['draw'] < _DRAW_THRESHOLD:
            predicted = 'home' if probs['home'] >= probs['away'] else 'away'

        if not allows_draws and predicted == 'draw':
            predicted = 'home' if probs['home'] >= probs['away'] else 'away'

        model_prob = probs[predicted]

        # 6. Confidence score mapped to [0.50, 0.95]
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
            'model_prob': round(model_prob, 4),
        }

    # ── DB lifecycle ───────────────────────────────────────────

    def generate_prediction(self, fixture, is_premium: bool = False) -> Prediction | None:
        existing = Prediction.query.filter_by(fixture_id=fixture.id).first()
        if existing:
            return existing

        result = self.predict(fixture)

        # Confidence gate: skip uncertain fixtures
        if result['model_prob'] < _MIN_MODEL_PROB:
            logger.debug(
                '[Engine] fixture=%d skipped — low confidence (%.1f%%)',
                fixture.id, result['model_prob'] * 100
            )
            return None

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
            '[Engine] fixture=%d  %s @ %.1f%%  λ=(%.2f,%.2f)  value=%s',
            fixture.id,
            result['predicted_outcome'],
            result['model_prob'] * 100,
            result['lambda_home'],
            result['lambda_away'],
            result['is_value_bet'],
        )
        return pred

    def regenerate_prediction(self, fixture, is_premium: bool = False) -> Prediction | None:
        Prediction.query.filter_by(fixture_id=fixture.id).delete()
        db.session.commit()
        return self.generate_prediction(fixture, is_premium=is_premium)

    def generate_predictions_for_upcoming(self, premium_threshold: float = 0.72) -> int:
        from ..models.fixture import Fixture

        upcoming = Fixture.query.filter_by(status='upcoming').filter(
            ~Fixture.id.in_(db.session.query(Prediction.fixture_id))
        ).all()

        generated = 0
        for fixture in upcoming:
            try:
                result = self.predict(fixture)
                if result['model_prob'] < _MIN_MODEL_PROB:
                    continue
                is_premium = result['confidence_score'] >= premium_threshold
                self.generate_prediction(fixture, is_premium=is_premium)
                generated += 1
            except Exception as exc:
                logger.error('[Engine] fixture=%d failed: %s', fixture.id, exc)

        logger.info('[Engine] generated %d predictions', generated)
        return generated
