from flask import Flask, request, jsonify
import os
import base64
import requests
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

# TextMagic API endpoint
TEXTMAGIC_API_URL = 'https://rest.textmagic.com/api/v2/messages'

def send_sms(to_number, message):
    """Send SMS using TextMagic API"""
    try:
        # Format number (remove any non-digit characters except +)
        to_number = ''.join(c for c in to_number if c == '+' or c.isdigit())
        
        # Create Basic Auth header
        auth_string = f"{TEXTMAGIC_USERNAME}:{TEXTMAGIC_API_KEY}"
        auth_token = base64.b64encode(auth_string.encode()).decode('utf-8')
        
        headers = {
            'Content-Type': 'application/json',
            'X-TM-Username': TEXTMAGIC_USERNAME,
            'X-TM-Key': TEXTMAGIC_API_KEY
        }
        
        payload = {
            'text': message,
            'phones': to_number,
            'from': TEXTMAGIC_FROM_NUMBER
        }
        
        response = requests.post(
            TEXTMAGIC_API_URL,
            json=payload,
            headers=headers
        )
        
        if response.status_code == 201:
            return True, f"SMS sent with ID: {response.json().get('id')}"
        else:
            return False, f"TextMagic API error: {response.text}"
    except Exception as e:
        return False, f"Error sending SMS: {str(e)}"

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

@app.route('/webhook/sms', methods=['GET', 'POST'])
def sms_webhook():
    """Handle incoming SMS webhook from TextMagic"""
    # Handle webhook validation (GET request)
    if request.method == 'GET':
        return jsonify({"status": "ok"}), 200
        
    # Handle incoming message (POST request)
    try:
        # Get JSON data from request
        if not request.is_json:
            return jsonify({"status": "error", "message": "Invalid content type"}), 400
            
        data = request.get_json()
        print(f"Received webhook data: {data}")
        
        # TextMagic webhook format can vary, try to extract message data
        message_data = data.get('message', {}) or data
        
        # Get the number this message was sent to
        to_number = message_data.get('receiver', '')
        if not to_number and 'to' in message_data:
            to_number = message_data['to']
        
        # Format to_number by removing any non-digit characters except +
        if to_number:
            to_number = ''.join(c for c in to_number if c == '+' or c.isdigit())
        
        # Only process messages sent to our dedicated number
        if to_number and to_number != TEXTMAGIC_FROM_NUMBER.replace('+', ''):
            print(f"Ignoring message not for our dedicated number. To: {to_number}, Expected: {TEXTMAGIC_FROM_NUMBER}")
            return jsonify({"status": "ignored", "message": "Not the dedicated number"}), 200
                
        provider_number = message_data.get('sender', message_data.get('from', ''))
        message_text = message_data.get('text', message_data.get('body', '')).strip().lower()
            
        # Find the most recent pending booking for this provider
        booking = Booking.query.filter_by(
            provider_phone=provider_number,
            status='pending'
        ).order_by(Booking.created_at.desc()).first()

        if not booking:
            print(f"No pending booking found for provider: {provider_number}")
            return jsonify({"status": "ignored", "message": "No pending booking found for this provider"}), 200

        # Process the response
        if message_text in ['y', 'yes']:
            try:
                # Update booking status
                booking.status = 'confirmed'
                booking.updated_at = datetime.utcnow()
                db.session.commit()

                # Send confirmation to customer
                customer_message = "You are confirmed with the provider"
                success, msg = send_sms(booking.customer_phone, customer_message)
                if not success:
                    print(f"Failed to send confirmation to customer: {msg}")

                # Send acknowledgment to provider
                ack_message = "You've confirmed the booking. The customer has been notified."
                success, msg = send_sms(provider_number, ack_message)
                if not success:
                    print(f"Failed to send ack to provider: {msg}")

                print(f"Booking {booking.id} confirmed successfully")
                return jsonify({"status": "success", "message": "Booking confirmed"})

            except Exception as e:
                db.session.rollback()
                print(f"Error confirming booking: {str(e)}")
                return jsonify({"status": "error", "message": "Failed to confirm booking"}), 500

        elif message_text in ['n', 'no']:
            try:
                # Update booking status
                booking.status = 'rejected'
                booking.updated_at = datetime.utcnow()
                db.session.commit()

                # Send alternative message to customer
                alt_message = (
                    "Hi, we are sorry for the inconvenience, but the provider you selected is not available. "
                    "You can book with another provider here: goldtouchmobile.com/providers. Thanks!"
                )
                success, msg = send_sms(booking.customer_phone, alt_message)
                if not success:
                    print(f"Failed to send rejection to customer: {msg}")

                print(f"Booking {booking.id} rejected successfully")
                return jsonify({"status": "success", "message": "Booking rejected"})

            except Exception as e:
                db.session.rollback()
                print(f"Error rejecting booking: {str(e)}")
                return jsonify({"status": "error", "message": "Failed to reject booking"}), 500

        else:
            # Not a valid response, ask for Y/N
            response_message = (
                "Please reply with 'Y' to confirm the booking or 'N' if you're not available. "
                "Thank you!"
            )
            success, msg = send_sms(provider_number, response_message)
            if not success:
                print(f"Failed to send instructions: {msg}")
            
            print(f"Received invalid response: {message_text}")
            return jsonify({"status": "ignored", "message": "Invalid response, sent instructions"})

    except Exception as e:
        import traceback
        print(f"Error processing webhook: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'false').lower() == 'true')
