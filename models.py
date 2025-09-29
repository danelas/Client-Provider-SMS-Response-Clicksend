from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Provider(db.Model):
    """Stores provider information in the database"""
    __tablename__ = 'providers'
    
    id = db.Column(db.String(50), primary_key=True)  # provider_id like 'provider1', 'provider2'
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Provider {self.id}: {self.name} ({self.phone})>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Booking(db.Model):
    """Stores the relationship between customer and provider"""
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_phone = db.Column(db.String(20), nullable=False)
    customer_name = db.Column(db.String(100), nullable=True)  # Add customer name field
    provider_phone = db.Column(db.String(20), nullable=False, index=True)
    provider_id = db.Column(db.String(50), nullable=True)  # Store the provider ID (e.g., 'prov_amy')
    service_type = db.Column(db.String(100), nullable=True)
    add_ons = db.Column(db.Text, nullable=True)  # Optional add-ons field
    address = db.Column(db.Text, nullable=True)
    appointment_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, rejected, expired
    response_deadline = db.Column(db.DateTime, nullable=True)  # When the provider must respond by
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Booking {self.id}: {self.customer_phone} -> {self.provider_phone} ({self.status})>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_phone': self.customer_phone,
            'provider_phone': self.provider_phone,
            'provider_id': self.provider_id,
            'service_type': self.service_type,
            'add_ons': self.add_ons,
            'address': self.address,
            'appointment_time': self.appointment_time.isoformat() if self.appointment_time else None,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class MessageLog(db.Model):
    """Tracks messages sent to phone numbers to prevent spam"""
    __tablename__ = 'message_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False, index=True)
    message_type = db.Column(db.String(50), nullable=False)  # 'basic_redirect', 'ai_response', etc.
    message_content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<MessageLog {self.id}: {self.phone_number} - {self.message_type}>"
