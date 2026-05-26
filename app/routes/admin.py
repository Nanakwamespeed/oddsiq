"""Admin routes for managing predictions, users, and guides."""
from datetime import datetime, timedelta
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import func
from ..extensions import db
from ..models.user import User
from ..models.prediction import Prediction
from ..models.guide import Guide
from ..models.accuracy_log import AccuracyLog
from ..models.fixture import Fixture
from ..models.subscription import Subscription
from ..utils.decorators import admin_required
from ..utils.helpers import json_error, json_success

admin_bp = Blueprint('admin', __name__)


# --- Stats & Revenue ---

@admin_bp.route('/stats', methods=['GET'])
@admin_required
def get_stats():
    """Dashboard stats: users by role, revenue, new signups."""
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    # User counts
    total_users = User.query.count()
    free_users = User.query.filter_by(role='free').count()
    premium_users = User.query.filter_by(role='premium').count()
    admin_users = User.query.filter_by(role='admin').count()

    # New signups
    new_last_7 = User.query.filter(User.created_at >= seven_days_ago).count()
    new_last_30 = User.query.filter(User.created_at >= thirty_days_ago).count()

    # Active vs expired premium (by subscription_expires_at)
    active_premium = User.query.filter(
        User.role == 'premium',
        User.subscription_expires_at > now
    ).count()
    no_expiry_premium = User.query.filter(
        User.role == 'premium',
        User.subscription_expires_at == None  # noqa: E711
    ).count()
    expired_premium = User.query.filter(
        User.role == 'premium',
        User.subscription_expires_at <= now
    ).count()

    # Revenue (from subscriptions with amount stored)
    revenue_total = db.session.query(func.sum(Subscription.amount)).scalar() or 0
    revenue_last_30 = db.session.query(func.sum(Subscription.amount)).filter(
        Subscription.created_at >= thirty_days_ago
    ).scalar() or 0
    revenue_last_7 = db.session.query(func.sum(Subscription.amount)).filter(
        Subscription.created_at >= seven_days_ago
    ).scalar() or 0

    # Recent subscriptions
    recent_subs = Subscription.query.order_by(Subscription.created_at.desc()).limit(10).all()

    return json_success(data={
        'users': {
            'total': total_users,
            'free': free_users,
            'premium': premium_users,
            'admin': admin_users,
            'new_last_7_days': new_last_7,
            'new_last_30_days': new_last_30,
        },
        'premium': {
            'active': active_premium + no_expiry_premium,
            'expired': expired_premium,
            'no_expiry': no_expiry_premium,
        },
        'revenue': {
            'total_pesewas': revenue_total,
            'total_ghs': round(revenue_total / 100, 2),
            'last_7_days_ghs': round(revenue_last_7 / 100, 2),
            'last_30_days_ghs': round(revenue_last_30 / 100, 2),
        },
        'recent_subscriptions': [s.to_dict() for s in recent_subs]
    })


# --- Data Ingestion Triggers ---

@admin_bp.route('/ingest', methods=['POST'])
@admin_required
def trigger_ingestion():
    """Manually trigger data ingestion and prediction generation."""
    from ..services.football_service import FootballService
    from ..services.basketball_service import BasketballService
    from ..services.tennis_service import TennisService
    from ..services.prediction_service import PredictionService

    results = {}

    try:
        fs = FootballService()
        fs.ingest_leagues()
        results['football_fixtures'] = fs.ingest_fixtures(days_ahead=7)
    except Exception as e:
        results['football_fixtures_error'] = str(e)

    try:
        bs = BasketballService()
        bs.ingest_leagues()
        results['basketball_fixtures'] = bs.ingest_fixtures(days_ahead=7)
    except Exception as e:
        results['basketball_fixtures_error'] = str(e)

    try:
        ts = TennisService()
        ts.ingest_leagues()
        results['tennis_fixtures'] = ts.ingest_fixtures(days_ahead=7)
    except Exception as e:
        results['tennis_fixtures_error'] = str(e)

    try:
        ps = PredictionService()
        results['predictions_generated'] = ps.generate_predictions_for_upcoming()
    except Exception as e:
        results['predictions_error'] = str(e)

    return json_success(data=results, message='Ingestion complete')


# --- Prediction Management ---

@admin_bp.route('/predictions/<int:prediction_id>/annotate', methods=['POST'])
@admin_required
def annotate_prediction(prediction_id):
    """Add or edit expert note on a prediction."""
    prediction = Prediction.query.get(prediction_id)

    if not prediction:
        return json_error('Prediction not found', 404)

    data = request.get_json() or {}
    expert_note = data.get('expert_note', '').strip()

    prediction.expert_note = expert_note if expert_note else None
    db.session.commit()

    return json_success(
        data=prediction.to_dict_full(),
        message='Expert note updated'
    )


