"""User model with password hashing."""
from datetime import datetime
import bcrypt
from ..extensions import db


class User(db.Model):
    """User model."""

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    other_names = db.Column(db.String(100), nullable=True)
    role = db.Column(db.Enum('free', 'premium', 'admin', name='user_role'), default='free', nullable=False)
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def full_name(self):
        parts = [self.first_name, self.other_names, self.last_name]
        return ' '.join(p for p in parts if p) or None

    # Relationships
    refresh_tokens = db.relationship('RefreshToken', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        """Hash and set the user's password."""
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')

    def check_password(self, password):
        """Check if the provided password matches the hash."""
        password_bytes = password.encode('utf-8')
        hash_bytes = self.password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)

    def is_premium(self):
        """Check if user has active premium subscription."""
        if self.role == 'admin':
            return True
        if self.role == 'premium':
            # If no expiry set, assume lifetime premium
            if not self.subscription_expires_at:
                return True
            return self.subscription_expires_at > datetime.utcnow()
        return False

    def is_admin(self):
        """Check if user is an admin."""
        return self.role == 'admin'

    def to_dict(self, include_email=False):
        """Serialize user to dictionary."""
        data = {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'other_names': self.other_names,
            'full_name': self.full_name,
            'role': self.role,
            'is_premium': self.is_premium(),
            'subscription_expires_at': self.subscription_expires_at.isoformat() if self.subscription_expires_at else None,
            'created_at': self.created_at.isoformat()
        }
        if include_email:
            data['email'] = self.email
        return data

    def __repr__(self):
        return f'<User {self.email}>'
