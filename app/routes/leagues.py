"""Leagues routes."""
from flask import Blueprint, request
from ..extensions import cache
from ..models.league import League
from ..models.sport import Sport
from ..models.team import Team
from ..models.fixture import Fixture
from ..utils.helpers import json_error, json_success

leagues_bp = Blueprint('leagues', __name__)


@leagues_bp.route('/', methods=['GET'])
@cache.cached(timeout=3600)
def get_leagues():
    """Get all leagues grouped by sport."""
    sports = Sport.query.all()

    result = {}
    for sport in sports:
        leagues = League.query.filter_by(sport_id=sport.id).all()
        result[sport.name] = [league.to_dict() for league in leagues]

    return json_success(data=result)


@leagues_bp.route('/<int:league_id>', methods=['GET'])
@cache.cached(timeout=3600)
def get_league(league_id):
    """Get single league details."""
    league = League.query.get(league_id)

    if not league:
        return json_error('League not found', 404)

    return json_success(data=league.to_dict(include_teams=True))


@leagues_bp.route('/<int:league_id>/teams', methods=['GET'])
@cache.cached(timeout=3600)
def get_league_teams(league_id):
    """Get all teams in a league."""
    league = League.query.get(league_id)

    if not league:
        return json_error('League not found', 404)

    teams = Team.query.filter_by(league_id=league_id).order_by(Team.name).all()

    return json_success(data={
        'league': league.to_dict(),
        'teams': [team.to_dict() for team in teams]
    })


@leagues_bp.route('/<int:league_id>/fixtures', methods=['GET'])
@cache.cached(timeout=900, query_string=True)
def get_league_fixtures(league_id):
    """Get fixtures for a league."""
    league = League.query.get(league_id)

    if not league:
        return json_error('League not found', 404)

    status = request.args.get('status')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Fixture.query.filter_by(league_id=league_id)

    if status and status in ['upcoming', 'live', 'finished']:
        query = query.filter_by(status=status)

    query = query.order_by(Fixture.kickoff_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return json_success(data={
        'league': league.to_dict(),
        'fixtures': [f.to_dict() for f in pagination.items],
        'page': page,
        'per_page': per_page,
        'total': pagination.total,
        'total_pages': pagination.pages
    })


@leagues_bp.route('/by-sport/<sport_name>', methods=['GET'])
@cache.cached(timeout=3600)
def get_leagues_by_sport(sport_name):
    """Get leagues for a specific sport."""
    sport = Sport.query.filter_by(name=sport_name.lower()).first()

    if not sport:
        return json_error('Sport not found', 404)

    all_leagues = League.query.filter_by(sport_id=sport.id).order_by(League.name).all()

    # Deduplicate by name (duplicate rows can appear from repeated ingestion runs)
    seen = set()
    leagues = []
    for league in all_leagues:
        if league.name not in seen:
            seen.add(league.name)
            leagues.append(league)

    return json_success(data={
        'sport': sport.to_dict(),
        'leagues': [league.to_dict() for league in leagues]
    })
