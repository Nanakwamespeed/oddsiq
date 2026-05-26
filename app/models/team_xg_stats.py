"""Team xG (Expected Goals) season stats scraped from Understat."""
from datetime import datetime
from ..extensions import db


class TeamXGStats(db.Model):
    __tablename__ = 'team_xg_stats'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False, unique=True, index=True)
    season = db.Column(db.String(10), nullable=False, default='2024')
    matches = db.Column(db.Integer, default=0)
    xg_for = db.Column(db.Float, nullable=True)      # season total xG scored (future use)
    xg_against = db.Column(db.Float, nullable=True)  # season total xG conceded (future use)
    elo = db.Column(db.Float, nullable=True)          # Club Elo rating (global strength)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def xg_per_game(self):
        if not self.matches or self.matches == 0:
            return None
        return round(self.xg_for / self.matches, 3)

    @property
    def xga_per_game(self):
        if not self.matches or self.matches == 0:
            return None
        return round(self.xg_against / self.matches, 3)

    def __repr__(self):
        return f'<TeamXGStats team_id={self.team_id} xg={self.xg_per_game}/game>'
