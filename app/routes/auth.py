"""Authentication routes with JWT token rotation."""
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
    get_jwt
)
from ..extensions import db, limiter
from ..models.user import User
from ..models.token import RefreshToken
from ..utils.helpers import json_error, json_success, validate_email

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/register', methods=['POST'])
@limiter.limit('100 per minute')
def register():
    """Register a new user."""
    data = request.get_json()

    if not data:
        return json_error('No data provided', 400)

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    first_name = data.get('first_name', '').strip()
    last_name = data.get('last_name', '').strip()
    other_names = data.get('other_names', '').strip()

    # Validate email
    if not email or not validate_email(email):
        return json_error('Invalid email address', 400)

    # Validate password
    if not password or len(password) < 6:
        return json_error('Password must be at least 6 characters', 400)

    # Validate required name fields
    if not first_name:
        return json_error('First name is required', 400)
    if not last_name:
        return json_error('Last name is required', 400)

    # Check if user exists
    if User.query.filter_by(email=email).first():
        return json_error('Email already registered', 409)

    # Create user
    user = User(
        email=email,
        role='free',
        first_name=first_name,
        last_name=last_name,
        other_names=other_names or None,
    )
    user.set_password(password)

    db.session.add(user)
    db.session.commit()

    return json_success(
        data=user.to_dict(include_email=True),
        message='Registration successful',
        code=201
    )


@auth_bp.route('/login', methods=['POST'])
@limiter.limit('100 per minute')
def login():
    """Login and get access + refresh tokens."""
    data = request.get_json()

    if not data:
        return json_error('No data provided', 400)

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return json_error('Email and password required', 400)

    # Find user
    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        return json_error('Invalid email or password', 401)

    # Create access token (identity must be a string for JWT)
    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={'role': user.role}
    )

    # Create refresh token and store hash in DB
    refresh_expires = datetime.utcnow() + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
    refresh_token, _ = RefreshToken.create_for_user(user.id, refresh_expires)

    return json_success(data={
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': user.to_dict(include_email=True)
    })


@auth_bp.route('/refresh', methods=['POST'])
@limiter.limit('100 per minute')
def refresh():
    """
    Refresh access token using refresh token.
    Implements token rotation and reuse detection.
    """
    data = request.get_json()

    if not data:
        return json_error('No data provided', 400)

    refresh_token = data.get('refresh_token', '')

    if not refresh_token:
        return json_error('Refresh token required', 400)

    # Find token by hash
    token_record = RefreshToken.find_by_token(refresh_token)

    if not token_record:
        return json_error('Invalid refresh token', 401)

    # Check if token was revoked (reuse detection)
    if token_record.revoked:
        # Security breach detected - revoke all tokens for this user
        RefreshToken.revoke_all_for_user(token_record.user_id)
        return json_error('Token reuse detected. All sessions revoked.', 401)

    # Check if token is expired
    if token_record.expires_at < datetime.utcnow():
        return json_error('Refresh token expired', 401)

    # Get user
    user = User.query.get(token_record.user_id)
    if not user:
        return json_error('User not found', 401)

    # Revoke old refresh token
    token_record.revoke()

    # Create new access token
    access_token = create_access_token(
        identity=user.id,
        additional_claims={'role': user.role}
    )

    # Create new refresh token (rotation)
    refresh_expires = datetime.utcnow() + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']
    new_refresh_token, _ = RefreshToken.create_for_user(user.id, refresh_expires)

    return json_success(data={
        'access_token': access_token,
        'refresh_token': new_refresh_token,
        'user': user.to_dict(include_email=True)
    })


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout and revoke refresh token."""
    data = request.get_json() or {}
    refresh_token = data.get('refresh_token', '')

    if refresh_token:
        # Revoke the specific refresh token
        token_record = RefreshToken.find_by_token(refresh_token)
        if token_record:
            token_record.revoke()

    return json_success(message='Logged out successfully')


@auth_bp.route('/me', methods=['GET'])
@auth_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current user info."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    return json_success(data=user.to_dict(include_email=True))


@auth_bp.route('/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """Update current user profile."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    data = request.get_json() or {}

    # Update allowed fields
    if 'name' in data:
        user.name = data['name'].strip()

    db.session.commit()

    return json_success(
        data=user.to_dict(include_email=True),
        message='Profile updated'
    )


@auth_bp.route('/password', methods=['PUT'])
@jwt_required()
def change_password():
    """Change user password."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    data = request.get_json() or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return json_error('Current and new password required', 400)

    if not user.check_password(current_password):
        return json_error('Current password is incorrect', 401)

    if len(new_password) < 6:
        return json_error('New password must be at least 6 characters', 400)

    user.set_password(new_password)
    db.session.commit()

    return json_success(message='Password changed successfully')
