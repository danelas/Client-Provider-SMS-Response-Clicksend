from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Provider(db.Model):
    """Stores provider information in the database"""
    __tablename__ = 'providers'
    
    id = db.Column(db.String(50), primary_key=True)  # provider_id like 'provider1', 'provider2'
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    stripe_account_id = db.Column(db.String(100))
    is_verified = db.Column(db.Boolean, default=False)
    sms_opted_out = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Provider {self.id}: {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'stripe_account_id': self.stripe_account_id,
            'is_verified': self.is_verified,
            'sms_opted_out': self.sms_opted_out,
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
    
    # New fields from form field definitions
    city_zip = db.Column(db.String(100), nullable=True)  # City or ZIP code
    session_length = db.Column(db.String(50), nullable=True)  # Session Length Preference
    location_type = db.Column(db.String(50), nullable=True)  # Location Type (Mobile/In-Studio)
    contact_preference = db.Column(db.String(50), nullable=True)  # How would you like to be contacted?
    
    status = db.Column(db.String(30), default='pending')  # pending, confirmed, rejected, expired, cancellation_requested
    provider_responded = db.Column(db.Boolean, default=False)  # Track if provider has responded (any message)
    response_deadline = db.Column(db.DateTime, nullable=True)  # When the provider must respond by
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<Booking {self.id}: {self.customer_phone} -> {self.provider_phone} ({self.status})>"
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_phone': self.customer_phone,
            'customer_name': self.customer_name,
            'provider_phone': self.provider_phone,
            'provider_id': self.provider_id,
            'service_type': self.service_type,
            'add_ons': self.add_ons,
            'address': self.address,
            'appointment_time': self.appointment_time.isoformat() if self.appointment_time else None,
            'city_zip': self.city_zip,
            'session_length': self.session_length,
            'location_type': self.location_type,
            'contact_preference': self.contact_preference,
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


class Lead(db.Model):
    """Stores lead information for the lead unlock system"""
    __tablename__ = 'leads'
    
    id = db.Column(db.String(50), primary_key=True)  # lead_id like 'lead_12345'
    city = db.Column(db.String(100), nullable=False)
    service_type = db.Column(db.String(100), nullable=False)
    preferred_time_window = db.Column(db.String(100), nullable=True)
    budget_range = db.Column(db.String(50), nullable=True)
    notes_snippet = db.Column(db.Text, nullable=True)
    
    # Locked client information (only revealed after payment)
    client_name = db.Column(db.String(100), nullable=False)
    client_phone = db.Column(db.String(20), nullable=False)
    client_email = db.Column(db.String(100), nullable=True)
    exact_address = db.Column(db.Text, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Lead {self.id}: {self.service_type} in {self.city}>'
    
    def to_dict(self, include_locked=False):
        """Convert to dictionary, optionally including locked client data"""
        data = {
            'id': self.id,
            'city': self.city,
            'service_type': self.service_type,
            'preferred_time_window': self.preferred_time_window,
            'budget_range': self.budget_range,
            'notes_snippet': self.notes_snippet,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
        
        if include_locked:
            data.update({
                'client_name': self.client_name,
                'client_phone': self.client_phone,
                'client_email': self.client_email,
                'exact_address': self.exact_address
            })
        else:
            # Redacted versions for teasers
            data.update({
                'client_name': '***LOCKED***',
                'client_phone': '***LOCKED***',
                'client_email': '***LOCKED***',
                'exact_address': '***LOCKED***'
            })
        
        return data


class LeadUnlock(db.Model):
    """Tracks the state machine for lead unlock payments per provider"""
    __tablename__ = 'lead_unlocks'
    
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.String(50), db.ForeignKey('leads.id'), nullable=False)
    provider_id = db.Column(db.String(50), db.ForeignKey('providers.id'), nullable=False)
    
    # State machine fields
    status = db.Column(db.String(30), default='NEW_LEAD')  # NEW_LEAD, TEASER_SENT, AWAIT_CONFIRM, PAYMENT_LINK_SENT, AWAITING_PAYMENT, PAID, DONE, EXPIRED, OPTED_OUT
    last_sent_at = db.Column(db.DateTime, nullable=True)
    payment_link_url = db.Column(db.Text, nullable=True)
    checkout_session_id = db.Column(db.String(100), nullable=True)
    unlocked_at = db.Column(db.DateTime, nullable=True)
    idempotency_key = db.Column(db.String(100), nullable=True)
    ttl_expires_at = db.Column(db.DateTime, nullable=True)
    
    # Config fields
    price_cents = db.Column(db.Integer, default=2000)  # $20.00
    currency = db.Column(db.String(3), default='usd')
    ttl_hours = db.Column(db.Integer, default=24)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    lead = db.relationship('Lead', backref='unlocks')
    provider = db.relationship('Provider', backref='lead_unlocks')
    
    # Unique constraint to prevent duplicate unlock attempts
    __table_args__ = (db.UniqueConstraint('lead_id', 'provider_id', name='unique_lead_provider'),)
    
    def __repr__(self):
        return f'<LeadUnlock {self.id}: {self.lead_id} -> {self.provider_id} ({self.status})>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'provider_id': self.provider_id,
            'status': self.status,
            'last_sent_at': self.last_sent_at.isoformat() if self.last_sent_at else None,
            'payment_link_url': self.payment_link_url,
            'checkout_session_id': self.checkout_session_id,
            'unlocked_at': self.unlocked_at.isoformat() if self.unlocked_at else None,
            'idempotency_key': self.idempotency_key,
            'ttl_expires_at': self.ttl_expires_at.isoformat() if self.ttl_expires_at else None,
            'price_cents': self.price_cents,
            'currency': self.currency,
            'ttl_hours': self.ttl_hours,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
