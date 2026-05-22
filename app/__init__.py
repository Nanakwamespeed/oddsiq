"""Flask application factory."""
import os
import json
import logging
from datetime import datetime
from flask import Flask, jsonify, request, g
from .config import config
from .extensions import db, migrate, jwt, cache, mail, cors, limiter, scheduler

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
request_logger = logging.getLogger('api.requests')


def create_app(config_name=None):
    """Create and configure the Flask application."""
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cache.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    # Configure CORS - allow all origins in development
    cors.init_app(app,
        origins='*',
        allow_headers=['Content-Type', 'Authorization', 'X-Requested-With'],
        methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'],
        expose_headers=['Content-Type', 'Authorization']
    )

    # Register blueprints
    register_blueprints(app)

    # Register request/response logging
    register_request_logging(app)

    # Register error handlers
    register_error_handlers(app)

    # Configure JWT callbacks
    configure_jwt(app)

    # Start scheduler — disabled on Vercel (serverless, no persistent process)
    on_vercel = os.getenv('VERCEL') == '1'
    if not app.config.get('TESTING') and not on_vercel:
        start_scheduler(app)

    # Only create tables locally — on Vercel tables already exist on Neon
    if not on_vercel and not app.config.get('TESTING'):
        with app.app_context():
            try:
                db.create_all()
            except Exception as e:
                logger.warning(f'db.create_all() skipped: {e}')

    # Register CLI commands
    register_cli_commands(app)

    logger.info(f'OddsIQ API started in {config_name} mode')

    return app


def register_cli_commands(app):
    """Register CLI commands for data ingestion."""
    import click

    @app.cli.command('ingest-fixtures')
    @click.option('--days', default=7, help='Number of days ahead to fetch')
    def ingest_fixtures(days):
        """Fetch real fixtures from API-Football."""
        from .services.football_service import FootballService

        click.echo('Starting fixture ingestion from API-Football...')

        service = FootballService()

        # Check if API key is configured
        if not service.api_key or service.api_key == 'your-api-football-key':
            click.echo(click.style('ERROR: API_FOOTBALL_KEY not configured in .env', fg='red'))
            click.echo('Get your free API key from: https://rapidapi.com/api-sports/api/api-football')
            return

        # Ingest leagues first
        click.echo('Ingesting leagues...')
        league_count = service.ingest_leagues()
        click.echo(f'  Created {league_count} leagues')

        # Ingest fixtures
        click.echo(f'Fetching fixtures for the next {days} days...')
        fixture_count = service.ingest_fixtures(days_ahead=days)
        click.echo(click.style(f'SUCCESS: Imported {fixture_count} fixtures', fg='green'))

    @app.cli.command('clear-fixtures')
    @click.confirmation_option(prompt='This will delete all fixtures. Continue?')
    def clear_fixtures():
        """Clear all fixtures from the database."""
        from .models.fixture import Fixture
        from .models.prediction import Prediction

        click.echo('Clearing predictions...')
        Prediction.query.delete()

        click.echo('Clearing fixtures...')
        Fixture.query.delete()

        db.session.commit()
        click.echo(click.style('Database cleared', fg='green'))

    @app.cli.command('check-api')
    def check_api():
        """Check if API-Football is configured and working."""
        from .services.football_service import FootballService

        service = FootballService()

        if not service.api_key or service.api_key == 'your-api-football-key':
            click.echo(click.style('API_FOOTBALL_KEY not configured', fg='red'))
            click.echo('\nTo get a free API key:')
            click.echo('1. Go to https://rapidapi.com/api-sports/api/api-football')
            click.echo('2. Sign up (free tier: 100 requests/day)')
            click.echo('3. Copy your API key')
            click.echo('4. Add to .env: API_FOOTBALL_KEY=your-key-here')
            return

        click.echo(f'API Key: {service.api_key[:10]}...')
        click.echo('Testing API connection...')

        # Test the API
        result = service._make_request('status')
        if result is not None:
            click.echo(click.style('API connection successful!', fg='green'))
        else:
            click.echo(click.style('API connection failed. Check your key.', fg='red'))


def register_blueprints(app):
    """Register all blueprints."""
    from .routes.auth import auth_bp
    from .routes.predictions import predictions_bp
    from .routes.fixtures import fixtures_bp
    from .routes.odds import odds_bp
    from .routes.leagues import leagues_bp
    from .routes.guides import guides_bp
    from .routes.accuracy import accuracy_bp
    from .routes.newsletter import newsletter_bp
    from .routes.payments import payments_bp
    from .routes.admin import admin_bp
    from .routes.market_predictions import market_predictions_bp

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(predictions_bp, url_prefix='/api/predictions')
    app.register_blueprint(fixtures_bp, url_prefix='/api/fixtures')
    app.register_blueprint(odds_bp, url_prefix='/api/odds')
    app.register_blueprint(leagues_bp, url_prefix='/api/leagues')
    app.register_blueprint(guides_bp, url_prefix='/api/guides')
    app.register_blueprint(accuracy_bp, url_prefix='/api/accuracy')
    app.register_blueprint(newsletter_bp, url_prefix='/api/newsletter')
    app.register_blueprint(payments_bp, url_prefix='/api/payments')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(market_predictions_bp, url_prefix='/api/markets')

    from .routes.cron import cron_bp
    app.register_blueprint(cron_bp, url_prefix='/api/cron')

    @app.route('/api/health')
    def health():
        try:
            db.session.execute(db.text('SELECT 1'))
            db_status = 'ok'
        except Exception as e:
            db_status = str(e)
        return jsonify({'status': 'ok', 'db': db_status})


