from flask import Flask, request, jsonify
import os
import textmagic.rest
from textmagic.rest import TextmagicRestClient
from dotenv import load_dotenv
from models import db, Booking
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///bookings.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Create tables
with app.app_context():
    db.create_all()

# TextMagic API credentials
TEXTMAGIC_USERNAME = os.getenv('TEXTMAGIC_USERNAME')
TEXTMAGIC_API_KEY = os.getenv('TEXTMAGIC_API_KEY')
TEXTMAGIC_FROM_NUMBER = os.getenv('TEXTMAGIC_FROM_NUMBER')

# Initialize TextMagic client
try:
    textmagic_client = TextmagicRestClient(TEXTMAGIC_USERNAME, TEXTMAGIC_API_KEY)
except Exception as e:
    print(f"Error initializing TextMagic client: {str(e)}")
    textmagic_client = None

def send_sms(to_number, message):
    """Send SMS using TextMagic API"""
    if not textmagic_client:
        return False, "TextMagic client not initialized"
    
    try:
        # Format number (remove any non-digit characters except +)
        to_number = ''.join(c for c in to_number if c == '+' or c.isdigit())
        
        # Send message
        result = textmagic_client.messages.create(
            phones=to_number,
            text=message,
            sending_phone_number=TEXTMAGIC_FROM_NUMBER
        )
        return True, f"SMS sent with ID: {result.id}"
    except Exception as e:
        return False, f"TextMagic API error: {str(e)}"

@app.route('/api/booking', methods=['POST'])
def create_booking():
    """Endpoint to receive form submissions and notify provider"""
    try:
        data = request.json
        customer_phone = data.get('customer_phone')
        provider_phone = data.get('provider_phone')
        service_type = data.get('service_type', 'service')
        address = data.get('address', 'the address')
        datetime_str = data.get('datetime', 'scheduled time')
        
        if not customer_phone or not provider_phone:
            return jsonify({"status": "error", "message": "Missing customer_phone or provider_phone"}), 400
        
        # Create new booking
        booking = Booking(
            customer_phone=customer_phone,
            provider_phone=provider_phone,
            status='pending'
        )
        
        db.session.add(booking)
        db.session.commit()
        
        # Send the detailed message to the provider
        provider_message = (
            f"Hey Dan, new request: {service_type} at {address} on {datetime_str}. "
            f"Reply Y to accept or N if you are booked. Feel free to contact the client directly at {customer_phone}"
        )
        
        success, message = send_sms(provider_phone, provider_message)
        if not success:
            return jsonify({"status": "error", "message": f"Failed to send SMS: {message}"}), 500
        
        return jsonify({
            "status": "success",
            "booking_id": booking.id,
            "message": "Provider notified successfully"
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook/sms', methods=['POST'])
def sms_webhook():
    """Handle incoming SMS webhook from TextMagic"""
    try:
        data = request.json
        
        # Extract relevant data from TextMagic webhook
        if 'message' in data:
            message_data = data['message']
            
            # Get the number this message was sent to
            to_number = message_data.get('receiver', '')
            
            # Only process messages sent to our dedicated number
            if to_number != TEXTMAGIC_FROM_NUMBER.replace('+', ''):
                return jsonify({"status": "ignored", "message": "Not the dedicated number"}), 200
                
            provider_number = message_data.get('sender', '')
            message_text = message_data.get('text', '').strip().lower()
            
            # Find the most recent pending booking for this provider
            booking = Booking.query.filter_by(
                provider_phone=provider_number,
                status='pending'
            ).order_by(Booking.created_at.desc()).first()
            
            if not booking:
                return jsonify({"status": "error", "message": "No pending booking found for this provider"}), 404
            
            # Clean the response (remove whitespace, convert to uppercase for comparison)
            response = message_text.strip().upper()
            
            # Check if message is a response to confirmation (case-insensitive 'Y' or 'N')
            if response in ['Y', 'y']:
                booking.status = 'confirmed'
                db.session.commit()
                # Send confirmation message to customer
                send_sms(
                    booking.customer_phone, 
                    "Your booking has been confirmed with the provider!"
                )
                # Acknowledge to provider
                send_sms(
                    provider_number,
                    "Thank you for confirming the booking. The customer has been notified."
                )
                
            elif response in ['N', 'n']:
                booking.status = 'rejected'
                db.session.commit()
                # Send alternative provider message to customer
                message = (
                    "Hi, we are sorry for the inconvenience, but the provider you selected is not available. "
                    "You can book with another provider here: goldtouchmobile.com/providers. Thanks!"
                )
                send_sms(booking.customer_phone, message)
                # Acknowledge to provider
                send_sms(
                    provider_number,
                    "Thank you for your response. The customer has been notified to find another provider."
                )
            
            return jsonify({"status": "success"}), 200
        
        return jsonify({"status": "error", "message": "Invalid webhook data"}), 400
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'false').lower() == 'true')
