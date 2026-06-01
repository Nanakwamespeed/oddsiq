"""The Odds API integration service."""
import logging
from datetime import datetime
import requests
from flask import current_app
from ..extensions import db
from ..models.fixture import Fixture
from ..models.odds import Odds
from ..models.market_odds import MarketOdds
from ..models.league import League

logger = logging.getLogger(__name__)

# Margin adjustment for fair odds calculation
BOOKMAKER_MARGIN = 0.05  # Typical 5% margin


class OddsService:
    """Service for fetching odds from The Odds API."""

    # Sport keys for The Odds API
    SPORT_KEYS = {
        'football': 'soccer_epl',  # Will need to handle multiple leagues
        'basketball': 'basketball_nba',
        'tennis': 'tennis_atp_french_open'  # Example, changes per tournament
    }

    # Bookmaker name mappings for affiliate URLs
    BOOKMAKER_AFFILIATES = {
        'betway': 'BETWAY_AFFILIATE_URL',
        '1xbet': 'ONEXBET_AFFILIATE_URL',
        'sportybet': 'SPORTYBET_AFFILIATE_URL',
        'bet365': 'BET365_AFFILIATE_URL',
    }

    def __init__(self):
        self.api_keys = [k for k in [
            current_app.config.get('THE_ODDS_API_KEY', ''),
            current_app.config.get('THE_ODDS_API_KEY_2', ''),
        ] if k]
        self.base_url = current_app.config['THE_ODDS_API_BASE_URL']
        self.affiliate_code = current_app.config.get('AFFILIATE_CODE', 'oddsiq')

    def _make_request(self, endpoint, params=None):
        """Make a request to The Odds API, falling back to secondary key on quota exhaustion."""
        if not self.api_keys:
            logger.warning('No Odds API keys configured')
            return None

        if params is None:
            params = {}

        for key in self.api_keys:
            params['apiKey'] = key
            try:
                url = f'{self.base_url}/{endpoint}'
                response = requests.get(url, params=params, timeout=30)
                if response.status_code in (401, 429):
                    logger.warning(f'Odds API key quota/limit hit ({response.status_code}), trying next key')
                    continue
                if response.status_code == 404:
                    # Sport not available (off-season or not on free tier) — not an error
                    return None
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                logger.error(f'The Odds API request failed: {e}')
                return None

        logger.error('All Odds API keys exhausted or failed')
        return None

    def _get_affiliate_url(self, bookmaker_name):
        """Get affiliate URL for a bookmaker."""
        bookmaker_lower = bookmaker_name.lower()

        for key, config_key in self.BOOKMAKER_AFFILIATES.items():
            if key in bookmaker_lower:
                base_url = current_app.config.get(config_key, '')
                if base_url:
                    return f'{base_url}{self.affiliate_code}'

        return None

    def get_available_sports(self):
        """Get list of available sports from the API."""
        return self._make_request('sports')

    def ingest_odds_for_sport(self, sport_key, regions='eu', markets='h2h,totals'):
        """
        Fetch and store odds for a specific sport.
        Free tier: 500 requests/month, so use sparingly.
        Fetches h2h (1X2), totals (Over/Under), and calculates Double Chance.
        """
        odds_data = self._make_request(f'sports/{sport_key}/odds', {
            'regions': regions,
            'markets': markets,
            'oddsFormat': 'decimal'
        })

        if not odds_data:
            return 0

        h2h_count = 0
        market_count = 0
        double_chance_count = 0
        btts_count = 0

        for event in odds_data:
            # Add sport key to event for league detection
            event['sport_key'] = sport_key

            # Try to match to existing fixture (or create if missing)
            fixture = self._match_fixture(event, create_if_missing=True)
            if not fixture:
                continue

            # Process bookmakers
            for bookmaker in event.get('bookmakers', []):
                bookmaker_name = bookmaker.get('title', 'Unknown')
                affiliate_url = self._get_affiliate_url(bookmaker_name)

                for market in bookmaker.get('markets', []):
                    market_key = market.get('key')

                    if market_key == 'h2h':
                        # Process 1X2 odds
                        outcomes = {o['name']: o['price'] for o in market.get('outcomes', [])}
                        home_odds = outcomes.get(event.get('home_team'))
                        away_odds = outcomes.get(event.get('away_team'))
                        draw_odds = outcomes.get('Draw')

                        if not home_odds or not away_odds:
                            continue

                        # Update or create odds record
                        existing = Odds.query.filter_by(
                            fixture_id=fixture.id,
                            bookmaker_name=bookmaker_name
                        ).first()

                        if existing:
                            existing.home_win_odds = home_odds
                            existing.draw_odds = draw_odds
                            existing.away_win_odds = away_odds
                            existing.affiliate_url = affiliate_url
                            existing.fetched_at = datetime.utcnow()
                        else:
                            odds_record = Odds(
                                fixture_id=fixture.id,
                                bookmaker_name=bookmaker_name,
                                affiliate_url=affiliate_url,
                                home_win_odds=home_odds,
                                draw_odds=draw_odds,
                                away_win_odds=away_odds
                            )
                            db.session.add(odds_record)

                        h2h_count += 1

                    elif market_key == 'totals':
                        # Process Over/Under odds
                        for outcome in market.get('outcomes', []):
                            point = outcome.get('point')  # e.g., 2.5
                            name = outcome.get('name')    # "Over" or "Under"
                            price = outcome.get('price')

                            if point is None or not name or not price:
                                continue

                            # Find or create market odds record for this line
                            existing = MarketOdds.query.filter_by(
                                fixture_id=fixture.id,
                                bookmaker_name=bookmaker_name,
                                market_type='over_under',
                                line_value=point
                            ).first()

                            if existing:
                                # Update existing odds_data
                                odds_dict = existing.odds_data or {}
                                odds_dict[name.lower()] = price
                                existing.odds_data = odds_dict
                                existing.fetched_at = datetime.utcnow()
                            else:
                                # Create new record
                                odds_dict = {name.lower(): price}
                                market_odds = MarketOdds(
                                    fixture_id=fixture.id,
                                    bookmaker_name=bookmaker_name,
                                    affiliate_url=affiliate_url,
                                    market_type='over_under',
                                    line_value=point,
                                    odds_data=odds_dict
                                )
                                db.session.add(market_odds)

                            market_count += 1

                    elif market_key == 'btts':
                        # Process Both Teams To Score odds
                        outcomes = {o['name'].lower(): o['price'] for o in market.get('outcomes', [])}
                        yes_odds = outcomes.get('yes')
                        no_odds = outcomes.get('no')

                        if yes_odds and no_odds:
                            existing = MarketOdds.query.filter_by(
                                fixture_id=fixture.id,
                                bookmaker_name=bookmaker_name,
                                market_type='btts'
                            ).first()

                            odds_dict = {'yes': yes_odds, 'no': no_odds}

                            if existing:
                                existing.odds_data = odds_dict
                                existing.fetched_at = datetime.utcnow()
                            else:
                                market_odds = MarketOdds(
                                    fixture_id=fixture.id,
                                    bookmaker_name=bookmaker_name,
                                    affiliate_url=affiliate_url,
                                    market_type='btts',
                                    odds_data=odds_dict
                                )
                                db.session.add(market_odds)

                            btts_count += 1

                # After processing h2h, calculate and store Double Chance odds
                # Double Chance is derived from 1X2 odds
                h2h_market = next((m for m in bookmaker.get('markets', []) if m.get('key') == 'h2h'), None)
                if h2h_market:
                    outcomes = {o['name']: o['price'] for o in h2h_market.get('outcomes', [])}
                    home_odds = outcomes.get(event.get('home_team'))
                    away_odds = outcomes.get(event.get('away_team'))
                    draw_odds = outcomes.get('Draw')

                    if home_odds and away_odds and draw_odds:
                        dc_odds = self._calculate_double_chance_odds(home_odds, draw_odds, away_odds)

                        existing = MarketOdds.query.filter_by(
                            fixture_id=fixture.id,
                            bookmaker_name=bookmaker_name,
                            market_type='double_chance'
                        ).first()

                        if existing:
                            existing.odds_data = dc_odds
                            existing.fetched_at = datetime.utcnow()
                        else:
                            market_odds = MarketOdds(
                                fixture_id=fixture.id,
                                bookmaker_name=bookmaker_name,
                                affiliate_url=affiliate_url,
                                market_type='double_chance',
                                odds_data=dc_odds
                            )
                            db.session.add(market_odds)

                        double_chance_count += 1

        db.session.commit()
        logger.info(f'Updated {h2h_count} h2h, {market_count} O/U, {double_chance_count} DC, {btts_count} BTTS odds for {sport_key}')
        return h2h_count + market_count + double_chance_count + btts_count

    def _calculate_double_chance_odds(self, home_odds, draw_odds, away_odds):
        """
        Calculate Double Chance odds from 1X2 odds.

        Double Chance markets:
        - 1X: Home Win OR Draw
        - X2: Draw OR Away Win
        - 12: Home Win OR Away Win

        Uses implied probabilities with margin adjustment.
        """
        # Convert odds to implied probabilities
        home_prob = 1 / home_odds
        draw_prob = 1 / draw_odds
        away_prob = 1 / away_odds

        # Total implied probability (includes bookmaker margin)
        total_prob = home_prob + draw_prob + away_prob

        # Normalize to remove margin for fair probabilities
        home_fair = home_prob / total_prob
        draw_fair = draw_prob / total_prob
        away_fair = away_prob / total_prob

        # Calculate double chance probabilities
        dc_1x_prob = home_fair + draw_fair  # Home or Draw
        dc_x2_prob = draw_fair + away_fair  # Draw or Away
        dc_12_prob = home_fair + away_fair  # Home or Away

        # Add back a small margin for realistic odds
        margin_factor = 1 - BOOKMAKER_MARGIN

        # Convert back to odds
        dc_odds = {
            '1X': round(1 / (dc_1x_prob * margin_factor), 2),
            'X2': round(1 / (dc_x2_prob * margin_factor), 2),
            '12': round(1 / (dc_12_prob * margin_factor), 2)
        }

        return dc_odds

    def _match_fixture(self, event, create_if_missing=True):
        """
        Try to match an API event to a database fixture.
        If create_if_missing=True, creates teams and fixtures that don't exist.
        """
        home_team_name = event.get('home_team', '')
        away_team_name = event.get('away_team', '')
        commence_time = event.get('commence_time')
        sport_key = event.get('sport_key', '')

        if not home_team_name or not away_team_name:
            return None

        # Parse commence time
        try:
            if commence_time:
                kickoff = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
            else:
                return None
        except ValueError:
            return None

        from ..models.team import Team
        from ..models.sport import Sport
        from datetime import timedelta

        # Find or create home team
        home = Team.query.filter(Team.name.ilike(f'%{home_team_name}%')).first()
        if not home and create_if_missing:
            # Determine league based on sport_key
            league = self._get_or_create_league_for_sport(sport_key)
            if league:
                home = Team(name=home_team_name, league_id=league.id)
                db.session.add(home)
                db.session.flush()
                logger.info(f'Created team: {home_team_name}')

        if not home:
            return None

        # Find or create away team
        away = Team.query.filter(Team.name.ilike(f'%{away_team_name}%')).first()
        if not away and create_if_missing:
            league = self._get_or_create_league_for_sport(sport_key)
            if league:
                away = Team(name=away_team_name, league_id=league.id)
                db.session.add(away)
                db.session.flush()
                logger.info(f'Created team: {away_team_name}')

        if not away:
            return None

        # Find fixture within 24 hours of commence time
        start_window = kickoff - timedelta(hours=12)
        end_window = kickoff + timedelta(hours=12)

        fixture = Fixture.query.filter(
            Fixture.home_team_id == home.id,
            Fixture.away_team_id == away.id,
            Fixture.kickoff_at.between(start_window, end_window)
        ).first()

        # Create fixture if it doesn't exist
        if not fixture and create_if_missing:
            league = self._get_or_create_league_for_sport(sport_key)
            if league:
                fixture = Fixture(
                    home_team_id=home.id,
                    away_team_id=away.id,
                    league_id=league.id,
                    kickoff_at=kickoff,
                    status='upcoming'
                )
                db.session.add(fixture)
                db.session.flush()
                logger.info(f'Created fixture: {home_team_name} vs {away_team_name}')

        return fixture

    def _get_or_create_league_for_sport(self, sport_key):
        """Get or create a league based on The Odds API sport key."""
        from ..models.sport import Sport

        # Map sport keys to league info
        SPORT_KEY_MAP = {
            'soccer_epl': ('football', 'Premier League', 'England', 'domestic'),
            'soccer_england_championship': ('football', 'Championship', 'England', 'domestic'),
            'soccer_spain_la_liga': ('football', 'La Liga', 'Spain', 'domestic'),
            'soccer_germany_bundesliga': ('football', 'Bundesliga', 'Germany', 'domestic'),
            'soccer_italy_serie_a': ('football', 'Serie A', 'Italy', 'domestic'),
            'soccer_france_ligue_one': ('football', 'Ligue 1', 'France', 'domestic'),
            'soccer_netherlands_eredivisie': ('football', 'Eredivisie', 'Netherlands', 'domestic'),
            'soccer_portugal_primeira_liga': ('football', 'Primeira Liga', 'Portugal', 'domestic'),
            'soccer_scotland_premiership': ('football', 'Scottish Premiership', 'Scotland', 'domestic'),
            'soccer_belgium_first_div': ('football', 'Belgian First Division A', 'Belgium', 'domestic'),
            'soccer_turkey_super_league': ('football', 'Süper Lig', 'Turkey', 'domestic'),
            'soccer_usa_mls': ('football', 'MLS', 'USA', 'domestic'),
            'soccer_mexico_ligamx': ('football', 'Liga MX', 'Mexico', 'domestic'),
            'soccer_brazil_campeonato': ('football', 'Brasileirão', 'Brazil', 'domestic'),
            'soccer_argentina_primera_division': ('football', 'Primera División', 'Argentina', 'domestic'),
            'soccer_uefa_champs_league': ('football', 'UEFA Champions League', 'Europe', 'international_club'),
            'soccer_uefa_europa_league': ('football', 'UEFA Europa League', 'Europe', 'international_club'),
            'soccer_conmebol_copa_libertadores': ('football', 'Copa Libertadores', 'South America', 'international_club'),
            'basketball_nba': ('basketball', 'NBA', 'USA', 'domestic'),
            'basketball_euroleague': ('basketball', 'EuroLeague', 'Europe', 'international_club'),
        }

        if sport_key not in SPORT_KEY_MAP:
            return None

        sport_name, league_name, country, league_type = SPORT_KEY_MAP[sport_key]

        # Get or create sport
        sport = Sport.query.filter_by(name=sport_name).first()
        if not sport:
            sport = Sport(name=sport_name)
            db.session.add(sport)
            db.session.flush()

        # Get or create league
        league = League.query.filter_by(name=league_name, sport_id=sport.id).first()
        if not league:
            league = League(
                name=league_name,
                country=country,
                sport_id=sport.id,
                league_type=league_type
            )
            db.session.add(league)
            db.session.flush()
            logger.info(f'Created league: {league_name}')

        return league

    # Ordered by expected fixture volume so high-value leagues come first.
    # Free tier: 500 requests/month — each sport key costs 1 request.
    FOOTBALL_SPORT_KEYS = [
        'soccer_epl',
        'soccer_spain_la_liga',
        'soccer_germany_bundesliga',
        'soccer_italy_serie_a',
        'soccer_france_ligue_one',
        'soccer_uefa_champs_league',
        'soccer_uefa_europa_league',
        'soccer_netherlands_eredivisie',
        'soccer_portugal_primeira_liga',
        'soccer_england_championship',
        'soccer_scotland_premiership',
        'soccer_belgium_first_div',
        'soccer_turkey_super_league',
        'soccer_usa_mls',
        'soccer_mexico_ligamx',
        'soccer_brazil_campeonato',
        'soccer_argentina_primera_division',
        'soccer_conmebol_copa_libertadores',
    ]

    def _get_active_sport_keys(self):
        """Return the set of sport keys currently marked active by The Odds API."""
        data = self._make_request('sports')
        if not data:
            return None  # Can't determine — caller should fall back to full list
        return {s['key'] for s in data if s.get('active')}

    def ingest_football_odds(self):
        """Ingest odds for active football leagues only (conserves monthly quota)."""
        active = self._get_active_sport_keys()
        total = 0
        for sport_key in self.FOOTBALL_SPORT_KEYS:
            if active is not None and sport_key not in active:
                logger.info(f'Skipping {sport_key} — not active in The Odds API')
                continue
            count = self.ingest_odds_for_sport(sport_key)
            if count:
                logger.info(f'  {sport_key}: {count} odds records')
            total += count
        return total

    def ingest_basketball_odds(self):
        """Ingest odds for NBA."""
        return self.ingest_odds_for_sport('basketball_nba')

    def get_best_odds(self, fixture_id, outcome):
        """Get the best odds for a specific outcome."""
        odds = Odds.query.filter_by(fixture_id=fixture_id).all()

        if not odds:
            return None

        if outcome == 'home':
            best = max(odds, key=lambda o: o.home_win_odds)
            return {
                'odds': best.home_win_odds,
                'bookmaker': best.bookmaker_name,
                'affiliate_url': best.affiliate_url
            }
        elif outcome == 'away':
            best = max(odds, key=lambda o: o.away_win_odds)
            return {
                'odds': best.away_win_odds,
                'bookmaker': best.bookmaker_name,
                'affiliate_url': best.affiliate_url
            }
        elif outcome == 'draw':
            odds_with_draw = [o for o in odds if o.draw_odds]
            if not odds_with_draw:
                return None
            best = max(odds_with_draw, key=lambda o: o.draw_odds)
            return {
                'odds': best.draw_odds,
                'bookmaker': best.bookmaker_name,
                'affiliate_url': best.affiliate_url
            }

        return None

    def get_market_odds(self, fixture_id, market_type, line_value=None):
        """
        Get all odds for a specific market type.

        Args:
            fixture_id: ID of the fixture
            market_type: 'over_under', 'btts', 'double_chance'
            line_value: For O/U markets (e.g., 2.5)

        Returns:
            List of odds records from different bookmakers
        """
        query = MarketOdds.query.filter_by(
            fixture_id=fixture_id,
            market_type=market_type
        )

        if line_value is not None:
            query = query.filter_by(line_value=line_value)

        return query.all()

    def get_best_market_odds(self, fixture_id, market_type, outcome, line_value=None):
        """
        Get the best odds for a specific market outcome.

        Args:
            fixture_id: ID of the fixture
            market_type: 'over_under', 'btts', 'double_chance'
            outcome: 'over', 'under', 'yes', 'no', '1X', 'X2', '12'
            line_value: For O/U markets (e.g., 2.5)

        Returns:
            Dict with best odds, bookmaker, and affiliate URL
        """
        odds_records = self.get_market_odds(fixture_id, market_type, line_value)

        if not odds_records:
            return None

        best_odds = 0
        best_record = None

        for record in odds_records:
            odds_data = record.odds_data or {}
            odds_value = odds_data.get(outcome)

            if odds_value and odds_value > best_odds:
                best_odds = odds_value
                best_record = record

        if best_record:
            return {
                'odds': best_odds,
                'bookmaker': best_record.bookmaker_name,
                'affiliate_url': best_record.affiliate_url,
                'market_type': market_type,
                'outcome': outcome,
                'line_value': line_value
            }

        return None

    def get_all_market_odds_for_fixture(self, fixture_id):
        """
        Get all market odds for a fixture, grouped by market type.

        Returns:
            Dict with market types as keys and list of odds as values
        """
        odds_records = MarketOdds.query.filter_by(fixture_id=fixture_id).all()

        grouped = {}
        for record in odds_records:
            market_type = record.market_type

            if market_type not in grouped:
                grouped[market_type] = []

            grouped[market_type].append(record.to_dict())

        return grouped
