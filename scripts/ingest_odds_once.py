#!/usr/bin/env python3
"""Run odds ingest exactly once. Costs ~19 API requests (18 football + 1 basketball)."""
import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Prevent APScheduler from starting ESPN background jobs
os.environ['VERCEL'] = '1'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.odds_service import OddsService

app = create_app()

with app.app_context():
    svc = OddsService()
    keys_loaded = len(svc.api_keys)
    print(f'Odds API keys loaded: {keys_loaded}')
    if not keys_loaded:
        print('ERROR: No API keys found — check .env')
        sys.exit(1)

    print('Ingesting football odds (~18 requests)...')
    football = svc.ingest_football_odds()
    print(f'  Football odds records updated: {football}')

    print('Ingesting basketball odds (~1 request)...')
    basketball = svc.ingest_basketball_odds()
    print(f'  Basketball odds records updated: {basketball}')

    print(f'\nDone. Total records: {football + basketball}')
