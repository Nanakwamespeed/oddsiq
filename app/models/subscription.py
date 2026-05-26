"""Subscription model for premium plans."""
from datetime import datetime
from ..extensions import db


class Subscription(db.Model):
    """Subscription model."""

    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    plan = db.Column(db.Enum('monthly', 'annual', name='subscription_plan'), nullable=False)
    paystack_ref = db.Column(db.String(100), unique=True, nullable=True, index=True)
    amount = db.Column(db.Integer, nullable=True)  # Amount in pesewas
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        """Serialize subscription to dictionary."""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'plan': self.plan,
            'amount': self.amount,
            'amount_ghs': round(self.amount / 100, 2) if self.amount else None,
            'starts_at': self.starts_at.isoformat(),
            'ends_at': self.ends_at.isoformat(),
            'is_active': self.is_active(),
            'created_at': self.created_at.isoformat()
        }

    def is_active(self):
        """Check if subscription is currently active."""
        now = datetime.utcnow()
        return self.starts_at <= now <= self.ends_at

    def __repr__(self):
        return f'<Subscription user_id={self.user_id} plan={self.plan}>'
