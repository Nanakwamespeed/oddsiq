#!/usr/bin/env python3
"""Copy all data from the Neon dev branch to the main branch.

Dev:  ep-winter-frog-apwwek07-pooler  (current production)
Main: ep-calm-hill-apuk1cwt-pooler    (target production)
"""
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

os.environ['VERCEL'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text, inspect

DEV_URL  = "postgresql://neondb_owner:npg_gEA6hem3VLOY@ep-winter-frog-apwwek07-pooler.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require"
MAIN_URL = "postgresql://neondb_owner:npg_gEA6hem3VLOY@ep-calm-hill-apuk1cwt-pooler.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require"

dev_engine  = create_engine(DEV_URL,  connect_args={'sslmode': 'require'}, pool_pre_ping=True)
main_engine = create_engine(MAIN_URL, connect_args={'sslmode': 'require'}, pool_pre_ping=True)

# Create schema on main using Flask's db.create_all()
print("Creating schema on main branch...")
from app import create_app
app = create_app()
with app.app_context():
    from app.extensions import db
    import app.models  # noqa: F401 — registers all models with metadata
    # Create tables directly on the main engine (bypasses app's configured URL)
    db.metadata.create_all(main_engine)
    print("  Schema created on main.")

# Tables in FK-safe copy order
TABLES = [
    'sports',
    'leagues',
    'teams',
    'fixtures',
    'predictions',
    'odds',
    'market_odds',
    'market_predictions',
    'h2h_records',
    'form_records',
    'team_xg_stats',
    'team_stats',
    'accuracy_logs',
    'market_accuracy_logs',
    'users',
    'refresh_tokens',
    'subscriptions',
    'guides',
    'newsletter_subscribers',
]

# Truncate order: leaf → root (reverse of insert order)
TRUNCATE_ORDER = [
    'market_accuracy_logs',
    'accuracy_logs',
    'subscriptions',
    'refresh_tokens',
    'market_predictions',
    'predictions',
    'odds',
    'market_odds',
    'h2h_records',
    'form_records',
    'team_xg_stats',
    'team_stats',
    'fixtures',
    'teams',
    'leagues',
    'sports',
    'users',
    'guides',
    'newsletter_subscribers',
]

def get_cols(engine, table):
    with engine.connect() as conn:
        rows = conn.execute(text(
            f"SELECT column_name FROM information_schema.columns "
            f"WHERE table_name='{table}' ORDER BY ordinal_position"
        )).fetchall()
    return [r[0] for r in rows]

def fetch_rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT * FROM {table}")).fetchall()

def run_dst(engine, sql, params=None):
    with engine.begin() as conn:
        if params:
            conn.execute(text(sql), params)
        else:
            conn.execute(text(sql))

# Get table list from dev
with dev_engine.connect() as c:
    existing_tables = set(inspect(dev_engine).get_table_names())

# Delete all tables in reverse FK order (fresh connection each time)
print("Clearing main tables...")
for table in TRUNCATE_ORDER:
    if table in existing_tables:
        run_dst(main_engine, f"DELETE FROM {table}")
        print(f"  cleared {table}")

# Insert in FK-safe order — fresh src + dst connections per table
CHUNK = 150
for table in TABLES:
    if table not in existing_tables:
        print(f"  Skipping {table} (not in dev schema)")
        continue

    rows = fetch_rows(dev_engine, table)
    if not rows:
        print(f"  {table}: empty, skipping")
        continue

    col_names = get_cols(dev_engine, table)
    col_list     = ', '.join(col_names)
    placeholders = ', '.join([f':{c}' for c in col_names])
    def serialize(v):
        return json.dumps(v) if isinstance(v, (dict, list)) else v

    batch = [{k: serialize(v) for k, v in zip(col_names, row)} for row in rows]

    for i in range(0, len(batch), CHUNK):
        run_dst(main_engine,
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
                batch[i:i+CHUNK])
    print(f"  {table}: copied {len(rows)} rows")

# Reset sequences
print("\nResetting sequences...")
with dev_engine.connect() as src:
    seqs = src.execute(text(
        "SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema='public'"
    )).fetchall()
    for (seq,) in seqs:
        try:
            max_val = src.execute(text(f"SELECT last_value FROM {seq}")).scalar()
            run_dst(main_engine, f"SELECT setval('{seq}', {max_val}, true)")
            print(f"  {seq} → {max_val}")
        except Exception as e:
            print(f"  {seq}: skipped ({e})")

print("\nDone! Main branch is now populated.")
print(f"\nUpdate your Vercel DATABASE_URL to:")
print(f"  {MAIN_URL}")
