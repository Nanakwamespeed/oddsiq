import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['VERCEL'] = '1'
from app import create_app
app = create_app()
with app.app_context():
    from app.extensions import db
    from sqlalchemy import text
    r = db.session.execute(text(
        "SELECT "
        "(SELECT COUNT(*) FROM fixtures WHERE status='upcoming' AND kickoff_at >= NOW()) AS upcoming,"
        "(SELECT COUNT(*) FROM predictions p JOIN fixtures f ON f.id=p.fixture_id WHERE f.status='upcoming' AND f.kickoff_at >= NOW()) AS predictions,"
        "(SELECT COUNT(*) FROM market_predictions mp JOIN fixtures f ON f.id=mp.fixture_id WHERE f.status='upcoming' AND f.kickoff_at >= NOW()) AS market_preds,"
        "(SELECT COUNT(*) FROM accuracy_log) AS acc_logs"
    )).fetchone()
    print(f'Upcoming fixtures:  {r[0]}')
    print(f'1x2 predictions:   {r[1]}')
    print(f'Market predictions:{r[2]}')
    print(f'Accuracy logs:     {r[3]}')
