"""Payment routes with Paystack integration."""
import hmac
import hashlib
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import db
from ..models.user import User
from ..models.subscription import Subscription
from ..services.paystack_service import PaystackService
from ..utils.helpers import json_error, json_success

logger = logging.getLogger(__name__)
payments_bp = Blueprint('payments', __name__)


@payments_bp.route('/plans', methods=['GET'])
def get_plans():
    """Get available subscription plans."""
    monthly_amount = current_app.config['MONTHLY_PLAN_AMOUNT']
    annual_amount = current_app.config['ANNUAL_PLAN_AMOUNT']

    return json_success(data={
        'plans': [
            {
                'id': 'monthly',
                'name': 'Monthly',
                'amount': monthly_amount / 100,
                'currency': 'GHS',
                'interval': 'month',
                'features': [
                    'Unlimited predictions',
                    'Value bet alerts',
                    'Expert analysis',
                    'Priority support'
                ]
            },
            {
                'id': 'annual',
                'name': 'Annual',
                'amount': annual_amount / 100,
                'currency': 'GHS',
                'interval': 'year',
                'features': [
                    'Unlimited predictions',
                    'Value bet alerts',
                    'Expert analysis',
                    'Priority support',
                    '2 months free'
                ]
            }
        ]
    })


@payments_bp.route('/initiate', methods=['POST'])
@jwt_required()
def initiate_payment():
    """Initiate a Paystack payment session."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    data = request.get_json() or {}
    plan = data.get('plan', 'monthly')

    if plan not in ['monthly', 'annual']:
        return json_error('Invalid plan. Choose monthly or annual.', 400)

    amount = current_app.config['MONTHLY_PLAN_AMOUNT'] if plan == 'monthly' else current_app.config['ANNUAL_PLAN_AMOUNT']

    paystack = PaystackService()
    result = paystack.initialize_transaction(
        email=user.email,
        amount=amount,
        metadata={
            'user_id': user.id,
            'plan': plan
        }
    )

    if not result['success']:
        return json_error(result.get('message', 'Payment initialization failed'), 500)

    return json_success(data={
        'authorization_url': result['authorization_url'],
        'access_code': result['access_code'],
        'reference': result['reference'],
        'plan': plan,
        'amount': amount / 100
    })


@payments_bp.route('/verify/<reference>', methods=['GET'])
@jwt_required()
def verify_payment(reference):
    """Verify a Paystack payment and upgrade user to premium."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    paystack = PaystackService()
    result = paystack.verify_transaction(reference)

    if not result['success']:
        return json_error(result.get('message', 'Payment verification failed'), 400)

    # Check if already processed (webhook may have beaten us here)
    existing_sub = Subscription.query.filter_by(paystack_ref=reference).first()
    if existing_sub:
        return json_success(
            data={
                'subscription': existing_sub.to_dict(),
                'user': user.to_dict(include_email=True)
            },
            message='Payment already processed. Welcome to premium!'
        )

    metadata = result.get('metadata', {})
    plan = metadata.get('plan', 'monthly')
    amount = result.get('amount', 0)  # pesewas

    now = datetime.utcnow()
    ends_at = now + timedelta(days=30 if plan == 'monthly' else 365)

    subscription = Subscription(
        user_id=user.id,
        plan=plan,
        paystack_ref=reference,
        amount=amount,
        starts_at=now,
        ends_at=ends_at
    )
    db.session.add(subscription)

    user.role = 'premium'
    user.subscription_expires_at = ends_at
    db.session.commit()

    return json_success(
        data={
            'subscription': subscription.to_dict(),
            'user': user.to_dict(include_email=True)
        },
        message='Payment successful! You are now a premium member.'
    )


@payments_bp.route('/webhook', methods=['POST'])
def paystack_webhook():
    """Paystack webhook for charge.success events."""
    secret_key = current_app.config.get('PAYSTACK_SECRET_KEY', '')

    # Verify HMAC-SHA512 signature
    signature = request.headers.get('x-paystack-signature', '')
    body = request.get_data()

    if secret_key:
        computed = hmac.new(
            secret_key.encode('utf-8'),
            body,
            hashlib.sha512
        ).hexdigest()

        if not hmac.compare_digest(computed, signature):
            logger.warning('Paystack webhook: invalid signature')
            return json_error('Invalid signature', 400)

    data = request.get_json(silent=True) or {}
    event = data.get('event')

    if event == 'charge.success':
        payload = data.get('data', {})
        reference = payload.get('reference')
        amount = payload.get('amount', 0)
        metadata = payload.get('metadata', {})
        user_id = metadata.get('user_id')
        plan = metadata.get('plan', 'monthly')

        if not user_id or not reference:
            return '', 200

        # Idempotency guard
        if Subscription.query.filter_by(paystack_ref=reference).first():
            return '', 200

        user = User.query.get(user_id)
        if not user:
            logger.error(f'Webhook: user {user_id} not found for ref {reference}')
            return '', 200

        now = datetime.utcnow()
        ends_at = now + timedelta(days=30 if plan == 'monthly' else 365)

        subscription = Subscription(
            user_id=user.id,
            plan=plan,
            paystack_ref=reference,
            amount=amount,
            starts_at=now,
            ends_at=ends_at
        )
        db.session.add(subscription)

        user.role = 'premium'
        user.subscription_expires_at = ends_at
        db.session.commit()

        logger.info(f'Webhook: upgraded user {user_id} to premium via {reference}')

    return '', 200


@payments_bp.route('/history', methods=['GET'])
@jwt_required()
def payment_history():
    """Get user's payment/subscription history."""
    user_id = get_jwt_identity()

    subscriptions = Subscription.query.filter_by(user_id=user_id).order_by(
        Subscription.created_at.desc()
    ).all()

    return json_success(data={
        'payments': [sub.to_dict() for sub in subscriptions]
    })


@payments_bp.route('/cancel', methods=['POST'])
@jwt_required()
def cancel_subscription():
    """Downgrade user to free (no refund — access remains until expires_at)."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return json_error('User not found', 404)

    if user.role != 'premium':
        return json_error('No active premium subscription', 400)

    user.role = 'free'
    user.subscription_expires_at = None
    db.session.commit()

    return json_success(
        data={'user': user.to_dict(include_email=True)},
        message='Subscription cancelled'
    )
