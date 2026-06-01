"""Football/Soccer service using ESPN's free API."""
import logging
from datetime import datetime, timedelta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import current_app
from ..extensions import db
from ..models.sport import Sport
from ..models.league import League
from ..models.team import Team
from ..models.fixture import Fixture
from ..models.form_record import FormRecord
from ..models.h2h_record import H2HRecord

logger = logging.getLogger(__name__)

# ESPN Soccer API base URL
BASE_URL = 'https://site.api.espn.com/apis/site/v2/sports/soccer'

# ESPN league codes for soccer
SUPPORTED_LEAGUES = {
    # Top European Domestic Leagues
    'eng.1': {'name': 'Premier League', 'country': 'England', 'type': 'domestic'},
    'eng.2': {'name': 'Championship', 'country': 'England', 'type': 'domestic'},
    'esp.1': {'name': 'La Liga', 'country': 'Spain', 'type': 'domestic'},
    'ger.1': {'name': 'Bundesliga', 'country': 'Germany', 'type': 'domestic'},
    'ita.1': {'name': 'Serie A', 'country': 'Italy', 'type': 'domestic'},
    'fra.1': {'name': 'Ligue 1', 'country': 'France', 'type': 'domestic'},
    'ned.1': {'name': 'Eredivisie', 'country': 'Netherlands', 'type': 'domestic'},
    'por.1': {'name': 'Primeira Liga', 'country': 'Portugal', 'type': 'domestic'},
    'sco.1': {'name': 'Scottish Premiership', 'country': 'Scotland', 'type': 'domestic'},
    'bel.1': {'name': 'Belgian Pro League', 'country': 'Belgium', 'type': 'domestic'},
    'tur.1': {'name': 'Super Lig', 'country': 'Turkey', 'type': 'domestic'},
    # Americas
    'usa.1': {'name': 'MLS', 'country': 'USA', 'type': 'domestic'},
    'mex.1': {'name': 'Liga MX', 'country': 'Mexico', 'type': 'domestic'},
    'bra.1': {'name': 'Brasileirao', 'country': 'Brazil', 'type': 'domestic'},
    'arg.1': {'name': 'Liga Argentina', 'country': 'Argentina', 'type': 'domestic'},
    # European Club Competitions
    'uefa.champions': {'name': 'UEFA Champions League', 'country': 'Europe', 'type': 'international_club'},
    'uefa.europa': {'name': 'UEFA Europa League', 'country': 'Europe', 'type': 'international_club'},
    'uefa.europa.conf': {'name': 'UEFA Conference League', 'country': 'Europe', 'type': 'international_club'},
    # South American Club Competitions
    'conmebol.libertadores': {'name': 'Copa Libertadores', 'country': 'South America', 'type': 'international_club'},
    'conmebol.sudamericana': {'name': 'Copa Sudamericana', 'country': 'South America', 'type': 'international_club'},
    # International National Team Competitions
    'fifa.friendly': {'name': 'International Friendlies', 'country': 'World', 'type': 'international_national'},
    'fifa.worldq.afc': {'name': 'World Cup Qualifiers - Asia', 'country': 'Asia', 'type': 'international_national'},
    'fifa.worldq.uefa': {'name': 'World Cup Qualifiers - Europe', 'country': 'Europe', 'type': 'international_national'},
    'fifa.worldq.conmebol': {'name': 'World Cup Qualifiers - South America', 'country': 'South America', 'type': 'international_national'},
    'fifa.worldq.concacaf': {'name': 'World Cup Qualifiers - CONCACAF', 'country': 'North America', 'type': 'international_national'},
    'fifa.worldq.caf': {'name': 'World Cup Qualifiers - Africa', 'country': 'Africa', 'type': 'international_national'},
    'uefa.nations': {'name': 'UEFA Nations League', 'country': 'Europe', 'type': 'international_national'},
    'conmebol.america': {'name': 'Copa America', 'country': 'South America', 'type': 'international_national'},
    'uefa.euro': {'name': 'UEFA Euro', 'country': 'Europe', 'type': 'international_national'},
    'caf.nations': {'name': 'Africa Cup of Nations', 'country': 'Africa', 'type': 'international_national'},
    'afc.asian.cup': {'name': 'AFC Asian Cup', 'country': 'Asia', 'type': 'international_national'},
    'concacaf.gold': {'name': 'CONCACAF Gold Cup', 'country': 'North America', 'type': 'international_national'},
}


