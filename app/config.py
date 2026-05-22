"""Application configuration loaded from environment variables."""
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')

    # Database — expects DATABASE_URL in env (Neon PostgreSQL)
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', '').replace('postgres://', 'postgresql://')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'connect_args': {'sslmode': 'require'},
    }

    # JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'jwt-dev-secret-key')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    JWT_TOKEN_LOCATION = ['headers']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'

    # Cache - use SimpleCache for development (no Redis needed)
    CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = 60  # 1 minute default for dev

    # CORS
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

    # Rate limiting — use memory backend unless Redis is provided
    RATELIMIT_STORAGE_URL = os.getenv('REDIS_URL', 'memory://')
    RATELIMIT_DEFAULT = '100/minute'
    RATELIMIT_HEADERS_ENABLED = True

    # Sports APIs
    API_FOOTBALL_KEY = os.getenv('API_FOOTBALL_KEY', '')
    API_FOOTBALL_BASE_URL = 'https://api-football-v1.p.rapidapi.com/v3'

    # AllSportsAPI
    ALLSPORTS_API_KEY = os.getenv('ALLSPORTS_API_KEY', '')

    THE_ODDS_API_KEY = os.getenv('THE_ODDS_API_KEY', '')
    THE_ODDS_API_BASE_URL = 'https://api.the-odds-api.com/v4'

    API_TENNIS_KEY = os.getenv('API_TENNIS_KEY', '')
    API_TENNIS_BASE_URL = 'https://api-tennis.p.rapidapi.com'

    BALLDONTLIE_BASE_URL = 'https://api.balldontlie.io/v1'

    # Affiliate URLs
    BETWAY_AFFILIATE_URL = os.getenv('BETWAY_AFFILIATE_URL', 'https://betway.com.gh/?ref=')
    ONEXBET_AFFILIATE_URL = os.getenv('ONEXBET_AFFILIATE_URL', 'https://1xbet.com/?ref=')
    SPORTYBET_AFFILIATE_URL = os.getenv('SPORTYBET_AFFILIATE_URL', 'https://sportybet.com/?ref=')
    BET365_AFFILIATE_URL = os.getenv('BET365_AFFILIATE_URL', 'https://bet365.com/?ref=')
    AFFILIATE_CODE = os.getenv('AFFILIATE_CODE', 'oddsiq')

    # Paystack
    PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY', '')
    PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY', '')
    PAYSTACK_BASE_URL = 'https://api.paystack.co'

    # Mail
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@oddsiq.com')

    # Subscription pricing (in pesewas)
    MONTHLY_PLAN_AMOUNT = int(os.getenv('MONTHLY_PLAN_AMOUNT', 5000))
    ANNUAL_PLAN_AMOUNT = int(os.getenv('ANNUAL_PLAN_AMOUNT', 50000))


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SQLALCHEMY_ECHO = False


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    CACHE_TYPE = 'SimpleCache'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
