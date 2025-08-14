from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Booking(db.Model):
    """Stores the relationship between customer and provider"""
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_phone = db.Column(db.String(20), nullable=False)
    provider_phone = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_phone': self.customer_phone,
            'provider_phone': self.provider_phone,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