def register_request_logging(app):
    """Register request/response logging middleware."""

    # ANSI color codes
    COLORS = {
        'reset': '\033[0m',
        'bold': '\033[1m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'red': '\033[91m',
        'blue': '\033[94m',
        'cyan': '\033[96m',
        'magenta': '\033[95m',
        'gray': '\033[90m',
    }

    def colorize(text, color):
        return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

    def format_json(obj, indent=2):
        """Format JSON with indentation."""
        return json.dumps(obj, indent=indent, default=str, ensure_ascii=False)

    @app.before_request
    def log_request():
        """Log incoming request details."""
        g.request_start_time = datetime.utcnow()

        # Skip logging for static files and OPTIONS
        if request.path.startswith('/static') or request.method == 'OPTIONS':
            return

        # Method color
        method_colors = {
            'GET': 'green',
            'POST': 'blue',
            'PUT': 'yellow',
            'PATCH': 'yellow',
            'DELETE': 'red',
        }
        method_color = method_colors.get(request.method, 'gray')

        # Build log message
        lines = [
            '',
            colorize('━' * 60, 'cyan'),
            colorize('▶ REQUEST', 'bold') + f"  {colorize(request.method, method_color)}  {request.path}",
            colorize('━' * 60, 'cyan'),
            f"  {colorize('Time:', 'gray')}    {g.request_start_time.strftime('%H:%M:%S')}",
        ]

        # Query params
        if request.args:
            lines.append(f"  {colorize('Params:', 'gray')}  {dict(request.args)}")

        # Headers
        if request.headers.get('Authorization'):
            lines.append(f"  {colorize('Auth:', 'gray')}    Bearer ***")
        if request.headers.get('Origin'):
            lines.append(f"  {colorize('Origin:', 'gray')}  {request.headers.get('Origin')}")

        # Request body for POST/PUT/PATCH
        if request.method in ['POST', 'PUT', 'PATCH']:
            try:
                body = request.get_json(silent=True)
                if body:
                    # Mask sensitive fields
                    safe_body = body.copy() if isinstance(body, dict) else body
                    if isinstance(safe_body, dict):
                        for key in ['password', 'current_password', 'new_password', 'refresh_token']:
                            if key in safe_body:
                                safe_body[key] = '***'
                    lines.append(f"  {colorize('Body:', 'gray')}")
                    for line in format_json(safe_body).split('\n'):
                        lines.append(f"    {line}")
            except Exception:
                pass

        print('\n'.join(lines))

    @app.after_request
    def log_response(response):
        """Log outgoing response details."""
        # Skip logging for static files and OPTIONS
        if request.path.startswith('/static') or request.method == 'OPTIONS':
            return response

        # Calculate request duration
        duration = None
        if hasattr(g, 'request_start_time'):
            duration = (datetime.utcnow() - g.request_start_time).total_seconds() * 1000

        # Status color
        if response.status_code >= 500:
            status_color = 'red'
            status_icon = '✗'
        elif response.status_code >= 400:
            status_color = 'yellow'
            status_icon = '⚠'
        else:
            status_color = 'green'
            status_icon = '✓'

        # Build log message
        lines = [
            '',
            colorize(f'◀ RESPONSE', 'bold') + f"  {colorize(status_icon + ' ' + str(response.status_code), status_color)}  {colorize(f'{duration:.1f}ms', 'gray') if duration else ''}",
        ]

        # Response body for JSON responses
        if response.content_type and 'application/json' in response.content_type:
            try:
                response_body = response.get_json(silent=True)
                if response_body:
                    body_str = format_json(response_body)
                    lines.append(f"  {colorize('Response:', 'gray')}")
                    for line in body_str.split('\n'):
                        lines.append(f"    {line}")
            except Exception:
                pass

        lines.append(colorize('━' * 60, 'cyan'))
        print('\n'.join(lines))

        return response


def register_error_handlers(app):
    """Register error handlers."""

    @app.errorhandler(400)
    def bad_request(error):
        logger.error(f'400 error: {error}')
        return jsonify({'error': f'Bad request: {str(error)}', 'code': 400}), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': 'Unauthorized', 'code': 401}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({'error': 'Forbidden', 'code': 403}), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found', 'code': 404}), 404

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        return jsonify({'error': 'Rate limit exceeded', 'code': 429}), 429

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f'Internal server error: {error}')
        return jsonify({'error': 'Internal server error', 'code': 500}), 500


def configure_jwt(app):
    """Configure JWT callbacks."""
    from .models.user import User
    from .models.token import RefreshToken

    @jwt.user_identity_loader
    def user_identity_lookup(user):
        # Return string for JWT compatibility
        return str(user.id) if hasattr(user, 'id') else str(user)

    @jwt.user_lookup_loader
    def user_lookup_callback(_jwt_header, jwt_data):
        identity = jwt_data['sub']
        return User.query.get(int(identity))

    @jwt.additional_claims_loader
    def add_claims_to_access_token(identity):
        user = User.query.get(int(identity))
        if user:
            return {'role': user.role}
        return {}

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'error': 'Token has expired', 'code': 401}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({'error': 'Invalid token', 'code': 401}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({'error': 'Authorization required', 'code': 401}), 401


def start_scheduler(app):
    """Start the APScheduler with all jobs."""
    from .tasks.scheduler import register_jobs

    with app.app_context():
        register_jobs(scheduler, app)

        if not scheduler.running:
            scheduler.start()
            logger.info('APScheduler started')

