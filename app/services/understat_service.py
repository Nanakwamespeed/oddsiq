"""
Club Elo strength ratings.

Fetches global Elo ratings for all clubs from clubelo.com (free, no key needed).
Stores the latest Elo value in team_xg_stats.elo so the prediction engine
can scale attack/defense ratings by relative team strength.

Elo baseline ~1600:  a team at 1700 is ~14 % stronger than average;
a team at 1400 is ~14 % weaker.  The engine multiplies lambda values
by (elo / _ELO_BASELINE) for attack and divides for defense.
"""
import csv
import logging
import io
from datetime import datetime, date
from difflib import SequenceMatcher

import requests
from ..extensions import db
from ..models.team import Team
from ..models.league import League
from ..models.team_xg_stats import TeamXGStats

logger = logging.getLogger(__name__)

_ELO_API = 'http://api.clubelo.com/{date}'
_BASELINE_ELO = 1600.0   # rough global average for professional clubs


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _best_match(name: str, candidates: dict) -> tuple:
    """Return (team_id, score). candidates = {team_id: team_name}."""
    best_id, best_score = None, 0.0
    for tid, tname in candidates.items():
        score = _similarity(name, tname)
        if score > best_score:
            best_score = score
            best_id = tid
    return best_id, best_score


class UnderstatService:
    """
    Despite the class name (kept for backward compatibility with cron.py),
    this service now fetches Club Elo ratings rather than Understat xG data.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0'

    def _fetch_elo_data(self) -> dict:
        """
        Fetch today's Club Elo snapshot.
        Returns dict: {club_name_lower: elo_float}
        """
        url = _ELO_API.format(date=date.today().isoformat())
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error('Club Elo fetch error: %s', e)
            return {}

        reader = csv.DictReader(io.StringIO(resp.text))
        return {row['Club'].strip(): float(row['Elo']) for row in reader if row.get('Elo')}

    def ingest_xg_stats(self) -> int:
        """
        Match Club Elo ratings to our DB teams and upsert into team_xg_stats.
        Returns total number of teams updated.
        """
        elo_map = self._fetch_elo_data()
        if not elo_map:
            logger.warning('Club Elo returned no data')
            return 0

        teams = Team.query.all()
        updated = 0

        for team in teams:
            # Build candidate lookup with just this team
            team_id, score = _best_match(team.name, {tid: tn for tid, tn in
                [(t.id, t.name) for t in [team]]})

            # Match against Elo data
            best_elo_name, best_score = None, 0.0
            for elo_name in elo_map:
                s = _similarity(team.name, elo_name)
                if s > best_score:
                    best_score = s
                    best_elo_name = elo_name

            if best_score < 0.55 or best_elo_name is None:
                continue

            elo_value = elo_map[best_elo_name]

            existing = TeamXGStats.query.filter_by(team_id=team.id).first()
            if existing:
                existing.elo = round(elo_value, 2)
                existing.updated_at = datetime.utcnow()
            else:
                db.session.add(TeamXGStats(
                    team_id=team.id,
                    season='2024',
                    matches=0,
                    elo=round(elo_value, 2),
                ))
            updated += 1

        db.session.commit()
        logger.info('Club Elo ingest complete: %d teams updated', updated)
        return updated
