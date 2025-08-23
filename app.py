from flask import Flask, request, jsonify
import os
import base64
import json
import requests
from pathlib import Path
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

# Load provider data
PROVIDERS_FILE = Path(__file__).parent / 'providers.json'
TEST_PROVIDER_ID = 'test_provider'

def get_provider(provider_id):
    """Look up provider details by ID"""
    try:
        with open(PROVIDERS_FILE, 'r') as f:
            providers = json.load(f)
        return providers.get(provider_id, providers.get(TEST_PROVIDER_ID))
    except Exception as e:
        print(f"Error loading providers: {str(e)}")
        return None

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
    """Handle form submission and send SMS to provider"""
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['customer_phone', 'provider_id', 'service_type', 'address', 'datetime']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"status": "error", "message": f"Missing required field: {field}"}), 400
        
        # Look up provider details
        provider = get_provider(data['provider_id'])
        if not provider:
            return jsonify({"status": "error", "message": "Provider not found"}), 404
        
        # Create new booking
        booking = Booking(
            customer_phone=data['customer_phone'],
            provider_phone=provider['phone'],
            provider_id=data['provider_id'],
            service_type=data['service_type'],
            address=data['address'],
            appointment_time=datetime.fromisoformat(data['datetime']),
            status='pending'
        )
        
        db.session.add(booking)
        db.session.commit()
        
        # Format the appointment time
        try:
            appointment_time = datetime.fromisoformat(data['datetime'].replace('Z', '+00:00'))
            formatted_time = appointment_time.strftime('%m/%d/%Y %-I:%M %p')
        except (ValueError, TypeError) as e:
            print(f"Error formatting datetime {data['datetime']}: {str(e)}")
            formatted_time = data['datetime']  # Fallback to raw string if parsing fails
            
        # Send SMS to provider with the requested format
        message = (
            f"Hey {provider['name']}, new request: {data['service_type']} "
            f"at {data['address']} on {formatted_time}. "
            f"Reply Y to accept or N if you are booked. "
            f"Feel free to contact the client directly at {data['customer_phone']}"
        )
        
        # Log the SMS attempt
        print(f"Sending SMS to provider {provider['name']} ({provider['phone']}): {message}")
        
        success, result = send_sms(provider['phone'], message)
        if not success:
            print(f"Failed to send SMS: {result}")
            # Fallback to test number if available
            test_provider = get_provider(TEST_PROVIDER_ID)
            if test_provider and test_provider['phone'] != provider['phone']:
                print(f"Falling back to test number: {test_provider['phone']}")
                success, result = send_sms(test_provider['phone'], 
                                         f"[TEST] Original recipient failed ({provider['phone']}):\n{message}")
                if not success:
                    return jsonify({"status": "error", "message": f"Failed to send SMS to both provider and test number: {result}"}), 500
            else:
                return jsonify({"status": "error", "message": f"Failed to send SMS to provider: {result}"}), 500
        
        return jsonify({
            "status": "success", 
            "message": "Booking created and notification sent",
            "provider": {"name": provider['name'], "phone": provider['phone']}
        })
        
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"Error in create_booking: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/webhook/sms', methods=['GET', 'POST'])
def sms_webhook():
    """Handle incoming SMS webhooks from TextMagic"""
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
        
        message_data = data.get('message', {}) or data
        
        to_number = message_data.get('receiver', '') or message_data.get('to', '')
        if to_number:
            to_number = ''.join(c for c in to_number if c == '+' or c.isdigit())
        
        # Only process messages sent to our dedicated number
        if to_number and to_number != TEXTMAGIC_FROM_NUMBER.replace('+', ''):
            print(f"Ignoring message not for our dedicated number. To: {to_number}, Expected: {TEXTMAGIC_FROM_NUMBER}")
            return jsonify({"status": "ignored", "message": "Not the dedicated number"}), 200
                
        provider_number = message_data.get('sender', message_data.get('from', ''))
        message_text = message_data.get('text', message_data.get('body', '')).strip().lower()
        
        # Get the provider details
        provider = None
        with open(PROVIDERS_FILE, 'r') as f:
            providers = json.load(f)
            for pid, pdata in providers.items():
                if pdata.get('phone', '').replace('+', '') == provider_number.replace('+', ''):
                    provider = {"id": pid, **pdata}
                    break
        
        if not provider:
            print(f"No provider found with number: {provider_number}")
            # Try to find by any booking with this provider number
            booking = Booking.query.filter_by(
                provider_phone=provider_number,
                status='pending'
            ).order_by(Booking.created_at.desc()).first()
        else:
            # Find the most recent pending booking for this provider ID
            booking = Booking.query.filter_by(
                provider_id=provider['id'],
                status='pending'
            ).order_by(Booking.created_at.desc()).first()
            
            if not booking and provider['id'] != TEST_PROVIDER_ID:
                # Fallback to phone number search if no booking found by ID
                booking = Booking.query.filter_by(
                    provider_phone=provider_number,
                    status='pending'
                ).order_by(Booking.created_at.desc()).first()

        if not booking:
            print(f"No pending booking found for provider: {provider_number}")
            
            # If we couldn't find a booking but have provider info, send a helpful message
            if provider:
                response_msg = (
                    "We couldn't find any pending bookings for you. "
                    "If you're responding to a booking request, please make sure to reply to the original message. "
                    "Otherwise, please contact support."
                )
                send_sms(provider_number, response_msg)
                
            return jsonify({"status": "ignored", "message": "No pending booking found for this provider"}), 200

        # Process the response
        if message_text in ['y', 'yes']:
            try:
                # Update booking status
                booking.status = 'confirmed'
                booking.updated_at = datetime.utcnow()
                db.session.commit()

                # Prepare customer message
                provider_name = provider.get('name', 'the provider') if provider else 'the provider'
                customer_message = (
                    f"Your booking with {provider_name} has been confirmed!\n\n"
                    f"Service: {booking.service_type or 'Not specified'}\n"
                    f"When: {booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'}\n"
                    f"Address: {booking.address or 'Not specified'}\n\n"
                    "Thank you for choosing our service!"
                )
                
                # Send confirmation to customer
                success, msg = send_sms(booking.customer_phone, customer_message)
                if not success:
                    print(f"Failed to send confirmation to customer: {msg}")
                    # Fallback to email or other notification method could be added here

                # Send acknowledgment to provider
                ack_message = (
                    "You've confirmed the booking! The customer has been notified.\n\n"
                    f"Customer: {booking.customer_phone}\n"
                    f"Service: {booking.service_type or 'Not specified'}\n"
                    f"When: {booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'}\n"
                    f"Address: {booking.address or 'Not specified'}"
                )
                
                success, msg = send_sms(provider_number, ack_message)
                if not success:
                    print(f"Failed to send ack to provider: {msg}")

                print(f"Booking {booking.id} confirmed successfully")
                return jsonify({"status": "success", "message": "Booking confirmed"})

            except Exception as e:
                db.session.rollback()
                error_msg = f"Error confirming booking: {str(e)}"
                print(error_msg)
                
                # Notify admin of the error
                try:
                    admin_msg = f"Error confirming booking {booking.id if booking else 'N/A'}: {str(e)}"
                    test_provider = get_provider(TEST_PROVIDER_ID)
                    if test_provider:
                        send_sms(test_provider['phone'], admin_msg)
                except Exception as admin_err:
                    print(f"Failed to notify admin: {str(admin_err)}")
                    
                return jsonify({"status": "error", "message": "Failed to confirm booking"}), 500

        elif message_text in ['n', 'no']:
            try:
                # Update booking status
                booking.status = 'rejected'
                booking.updated_at = datetime.utcnow()
                db.session.commit()

                # Send alternative message to customer
                alt_message = (
                    "Hi, we're sorry for the inconvenience, but the provider you selected is not available. "
                    "You can book with another provider here: goldtouchmobile.com/providers.\n\n"
                    "We apologize for any inconvenience and hope to serve you soon!"
                )
                success, msg = send_sms(booking.customer_phone, alt_message)
                if not success:
                    print(f"Failed to send rejection to customer: {msg}")
                    # Log this for follow-up

                # Send acknowledgment to provider
                ack_message = (
                    "You've declined the booking. The customer has been notified and will look for another provider.\n\n"
                    "Thank you for your prompt response!"
                )
                success, msg = send_sms(provider_number, ack_message)
                if not success:
                    print(f"Failed to send ack to provider: {msg}")

                print(f"Booking {booking.id} rejected successfully")
                return jsonify({"status": "success", "message": "Booking rejected"})

            except Exception as e:
                db.session.rollback()
                print(f"Error rejecting booking: {str(e)}")
                return jsonify({"status": "error", "message": "Failed to reject booking"}), 500

        else:
            # Not a valid response, ask for Y/N
            response_message = (
                "We didn't understand your response. "
                "Please reply with:\n"
                "- 'Y' to CONFIRM the booking\n"
                "- 'N' to DECLINE the booking\n\n"
                "Thank you!"
            )
            success, msg = send_sms(provider_number, response_message)
            if not success:
                print(f"Failed to send instructions: {msg}")
            
            print(f"Received invalid response from {provider_number}: {message_text}")
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
