#!/usr/bin/env python3
"""One-shot: fetch Club Elo strength ratings for all teams."""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
os.environ['VERCEL'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.understat_service import UnderstatService

app = create_app()
with app.app_context():
    print('Fetching Club Elo strength ratings...')
    total = UnderstatService().ingest_xg_stats()
    print(f'Done: {total} teams updated with Elo ratings')