class FootballService:
    """Service for fetching football/soccer data from ESPN's free API."""

    def __init__(self):
        # Keep API-Football key for backwards compatibility (can be used as fallback)
        self.api_key = current_app.config.get('API_FOOTBALL_KEY')

        # Setup session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def _make_request(self, url, params=None):
        """Make a request to ESPN API with retry logic."""
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f'ESPN Football request failed: {e}')
            return None

    def get_or_create_sport(self):
        """Get or create the football sport."""
        sport = Sport.query.filter_by(name='football').first()
        if not sport:
            sport = Sport(name='football')
            db.session.add(sport)
            db.session.commit()
        return sport

    def ingest_leagues(self):
        """Ingest supported leagues into the database."""
        sport = self.get_or_create_sport()
        created_count = 0

        for league_code, league_info in SUPPORTED_LEAGUES.items():
            existing = League.query.filter_by(external_id=f'espn_{league_code}').first()
            if not existing:
                league = League(
                    sport_id=sport.id,
                    name=league_info['name'],
                    country=league_info['country'],
                    external_id=f'espn_{league_code}',
                    league_type=league_info.get('type', 'domestic')
                )
                db.session.add(league)
                created_count += 1
            else:
                # Update league type if needed
                if existing.league_type != league_info.get('type', 'domestic'):
                    existing.league_type = league_info.get('type', 'domestic')

        db.session.commit()
        logger.info(f'Football: Created {created_count} new leagues')
        return created_count

    def ingest_fixtures(self, days_ahead=7):
        """Fetch upcoming fixtures for all supported leagues from ESPN."""
        sport = self.get_or_create_sport()
        total_fixtures = 0

        # ESPN returns results oldest-first, so starting the range in the past
        # pushes upcoming matches off the first page. Use two calls per league:
        #   1. upcoming: today → +days_ahead  (the important one)
        #   2. lookback: today-3 → yesterday  (to update finished scores)
        today = datetime.utcnow()
        upcoming_range = f"{today.strftime('%Y%m%d')}-{(today + timedelta(days=days_ahead)).strftime('%Y%m%d')}"
        lookback_range = f"{(today - timedelta(days=3)).strftime('%Y%m%d')}-{(today - timedelta(days=1)).strftime('%Y%m%d')}"

        for league_code, league_info in SUPPORTED_LEAGUES.items():
            league = League.query.filter_by(external_id=f'espn_{league_code}').first()
            if not league:
                continue

            url = f'{BASE_URL}/{league_code}/scoreboard'

            for date_range in (upcoming_range, lookback_range):
                data = self._make_request(url, {'dates': date_range, 'limit': 100})
                if not data:
                    continue
                for event in data.get('events', []):
                    created = self._process_event(event, league)
                    total_fixtures += created

        db.session.commit()
        logger.info(f'Football: Ingested {total_fixtures} fixtures')
        return total_fixtures

    def _process_event(self, event, league):
        """Process a single ESPN event into a fixture."""
        event_id = event.get('id')
        external_id = f'football_{event_id}'

        # Check if fixture already exists
        existing = Fixture.query.filter_by(external_id=external_id).first()
        if existing:
            # Update status if needed
            status = self._parse_status(event)
            if existing.status != status:
                existing.status = status
                # Update scores if finished
                if status == 'finished':
                    scores = self._parse_scores(event)
                    existing.home_score = scores.get('home')
                    existing.away_score = scores.get('away')
            return 0

        # Get competition info
        competitions = event.get('competitions', [])
        if not competitions:
            return 0

        competition = competitions[0]
        competitors = competition.get('competitors', [])

        if len(competitors) < 2:
            return 0

        # Parse teams (ESPN uses 'home'/'away' in homeAway field)
        home_data = None
        away_data = None
        for comp in competitors:
            if comp.get('homeAway') == 'home':
                home_data = comp
            else:
                away_data = comp

        if not home_data or not away_data:
            return 0

        # Get or create teams
        home_team = self._get_or_create_team(home_data.get('team', {}), league.id)
        away_team = self._get_or_create_team(away_data.get('team', {}), league.id)

        if not home_team or not away_team:
            return 0

        # Parse kickoff time
        date_str = event.get('date', '')
        try:
            kickoff_at = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            kickoff_at = datetime.utcnow()

        # Parse status
        status = self._parse_status(event)

        # Parse scores
        scores = self._parse_scores(event)

        # Create fixture
        fixture = Fixture(
            league_id=league.id,
            home_team_id=home_team.id,
            away_team_id=away_team.id,
            kickoff_at=kickoff_at,
            status=status,
            external_id=external_id,
            home_score=scores.get('home'),
            away_score=scores.get('away')
        )
        db.session.add(fixture)
        return 1

    def _parse_status(self, event):
        """Parse ESPN event status to our status."""
        status_info = event.get('status', {})
        type_info = status_info.get('type', {})
        state = type_info.get('state', 'pre')

        if state == 'pre':
            return 'upcoming'
        elif state == 'in':
            return 'live'
        elif state == 'post':
            return 'finished'
        return 'upcoming'

    def _parse_scores(self, event):
        """Parse scores from ESPN event."""
        competitions = event.get('competitions', [])
        if not competitions:
            return {'home': None, 'away': None}

        competitors = competitions[0].get('competitors', [])
        scores = {'home': None, 'away': None}

        for comp in competitors:
            score = comp.get('score')
            if score is not None:
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = None

            if comp.get('homeAway') == 'home':
                scores['home'] = score
            else:
                scores['away'] = score

        return scores

    def _get_or_create_team(self, team_data, league_id):
        """Get or create a team from ESPN data."""
        team_id = team_data.get('id')
        name = team_data.get('displayName') or team_data.get('name')
        logo = team_data.get('logo')

        if not team_id or not name:
            return None

        external_id = f'football_{team_id}'
        team = Team.query.filter_by(external_id=external_id).first()

        if not team:
            team = Team(
                league_id=league_id,
                name=name,
                external_id=external_id,
                logo_url=logo
            )
            db.session.add(team)
            db.session.flush()

        return team

    def ingest_recent_results(self, days_back=3):
        """
        Fetch recent finished matches to build form records.
        This gets results from the past few days to populate team form data.
        """
        sport = self.get_or_create_sport()
        form_records_created = 0
        h2h_records_created = 0

        for league_code, league_info in SUPPORTED_LEAGUES.items():
            league = League.query.filter_by(external_id=f'espn_{league_code}').first()
            if not league:
                continue

            # Fetch past days
            for day_offset in range(1, days_back + 1):
                date = datetime.utcnow() - timedelta(days=day_offset)
                date_str = date.strftime('%Y%m%d')

                url = f'{BASE_URL}/{league_code}/scoreboard'
                data = self._make_request(url, {'dates': date_str})

                if not data:
                    continue

                events = data.get('events', [])
                for event in events:
                    status = self._parse_status(event)
                    if status != 'finished':
                        continue

                    # Process form and H2H records
                    form_created, h2h_created = self._process_finished_match(event, league)
                    form_records_created += form_created
                    h2h_records_created += h2h_created

        db.session.commit()
        logger.info(f'Football: Created {form_records_created} form records, {h2h_records_created} H2H records')
        return form_records_created, h2h_records_created

    def _process_finished_match(self, event, league):
        """Process a finished match to create form and H2H records."""
        form_created = 0
        h2h_created = 0

        competitions = event.get('competitions', [])
        if not competitions:
            return 0, 0

        competition = competitions[0]
        competitors = competition.get('competitors', [])

        if len(competitors) < 2:
            return 0, 0

        # Get teams and scores
        home_data = None
        away_data = None
        for comp in competitors:
            if comp.get('homeAway') == 'home':
                home_data = comp
            else:
                away_data = comp

        if not home_data or not away_data:
            return 0, 0

        home_team = self._get_or_create_team(home_data.get('team', {}), league.id)
        away_team = self._get_or_create_team(away_data.get('team', {}), league.id)

        if not home_team or not away_team:
            return 0, 0

        # Parse scores
        try:
            home_score = int(home_data.get('score', 0))
            away_score = int(away_data.get('score', 0))
        except (ValueError, TypeError):
            return 0, 0

        # Parse match date
        date_str = event.get('date', '')
        try:
            match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
        except (ValueError, AttributeError):
            match_date = datetime.utcnow().date()

        # Determine results
        if home_score > away_score:
            home_result = 'W'
            away_result = 'L'
        elif home_score < away_score:
            home_result = 'L'
            away_result = 'W'
        else:
            home_result = 'D'
            away_result = 'D'

        # Create form record for home team
        existing_home = FormRecord.query.filter_by(
            team_id=home_team.id,
            match_date=match_date
        ).first()
        if not existing_home:
            form_record = FormRecord(
                team_id=home_team.id,
                match_date=match_date,
                result=home_result,
                goals_scored=home_score,
                goals_conceded=away_score
            )
            db.session.add(form_record)
            form_created += 1

        # Create form record for away team
        existing_away = FormRecord.query.filter_by(
            team_id=away_team.id,
            match_date=match_date
        ).first()
        if not existing_away:
            form_record = FormRecord(
                team_id=away_team.id,
                match_date=match_date,
                result=away_result,
                goals_scored=away_score,
                goals_conceded=home_score
            )
            db.session.add(form_record)
            form_created += 1

        # Create H2H record
        existing_h2h = H2HRecord.query.filter(
            H2HRecord.team1_id == home_team.id,
            H2HRecord.team2_id == away_team.id,
            H2HRecord.match_date == match_date
        ).first()
        if not existing_h2h:
            h2h_record = H2HRecord(
                team1_id=home_team.id,
                team2_id=away_team.id,
                match_date=match_date,
                result_for_team1=home_result
            )
            db.session.add(h2h_record)
            h2h_created += 1

        return form_created, h2h_created

    def ingest_team_form(self, external_id, limit=5):
        """
        Fetch recent match results for a specific team to build form records.
        This method is called by the scheduler for each team with an external_id.

        Args:
            external_id: The team's external_id (e.g., 'football_123')
            limit: Number of recent matches to fetch

        Returns:
            Number of form records created
        """
        # Extract ESPN team ID from external_id (format: 'football_{team_id}')
        if not external_id or not external_id.startswith('football_'):
            return 0

        espn_team_id = external_id.replace('football_', '')

        # Get team from DB with its league
        team = Team.query.filter_by(external_id=external_id).first()
        if not team:
            logger.warning(f'Team not found for external_id: {external_id}')
            return 0

        # Get the league's ESPN code from external_id (format: 'espn_{league_code}')
        league = League.query.get(team.league_id)
        if not league or not league.external_id:
            logger.warning(f'League not found for team {team.name}')
            return 0

        espn_league_code = league.external_id.replace('espn_', '')

        # ESPN team schedule endpoint - MUST use league-specific path
        url = f'{BASE_URL}/{espn_league_code}/teams/{espn_team_id}/schedule'
        data = self._make_request(url)

        if not data:
            logger.warning(f'No schedule data for team {espn_team_id}')
            return 0

        events = data.get('events', [])
        form_records_created = 0

        # Filter to finished matches (boxscoreAvailable = true means finished)
        # and sort by date descending
        finished_events = []
        for event in events:
            competitions = event.get('competitions', [])
            if competitions and competitions[0].get('boxscoreAvailable'):
                finished_events.append(event)

        # Sort by date descending and take the most recent
        finished_events.sort(key=lambda e: e.get('date', ''), reverse=True)
        recent_events = finished_events[:limit]

        for event in recent_events:
            # Get teams and scores
            competitions = event.get('competitions', [])
            if not competitions:
                continue

            competition = competitions[0]
            competitors = competition.get('competitors', [])

            if len(competitors) < 2:
                continue

            # Find our team and opponent
            our_team_data = None
            opponent_data = None
            for comp in competitors:
                comp_id = comp.get('id') or comp.get('team', {}).get('id')
                if str(comp_id) == str(espn_team_id):
                    our_team_data = comp
                else:
                    opponent_data = comp

            if not our_team_data or not opponent_data:
                continue

            # Parse scores - schedule endpoint uses score.value or score.displayValue
            try:
                our_score_data = our_team_data.get('score', {})
                opp_score_data = opponent_data.get('score', {})
                # Handle both formats: direct int or nested object
                if isinstance(our_score_data, dict):
                    our_score = int(our_score_data.get('value', our_score_data.get('displayValue', 0)))
                    opponent_score = int(opp_score_data.get('value', opp_score_data.get('displayValue', 0)))
                else:
                    our_score = int(our_score_data or 0)
                    opponent_score = int(opp_score_data or 0)
            except (ValueError, TypeError):
                continue

            # Parse match date
            date_str = event.get('date', '')
            try:
                match_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
            except (ValueError, AttributeError):
                match_date = datetime.utcnow().date()

            # Determine result
            if our_score > opponent_score:
                result = 'W'
            elif our_score < opponent_score:
                result = 'L'
            else:
                result = 'D'

            # Check if form record already exists
            existing = FormRecord.query.filter_by(
                team_id=team.id,
                match_date=match_date
            ).first()

            if not existing:
                form_record = FormRecord(
                    team_id=team.id,
                    match_date=match_date,
                    result=result,
                    goals_scored=our_score,
                    goals_conceded=opponent_score
                )
                db.session.add(form_record)
                form_records_created += 1

        if form_records_created > 0:
            db.session.commit()
            logger.debug(f'Created {form_records_created} form records for team {team.name}')

        return form_records_created
