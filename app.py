from flask import Flask, request, jsonify
import os
import base64
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from models import db, Booking
from datetime import datetime, timedelta
import pytz

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
        if not provider_id:
            print("Error: No provider ID provided")
            return None
            
        with open(PROVIDERS_FILE, 'r') as f:
            providers = json.load(f)
            
        # First try to get the exact provider
        provider = providers.get(provider_id)
        
        if not provider:
            print(f"Error: Provider with ID '{provider_id}' not found in providers.json")
            # List available provider IDs for debugging
            available_ids = list(providers.keys())
            print(f"Available provider IDs: {available_ids}")
            return None
            
        return provider
        
    except Exception as e:
        print(f"Error loading providers: {str(e)}")
        return None

def send_sms(to_number, message, from_number=None):
    """Send SMS using TextMagic API"""
    try:
        # Format number (remove any non-digit characters except +)
        to_number = ''.join(c for c in to_number if c == '+' or c.isdigit())
        
        # Use provided from_number or fall back to environment variable
        sender_id = from_number or TEXTMAGIC_FROM_NUMBER
        
        # For TextMagic, if using a dedicated number, it should be in the international format
        # without the + sign for the 'from' parameter
        if sender_id and sender_id.startswith('+'):
            sender_id = sender_id[1:]
        
        headers = {
            'Content-Type': 'application/json',
            'X-TM-Username': TEXTMAGIC_USERNAME,
            'X-TM-Key': TEXTMAGIC_API_KEY
        }
        
        payload = {
            'text': message,
            'phones': to_number,
        }
        
        # Only add 'from' if we have a sender_id
        if sender_id:
            payload['from'] = sender_id
        
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
        print("\n=== NEW BOOKING REQUEST ===")
        print(f"Time: {datetime.now().isoformat()}")
        print(f"Request method: {request.method}")
        print(f"Request headers: {dict(request.headers)}")
        print(f"Request content type: {request.content_type}")
        print(f"Request data length: {len(request.data) if request.data else 0} bytes")
        
        # Log raw request data safely
        try:
            raw_data = request.get_data(as_text=True)
            print(f"Raw request data (first 1000 chars): {raw_data[:1000]}")
        except Exception as e:
            print(f"Error reading raw request data: {str(e)}")
        
        # Log environment variables for debugging
        print("\n=== ENVIRONMENT VARIABLES ===")
        print(f"TEXTMAGIC_USERNAME: {'Set' if os.getenv('TEXTMAGIC_USERNAME') else 'Not set'}")
        print(f"TEXTMAGIC_API_KEY: {'Set (first 4 chars shown)' + os.getenv('TEXTMAGIC_API_KEY', '')[:4] + '...' if os.getenv('TEXTMAGIC_API_KEY') else 'Not set'}")
        print(f"TEXTMAGIC_FROM_NUMBER: {os.getenv('TEXTMAGIC_FROM_NUMBER', 'Not set')}")
        print(f"DATABASE_URL: {os.getenv('DATABASE_URL', 'sqlite:///bookings.db')}")
        print("===========================\n")
        
        # Check content type and parse data
        content_type = request.headers.get('Content-Type', '').lower()
        
        # Debug: Log the raw request data
        raw_data = request.get_data(as_text=True)
        print(f"Raw request data: {raw_data}")
        
        try:
            if 'application/json' in content_type:
                if not raw_data.strip():
                    raise ValueError("Empty JSON payload")
                data = request.get_json(force=True)  # Force parsing even if content-type is wrong
            elif 'application/x-www-form-urlencoded' in content_type:
                data = request.form.to_dict()
                print(f"Form data: {data}")
                # Try to parse any JSON in the form data
                for key in data:
                    try:
                        if isinstance(data[key], str) and (data[key].startswith('{') or data[key].startswith('[')):
                            data[key] = json.loads(data[key])
                    except (json.JSONDecodeError, TypeError):
                        pass
            else:
                # Try to auto-detect the content type
                try:
                    data = request.get_json(force=True)
                    print("Auto-detected JSON data")
                except:
                    data = request.form.to_dict()
                    print("Fell back to form data")
                    
            print(f"Parsed request data: {data}")
            
            if not data:
                raise ValueError("No data found in request")
                
        except Exception as e:
            error_msg = f"Error parsing request data: {str(e)}"
            print(f"ERROR: {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400
        
        # Log all received fields
        print("\n=== RECEIVED DATA ===")
        for key, value in data.items():
            print(f"{key}: {value} (type: {type(value)})")
        print("===================\n")
        
        # Check database connection
        try:
            with app.app_context():
                from sqlalchemy import text
                db.session.execute(text('SELECT 1'))
                print("Database connection successful")
        except Exception as e:
            error_msg = f"Database connection error: {str(e)}"
            print(f"DATABASE ERROR: {error_msg}")
            return jsonify({"status": "error", "message": "Database connection error"}), 500
        
        # Validate required fields
        required_fields = ['customer_phone', 'provider_id', 'service_type', 'datetime']
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            print(f"VALIDATION ERROR: {error_msg}")
            return jsonify({"status": "error", "message": error_msg, "missing_fields": missing_fields}), 400
        
        # Clean and validate phone number
        phone = ''.join(c for c in str(data['customer_phone']) if c.isdigit() or c == '+')
        if not phone:
            error_msg = "Invalid phone number format"
            print(f"VALIDATION ERROR: {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400
            
        # Normalize service type (replace middle dots with dashes)
        if 'service_type' in data:
            data['service_type'] = data['service_type'].replace('·', '-').replace('•', '-').strip()
            print(f"Normalized service_type: {data['service_type']}")
        
        # Set default empty address if not provided
        if 'address' not in data or not data['address']:
            data['address'] = 'Address not provided'
        
        # Look up provider details with detailed logging
        print(f"\n=== LOOKING UP PROVIDER ===")
        print(f"Provider ID: {data['provider_id']}")
        provider = get_provider(data['provider_id'])
        
        if not provider:
            error_msg = f"Provider with ID '{data['provider_id']}' not found"
            print(f"PROVIDER ERROR: {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 404
            
        print(f"Found provider: {provider}")
        print("==========================\n")
        
        # Parse the datetime string
        try:
            # Try parsing with AM/PM format first
            try:
                appointment_dt = datetime.strptime(data['datetime'], '%m/%d/%Y %I:%M %p')
            except ValueError:
                # Fall back to ISO format if AM/PM format fails
                appointment_dt = datetime.fromisoformat(data['datetime'])
                
            # Calculate response deadline (15 minutes from now)
            response_deadline = datetime.utcnow() + timedelta(minutes=15)
            
            # Extract customer name from form data (handling both direct and nested formats)
            customer_name = ''
            if 'name' in data:
                customer_name = data['name']
            elif 'names' in data and isinstance(data['names'], dict) and 'First Name' in data['names']:
                customer_name = data['names']['First Name']
                
            # Create a new booking
            booking = Booking(
                customer_phone=data['customer_phone'],
                customer_name=customer_name,  # Store the customer name
                provider_phone=provider['phone'],  # Add provider's phone number
                provider_id=data['provider_id'],
                service_type=data['service_type'],
                address=data.get('address', ''),
                appointment_time=appointment_dt,
                status='pending',
                response_deadline=response_deadline
            )
            
            db.session.add(booking)
            db.session.commit()
            
            # Format the appointment time for the message
            try:
                # First try to parse the date if it's a string
                if isinstance(data['datetime'], str):
                    try:
                        # Try parsing as MM/DD/YYYY hh:mm AM/PM
                        dt = datetime.strptime(data['datetime'], '%m/%d/%Y %I:%M %p')
                    except ValueError:
                        # Fall back to ISO format
                        dt = datetime.fromisoformat(data['datetime'].replace('Z', '+00:00'))
                else:
                    dt = data['datetime']
                    
                formatted_time = dt.strftime('%m/%d/%Y %-I:%M %p')
            except Exception as e:
                print(f"Error formatting datetime {data['datetime']}: {str(e)}")
                formatted_time = str(data['datetime'])  # Fallback to string representation
                
            # Format deadline in provider's local time (ET timezone)
            et = pytz.timezone('US/Eastern')
            deadline_et = response_deadline.astimezone(et)
            deadline_str = deadline_et.strftime('%-I:%M %p ET')
            
            # Send SMS to provider with the requested format and deadline (without customer phone number)
            message = (
                f"Hey {provider['name']}, new request: {data['service_type']} "
                f"at {data['address']} on {formatted_time}. "
                f"\n\nPlease reply with:\n"
                f"Y to ACCEPT or N to DECLINE\n"
                f"\nYou have until {deadline_str} to respond."
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
            
        except (ValueError, TypeError) as e:
            db.session.rollback()
            return jsonify({"status": "error", "message": f"Invalid datetime format. Use MM/DD/YYYY hh:mm AM/PM format. Error: {str(e)}"}), 400
        
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

@app.route('/webhook/sms', methods=['GET', 'POST', 'PUT'])
def sms_webhook():
    """Handle incoming SMS webhooks from TextMagic"""
    # Handle webhook validation (GET request)
    if request.method == 'GET':
        print("Webhook validation request received")
        return jsonify({"status": "ok"}), 200
        
    # Log all incoming requests for debugging
    print(f"\n=== INCOMING WEBHOOK REQUEST ===")
    print(f"Method: {request.method}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Content-Type: {request.content_type}")
    print(f"Raw data: {request.get_data()}")
    
    # Ensure proper content type
    if not request.is_json and request.content_type != 'application/x-www-form-urlencoded':
        error_msg = "Unsupported Media Type: Content-Type must be application/json or application/x-www-form-urlencoded"
        print(f"ERROR: {error_msg}")
        return jsonify({"status": "error", "message": error_msg}), 400
        
    # Parse the request data
    data = {}
    if request.is_json:
        data = request.get_json() or {}
    else:
        # Handle form data
        data = request.form.to_dict()
        
    print(f"Parsed webhook data: {data}")
    
    # Validate required fields
    if not data:
        error_msg = "No data received in webhook"
        print(f"ERROR: {error_msg}")
        return jsonify({"status": "error", "message": error_msg}), 400
    
    try:
        # Process the incoming message
        message_data = data.get('message', {}) or data
        print(f"Processing message: {message_data}")
        
        # Extract the SMS content and sender
        text = message_data.get('text', '').strip().lower()
        from_number = message_data.get('from', '')
        
        if not text or not from_number:
            error_msg = "Missing required fields in webhook data"
            print(f"ERROR: {error_msg}")
            return jsonify({"status": "error", "message": error_msg}), 400
            
        print(f"Processing message from {from_number}: {text}")
        
        # If we got here, we have valid message data
        
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
                
                # Send confirmation to provider with customer details
                if provider:
                    # Format appointment time
                    appointment_time = booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'
                    
                    # Get customer name, fallback to empty string if not available
                    customer_name = getattr(booking, 'customer_name', '')
                    
                    # Format service type (assuming format like '60 min · Mobile · $150')
                    service_type = booking.service_type or '60 min · Mobile · $150'
                    
                    # Format address (using the provided example if not available)
                    address = booking.address or '4400 Hillcrest Drive, Apt. 303, Hollywood, 33021'
                    
                    # Single confirmation message with all details
                    provider_message = (
                        "You've confirmed the booking! The customer has been notified.\n\n"
                        f"Customer: {customer_name} - {booking.customer_phone}\n"
                        f"Service: {service_type}\n"
                        f"When: {appointment_time}\n"
                        f"Address: {address}"
                    )
                    success, msg = send_sms(provider['phone'], provider_message)
                    if not success:
                        print(f"Failed to send confirmation to provider: {msg}")
                    # Don't send any other messages to provider

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

                # No need to send a second message to provider

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

def check_expired_bookings():
    """Background task to check for and handle expired bookings"""
    with app.app_context():
        try:
            now = datetime.utcnow()
            expired_bookings = Booking.query.filter(
                Booking.status == 'pending',
                Booking.response_deadline <= now
            ).all()
            
            for booking in expired_bookings:
                try:
                    # Update booking status
                    booking.status = 'expired'
                    booking.updated_at = datetime.utcnow()
                    db.session.commit()
                    
                    # Notify customer
                    alt_message = (
                        f"We're sorry, but the provider hasn't responded to your booking request. "
                        f"We're working to find you an alternative provider. "
                        f"You can also book with another provider here: goldtouchmobile.com/providers.\n\n"
                        "We apologize for any inconvenience and hope to serve you soon!"
                    )
                    success, msg = send_sms(booking.customer_phone, alt_message)
                    if not success:
                        print(f"Failed to send expiration notice to customer: {msg}")
                    
                    print(f"Marked booking {booking.id} as expired and notified customer")
                    
                except Exception as e:
                    db.session.rollback()
                    print(f"Error processing expired booking {booking.id}: {str(e)}")
                    
        except Exception as e:
            print(f"Error in check_expired_bookings: {str(e)}")

def start_background_tasks():
    """Start background tasks"""
    from apscheduler.schedulers.background import BackgroundScheduler
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=check_expired_bookings,
        trigger='interval',
        minutes=1,  # Check every minute
        id='expired_bookings_check',
        name='Check for expired bookings',
        replace_existing=True
    )
    scheduler.start()
    return scheduler

@app.route('/test-sms', methods=['GET'])
def test_sms():
    """Test endpoint to verify SMS functionality"""
    test_number = request.args.get('to')
    if not test_number:
        return jsonify({
            "status": "error",
            "message": "Missing 'to' parameter with phone number"
        }), 400
        
    test_message = "Test message from SMS system - please ignore"
    success, result = send_sms(test_number, test_message)
    
    return jsonify({
        "status": "success" if success else "error",
        "message": result,
        "number": test_number
    })

if __name__ == '__main__':
    # Start background tasks
    scheduler = start_background_tasks()
    
    # Start the web server
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
    
    # Shut down the scheduler when the app stops
    scheduler.shutdown()