@admin_bp.route('/predictions/<int:prediction_id>/toggle-premium', methods=['POST'])
@admin_required
def toggle_prediction_premium(prediction_id):
    """Toggle premium status of a prediction."""
    prediction = Prediction.query.get(prediction_id)

    if not prediction:
        return json_error('Prediction not found', 404)

    prediction.is_premium = not prediction.is_premium
    db.session.commit()

    return json_success(
        data=prediction.to_dict_full(),
        message=f'Prediction {"marked as premium" if prediction.is_premium else "set to free"}'
    )


# --- User Management ---

@admin_bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    """List all users with subscription status."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    role = request.args.get('role')

    query = User.query

    if role and role in ['free', 'premium', 'admin']:
        query = query.filter_by(role=role)

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    users = [user.to_dict(include_email=True) for user in pagination.items]

    return json_success(data={
        'users': users,
        'page': page,
        'per_page': per_page,
        'total': pagination.total,
        'total_pages': pagination.pages
    })


@admin_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def update_user_role(user_id):
    """Change a user's role and optionally set subscription expiry."""
    from datetime import datetime
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    data = request.get_json() or {}
    new_role = data.get('role')

    if new_role not in ['free', 'premium', 'admin']:
        return json_error('Invalid role. Choose free, premium, or admin.', 400)

    user.role = new_role

    if new_role == 'premium' and data.get('expires_at'):
        try:
            user.subscription_expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return json_error('Invalid expires_at format. Use ISO 8601.', 400)
    elif new_role == 'free':
        user.subscription_expires_at = None

    db.session.commit()

    return json_success(
        data=user.to_dict(include_email=True),
        message=f'User updated to {new_role}'
    )


# --- Guide Management ---

@admin_bp.route('/guides', methods=['POST'])
@admin_required
def create_guide():
    """Create a new betting guide."""
    data = request.get_json() or {}

    title = data.get('title', '').strip()
    body = data.get('body', '').strip()
    sport_id = data.get('sport_id')
    published = data.get('published', False)

    if not title or not body:
        return json_error('Title and body are required', 400)

    # Generate slug
    slug = Guide.generate_slug(title)

    # Check for duplicate slug
    existing = Guide.query.filter_by(slug=slug).first()
    if existing:
        slug = f'{slug}-{Guide.query.count() + 1}'

    guide = Guide(
        title=title,
        slug=slug,
        body=body,
        sport_id=sport_id,
        published=published
    )
    db.session.add(guide)
    db.session.commit()

    return json_success(
        data=guide.to_dict(),
        message='Guide created',
        code=201
    )


@admin_bp.route('/guides/<int:guide_id>', methods=['PUT'])
@admin_required
def update_guide(guide_id):
    """Update an existing guide."""
    guide = Guide.query.get(guide_id)

    if not guide:
        return json_error('Guide not found', 404)

    data = request.get_json() or {}

    if 'title' in data:
        guide.title = data['title'].strip()
        guide.slug = Guide.generate_slug(guide.title)

    if 'body' in data:
        guide.body = data['body'].strip()

    if 'sport_id' in data:
        guide.sport_id = data['sport_id']

    if 'published' in data:
        guide.published = bool(data['published'])

    db.session.commit()

    return json_success(
        data=guide.to_dict(),
        message='Guide updated'
    )


@admin_bp.route('/guides/<int:guide_id>', methods=['DELETE'])
@admin_required
def delete_guide(guide_id):
    """Delete a guide."""
    guide = Guide.query.get(guide_id)

    if not guide:
        return json_error('Guide not found', 404)

    db.session.delete(guide)
    db.session.commit()

    return json_success(message='Guide deleted')


# --- Accuracy Logging ---

@admin_bp.route('/accuracy/log', methods=['POST'])
@admin_required
def log_accuracy():
    """Manually log actual match outcome against prediction."""
    data = request.get_json() or {}

    prediction_id = data.get('prediction_id')
    actual_outcome = data.get('actual_outcome')

    if not prediction_id or not actual_outcome:
        return json_error('prediction_id and actual_outcome are required', 400)

    if actual_outcome not in ['home', 'draw', 'away']:
        return json_error('Invalid outcome. Choose home, draw, or away.', 400)

    prediction = Prediction.query.get(prediction_id)
    if not prediction:
        return json_error('Prediction not found', 404)

    # Check if already logged
    existing = AccuracyLog.query.filter_by(prediction_id=prediction_id).first()
    if existing:
        return json_error('Accuracy already logged for this prediction', 409)

    # Determine if prediction was correct
    was_correct = prediction.predicted_outcome == actual_outcome

    accuracy_log = AccuracyLog(
        prediction_id=prediction_id,
        actual_outcome=actual_outcome,
        was_correct=was_correct
    )
    db.session.add(accuracy_log)
    db.session.commit()

    return json_success(
        data=accuracy_log.to_dict(),
        message=f'Accuracy logged. Prediction was {"correct" if was_correct else "incorrect"}.',
        code=201
    )
