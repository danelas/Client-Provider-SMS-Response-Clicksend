from flask import Flask, request, jsonify
import os
import base64
import json
import requests
from pathlib import Path
from dotenv import load_dotenv
from models import db, Booking, Provider
from datetime import datetime, timedelta
import pytz

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Database configuration
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    # Fix for newer SQLAlchemy versions that require postgresql://
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///bookings.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

print(f"Using database: {app.config['SQLALCHEMY_DATABASE_URI'][:20]}...")

# Initialize database
db.init_app(app)

# Create tables and migrate existing providers
with app.app_context():
    db.create_all()
    
    # Migrate existing providers from JSON to database (one-time migration)
    try:
        # Check if we have any providers in the database already
        existing_count = Provider.query.count()
        
        if existing_count == 0 and PROVIDERS_FILE.exists():
            print("Migrating providers from JSON file to database...")
            with open(PROVIDERS_FILE, 'r') as f:
                json_providers = json.load(f)
            
            for provider_id, provider_data in json_providers.items():
                # Check if provider already exists
                if not Provider.query.get(provider_id):
                    new_provider = Provider(
                        id=provider_id,
                        name=provider_data.get('name', ''),
                        phone=provider_data.get('phone', '')
                    )
                    db.session.add(new_provider)
            
            db.session.commit()
            migrated_count = Provider.query.count()
            print(f"Successfully migrated {migrated_count} providers to database")
        else:
            print(f"Database already has {existing_count} providers, skipping migration")
            
    except Exception as e:
        print(f"Error during provider migration: {str(e)}")
        db.session.rollback()

# Start background tasks for production (moved outside of __main__ block)
try:
    scheduler = start_background_tasks()
    print("Background tasks started successfully")
except Exception as e:
    print(f"Warning: Could not start background tasks: {e}")
    scheduler = None

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
    """Look up provider details by ID from database"""
    try:
        if not provider_id:
            print("Error: No provider ID provided")
            return None
            
        provider = Provider.query.get(provider_id)
        
        if not provider:
            print(f"Error: Provider with ID '{provider_id}' not found in database")
            # List available provider IDs for debugging
            available_providers = Provider.query.all()
            available_ids = [p.id for p in available_providers]
            print(f"Available provider IDs: {available_ids}")
            return None
            
        return {'name': provider.name, 'phone': provider.phone}
        
    except Exception as e:
        print(f"Error loading providers: {str(e)}")
        return None

def clean_phone_number(phone):
    """Helper function to clean and standardize phone numbers"""
    if not phone:
        return ""
    # Remove all non-digit characters except +
    cleaned = ''.join(c for c in str(phone) if c == '+' or c.isdigit())
    # Ensure it starts with + and has country code
    if cleaned and not cleaned.startswith('+'):
        # Assume US/Canada number if no country code
        cleaned = f"+1{cleaned}" if len(cleaned) == 10 else f"+{cleaned}"
    return cleaned

def send_sms(to_number, message, from_number=None):
    """Send SMS using TextMagic API"""
    try:
        print(f"\n=== SEND_SMS STARTED ===")
        print(f"Original to_number: {to_number}")
        print(f"Original from_number: {from_number}")
        
        # Validate API credentials
        if not TEXTMAGIC_USERNAME or not TEXTMAGIC_API_KEY:
            error_msg = "TextMagic API credentials not configured"
            print(f"CREDENTIAL ERROR: {error_msg}")
            print(f"TEXTMAGIC_USERNAME: {'Set' if TEXTMAGIC_USERNAME else 'Not set'}")
            print(f"TEXTMAGIC_API_KEY: {'Set' if TEXTMAGIC_API_KEY else 'Not set'}")
            return False, error_msg
        
        # Clean and format numbers
        to_number = clean_phone_number(to_number)
        print(f"Cleaned to_number: {to_number}")
        
        if not to_number:
            error_msg = "Invalid or empty phone number"
            print(f"PHONE ERROR: {error_msg}")
            return False, error_msg
        
        # Handle sender ID (from_number)
        sender_id = clean_phone_number(from_number or TEXTMAGIC_FROM_NUMBER)
        print(f"Using sender_id: {sender_id}")
        
        # For TextMagic, the 'from' parameter should not include the +
        if sender_id and sender_id.startswith('+'):
            sender_id = sender_id[1:]
        
        headers = {
            'Content-Type': 'application/json',
            'X-TM-Username': TEXTMAGIC_USERNAME,
            'X-TM-Key': TEXTMAGIC_API_KEY
        }
        
        # For TextMagic, the 'phones' parameter should not include the +
        phones_number = to_number
        if phones_number and phones_number.startswith('+'):
            phones_number = phones_number[1:]
        
        payload = {
            'text': message,
            'phones': phones_number,
        }
        
        if sender_id:
            payload['from'] = sender_id
        
        print(f"Sending to: {to_number}")
        print(f"From: {sender_id}")
        print(f"Message length: {len(message)} characters")
        
        response = requests.post(
            TEXTMAGIC_API_URL,
            json=payload,
            headers=headers,
            timeout=10  # Add timeout to prevent hanging
        )
        
        print(f"API Response Status: {response.status_code}")
        print(f"API Response Headers: {dict(response.headers)}")
        print(f"API Response Body: {response.text}")
        
        if response.status_code == 201:
            try:
                response_data = response.json()
                print(f"SMS sent successfully - Response data: {response_data}")
                return True, f"SMS sent with ID: {response_data.get('id', 'unknown')}"
            except Exception as json_err:
                print(f"Warning: Could not parse JSON response: {json_err}")
                return True, "SMS sent successfully (could not parse response ID)"
        else:
            error_msg = f"TextMagic API error ({response.status_code}): {response.text}"
            print(f"API ERROR: {error_msg}")
            
            # Try to parse error details if available
            try:
                error_data = response.json()
                if 'message' in error_data:
                    error_msg += f" - Details: {error_data['message']}"
                if 'errors' in error_data:
                    error_msg += f" - Errors: {error_data['errors']}"
            except:
                pass
                
            return False, error_msg
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Request error sending SMS: {str(e)}"
        print(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error sending SMS: {str(e)}"
        print(error_msg)
        return False, error_msg
    finally:
        print("=== SEND_SMS COMPLETED ===\n")

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
        print(f"Provider ID from form: '{data['provider_id']}'")
        print(f"Provider ID type: {type(data['provider_id'])}")
        
        # Check if providers exist in database
        try:
            all_providers = Provider.query.all()
            provider_dict = {p.id: {'name': p.name, 'phone': p.phone} for p in all_providers}
            print(f"Successfully loaded {len(all_providers)} providers from database")
            print(f"Available provider IDs: {list(provider_dict.keys())}")
        except Exception as e:
            print(f"ERROR reading providers from database: {str(e)}")
            return jsonify({"status": "error", "message": f"Cannot read providers from database: {str(e)}"}), 500
        
        provider = get_provider(data['provider_id'])
        
        if not provider:
            error_msg = f"Provider with ID '{data['provider_id']}' not found"
            print(f"ERROR: {error_msg}")
            print(f"Form data received: {data}")
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
                
            # Calculate response deadline (15 minutes from now) - make it timezone aware
            utc = pytz.UTC
            current_time = datetime.utcnow()
            response_deadline = utc.localize(current_time) + timedelta(minutes=15)
            
            # Check if this is a last-minute booking (appointment within 1 hour)
            time_until_appointment = appointment_dt - current_time
            is_last_minute = time_until_appointment <= timedelta(hours=1)
            
            # Extract customer name from form data (handling both direct and nested formats)
            customer_name = ''
            if 'name' in data:
                customer_name = data['name']
            elif 'names' in data and isinstance(data['names'], dict) and 'First Name' in data['names']:
                customer_name = data['names']['First Name']
                
            # Create a new booking with detailed error handling
            try:
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
                print(f"Booking object created: {booking}")
                
                db.session.add(booking)
                db.session.commit()
                print("Booking successfully committed to database")
                
            except Exception as e:
                db.session.rollback()
                error_details = {
                    'error': str(e),
                    'type': type(e).__name__,
                    'data': {
                        'customer_phone': data['customer_phone'],
                        'provider_phone': provider['phone'],
                        'provider_id': data['provider_id'],
                        'service_type': data['service_type'],
                        'appointment_time': str(appointment_dt)
                    }
                }
                print(f"ERROR creating booking: {error_details}")
                return jsonify({
                    "status": "error",
                    "message": "Failed to create booking",
                    "details": str(e)
                }), 400
            
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
            # Check if service is In-Studio to exclude address
            is_in_studio = 'In-Studio' in data['service_type'] or 'in-studio' in data['service_type'].lower()
            
            # Add short-notice bonus line if it's a last-minute booking
            short_notice_line = "\n$20 Short-Notice Bonus" if is_last_minute else ""
            
            if is_in_studio:
                message = (
                    f"Hey {provider['name']}, new request: {data['service_type']} "
                    f"on {formatted_time}. {short_notice_line}"
                    f"\n\nReply Y to ACCEPT or N to DECLINE"
                )
            else:
                message = (
                    f"Hey {provider['name']}, new request: {data['service_type']} "
                    f"at {data['address']} on {formatted_time}. {short_notice_line}"
                    f"\n\nReply Y to ACCEPT or N to DECLINE"
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

@app.route('/confirm/<int:booking_id>', methods=['GET'])
def confirm_booking_manual(booking_id):
    """Manual confirmation endpoint - provider clicks link to confirm"""
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({"status": "error", "message": "Booking not found"}), 404
            
        if booking.status != 'pending':
            return jsonify({"status": "error", "message": f"Booking already {booking.status}"}), 400
        
        # Update booking status
        booking.status = 'confirmed'
        booking.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Get provider info
        provider = get_provider(booking.provider_id)
        provider_name = provider.get('name', 'the provider') if provider else 'the provider'
        
        # Send confirmation SMS to provider with customer details
        customer_name = getattr(booking, 'customer_name', '')
        appointment_time = booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'
        
        provider_message = (
            "✅ BOOKING CONFIRMED!\n\n"
            f"Customer: {customer_name} - {booking.customer_phone}\n\n"
            "Please contact the customer to arrange details."
        )
        
        success, msg = send_sms(provider['phone'], provider_message)
        if not success:
            print(f"Failed to send confirmation to provider: {msg}")
        
        # Send confirmation to customer
        customer_message = (
            f"Your booking with {provider_name} has been confirmed!\n\n"
            f"Service: {booking.service_type or 'Not specified'}\n"
            f"When: {appointment_time}\n"
            f"Address: {booking.address or 'Not specified'}\n\n"
            "The provider will contact you shortly."
        )
        
        success, msg = send_sms(booking.customer_phone, customer_message)
        if not success:
            print(f"Failed to send confirmation to customer: {msg}")
        
        return f"""
        <html>
        <head><title>Booking Confirmed</title></head>
        <body style="font-family: Arial; padding: 20px; text-align: center;">
            <h2>✅ Booking Confirmed!</h2>
            <p>Customer details have been sent to your phone.</p>
            <p>Customer: {customer_name} - {booking.customer_phone}</p>
            <p>Service: {booking.service_type}</p>
            <p>When: {appointment_time}</p>
            <p>Address: {booking.address or 'Not specified'}</p>
        </body>
        </html>
        """
        
    except Exception as e:
        print(f"Error in manual confirmation: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/decline/<int:booking_id>', methods=['GET'])
def decline_booking_manual(booking_id):
    """Manual decline endpoint - provider clicks link to decline"""
    try:
        booking = Booking.query.get(booking_id)
        if not booking:
            return jsonify({"status": "error", "message": "Booking not found"}), 404
            
        if booking.status != 'pending':
            return jsonify({"status": "error", "message": f"Booking already {booking.status}"}), 400
        
        # Update booking status
        booking.status = 'rejected'
        booking.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Send rejection message to customer
        alt_message = (
            "We're sorry, but the provider you selected is not available. "
            "You can book with another provider here: goldtouchmobile.com/providers\n\n"
            "We apologize for any inconvenience."
        )
        success, msg = send_sms(booking.customer_phone, alt_message)
        if not success:
            print(f"Failed to send rejection to customer: {msg}")
        
        return f"""
        <html>
        <head><title>Booking Declined</title></head>
        <body style="font-family: Arial; padding: 20px; text-align: center;">
            <h2>❌ Booking Declined</h2>
            <p>The customer has been notified that you're not available.</p>
            <p>Thank you for your prompt response.</p>
        </body>
        </html>
        """
        
    except Exception as e:
        print(f"Error in manual decline: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook/textmagic', methods=['GET', 'POST', 'PUT'])
def sms_webhook():
    """Handle incoming SMS webhooks from TextMagic"""
    # Handle webhook validation (GET request)
    if request.method == 'GET':
        print("Webhook validation request received")
        return jsonify({"status": "ok"}), 200
    
    try:
        # Log all incoming requests for debugging
        print(f"\n{'='*20} INCOMING WEBHOOK REQUEST {'='*20}")
        print(f"Time: {datetime.utcnow().isoformat()}")
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Content-Type: {request.content_type}")
        print(f"Form data: {request.form}")
        print(f"JSON data: {request.get_json(silent=True) or 'No JSON data'}")
        print(f"Raw data: {request.get_data()}")
        print("-" * 60)
        
        # Parse the request data based on Content-Type
        content_type = request.headers.get('Content-Type', '').lower()
        data = {}
        if 'application/json' in content_type:
            data = request.get_json(silent=True) or {}
        elif 'application/x-www-form-urlencoded' in content_type:
            data = request.form.to_dict()
        else:
            data = request.form.to_dict() or request.get_json(silent=True) or {}

        if not data:
            print("No webhook data received")
            return jsonify({"status": "ok"}), 200
            
        print(f"Parsed webhook data: {data}")
        
        # Extract message text and sender
        text = (
            data.get('text') or 
            data.get('body') or 
            data.get('message', '')
        ).strip().lower()
        
        from_number = clean_phone_number(
            data.get('from') or 
            data.get('sender') or 
            data.get('customer_phone', '')
        )
        
        print(f"From: {from_number}, Message: '{text}'")
        
        if not text or not from_number:
            print("Missing text or from_number")
            return jsonify({"status": "ok"}), 200
        
        # Find pending booking for this provider
        booking = None
        all_pending = Booking.query.filter_by(status='pending').all()
        
        for b in all_pending:
            if hasattr(b, 'provider_phone') and b.provider_phone:
                booking_phone_normalized = clean_phone_number(b.provider_phone).replace('+', '').replace('-', '').replace(' ', '')
                provider_phone_normalized = from_number.replace('+', '').replace('-', '').replace(' ', '')
                
                if booking_phone_normalized == provider_phone_normalized:
                    booking = b
                    print(f"✓ Found booking by phone match: {booking.id}")
                    break
        
        if not booking:
            print(f"No pending booking found for provider: {from_number}")
            return jsonify({"status": "ok"}), 200
        
        # Get provider info
        provider = get_provider(booking.provider_id)
        
        # Process Y/N response
        if text in ['y', 'yes']:
            print(f"Processing CONFIRMATION for booking {booking.id}")
            
            # Update booking status
            booking.status = 'confirmed'
            booking.updated_at = datetime.utcnow()
            db.session.commit()
            
            # Get customer name
            customer_name = getattr(booking, 'customer_name', '')
            appointment_time = booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'
            
            # Send confirmation SMS to provider with customer details
            provider_message = (
                "✅ BOOKING CONFIRMED!\n\n"
                f"Customer: {customer_name} - {booking.customer_phone}\n\n"
                "Please contact the customer to arrange details."
            )
            
            print(f"=== SENDING CONFIRMATION TO PROVIDER ===")
            print(f"Provider phone: {provider['phone'] if provider else 'Unknown'}")
            print(f"Provider message: {provider_message}")
            
            if provider:
                success, msg = send_sms(provider['phone'], provider_message)
                if success:
                    print(f"✓ Successfully sent confirmation to provider: {msg}")
                else:
                    print(f"✗ FAILED to send confirmation to provider: {msg}")
            
            # Send confirmation to customer
            provider_name = provider.get('name', 'the provider') if provider else 'the provider'
            customer_message = (
                f"Your booking with {provider_name} has been confirmed!\n\n"
                f"Service: {booking.service_type or 'Not specified'}\n"
                f"When: {appointment_time}\n"
                f"Address: {booking.address or 'Not specified'}\n\n"
                "The provider will contact you shortly."
            )
            
            success, msg = send_sms(booking.customer_phone, customer_message)
            if success:
                print(f"✓ Successfully sent confirmation to customer: {msg}")
            else:
                print(f"✗ FAILED to send confirmation to customer: {msg}")
            
            print(f"Booking {booking.id} confirmed successfully")
            
        elif text in ['n', 'no']:
            print(f"Processing REJECTION for booking {booking.id}")
            
            # Update booking status
            booking.status = 'rejected'
            booking.updated_at = datetime.utcnow()
            db.session.commit()
            
            # Send rejection message to customer
            alt_message = (
                "The provider you selected isn't available at this time, but you can easily choose another provider here: goldtouchmobile.com/providers.\n"
                "As a thank-you for your flexibility, we'd like to offer you $15 off your next massage. We appreciate your understanding and look forward to serving you."
            )
            success, msg = send_sms(booking.customer_phone, alt_message)
            if not success:
                print(f"Failed to send rejection to customer: {msg}")
            
            print(f"Booking {booking.id} rejected successfully")
        else:
            print(f"Invalid response: '{text}'. Expected Y or N")
        
        # ALWAYS return 200 OK to prevent webhook deletion
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        import traceback
        print(traceback.format_exc())
        # STILL return 200 OK even on error to prevent webhook deletion
        return jsonify({"status": "ok"}), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

@app.route('/providers', methods=['GET'])
def list_providers():
    """List all providers"""
    try:
        providers = Provider.query.all()
        provider_dict = {p.id: {'name': p.name, 'phone': p.phone} for p in providers}
        return jsonify(provider_dict), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/providers/add', methods=['POST', 'GET'])
def add_provider():
    """Add a new provider"""
    if request.method == 'GET':
        # Show form
        return """
        <html>
        <head><title>Add Provider</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>Add New Provider</h2>
            <form method="POST">
                <p>
                    <label>Provider ID:</label><br>
                    <input type="text" name="provider_id" placeholder="provider24" required style="padding: 8px; width: 200px;">
                </p>
                <p>
                    <label>Name:</label><br>
                    <input type="text" name="name" placeholder="John Doe" required style="padding: 8px; width: 200px;">
                </p>
                <p>
                    <label>Phone:</label><br>
                    <input type="text" name="phone" placeholder="+1234567890" required style="padding: 8px; width: 200px;">
                </p>
                <p>
                    <button type="submit" style="padding: 10px 20px; background: #007cba; color: white; border: none; cursor: pointer;">Add Provider</button>
                    <a href="/providers/manage" style="margin-left: 10px;">Back to Manage</a>
                </p>
            </form>
        </body>
        </html>
        """
    
    try:
        # Get form data
        provider_id = request.form.get('provider_id')
        name = request.form.get('name')
        phone = request.form.get('phone')
        
        if not all([provider_id, name, phone]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Check if provider already exists
        existing_provider = Provider.query.get(provider_id)
        if existing_provider:
            return jsonify({"error": f"Provider with ID '{provider_id}' already exists"}), 400
        
        # Create new provider
        new_provider = Provider(id=provider_id, name=name, phone=phone)
        db.session.add(new_provider)
        db.session.commit()
        
        return f"""
        <html>
        <head><title>Provider Added</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>✅ Provider Added Successfully!</h2>
            <p><strong>ID:</strong> {provider_id}</p>
            <p><strong>Name:</strong> {name}</p>
            <p><strong>Phone:</strong> {phone}</p>
            <p><a href="/providers/manage">Back to Manage Providers</a></p>
        </body>
        </html>
        """
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/providers/manage', methods=['GET'])
def manage_providers():
    """Provider management interface"""
    try:
        providers = Provider.query.all()
        
        provider_rows = ""
        for provider in providers:
            provider_rows += f"""
            <tr>
                <td>{provider.id}</td>
                <td>{provider.name}</td>
                <td>{provider.phone}</td>
                <td>
                    <a href="/providers/edit/{provider.id}" style="color: #007cba;">Edit</a> | 
                    <a href="/providers/delete/{provider.id}" style="color: #d63384;" onclick="return confirm('Delete {provider.name}?')">Delete</a>
                </td>
            </tr>
            """
        
        return f"""
        <html>
        <head><title>Manage Providers</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>Manage Providers</h2>
            <p><a href="/providers/add" style="background: #28a745; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px;">+ Add New Provider</a></p>
            
            <table border="1" style="border-collapse: collapse; width: 100%; margin-top: 20px;">
                <tr style="background: #f8f9fa;">
                    <th style="padding: 10px; text-align: left;">Provider ID</th>
                    <th style="padding: 10px; text-align: left;">Name</th>
                    <th style="padding: 10px; text-align: left;">Phone</th>
                    <th style="padding: 10px; text-align: left;">Actions</th>
                </tr>
                {provider_rows}
            </table>
            
            <div style="margin-top: 30px; padding: 15px; background: #e9ecef; border-radius: 5px;">
                <h3>✅ Providers are now stored in the database!</h3>
                <p>Changes will persist across deployments automatically. No need to manually commit to Git.</p>
            </div>
        </body>
        </html>
        """
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/providers/edit/<provider_id>', methods=['GET', 'POST'])
def edit_provider(provider_id):
    """Edit an existing provider"""
    try:
        provider = Provider.query.get(provider_id)
        
        if not provider:
            return jsonify({"error": "Provider not found"}), 404
        
        if request.method == 'GET':
            # Show edit form
            return f"""
            <html>
            <head><title>Edit Provider</title></head>
            <body style="font-family: Arial; padding: 20px;">
                <h2>Edit Provider: {provider_id}</h2>
                <form method="POST">
                    <p>
                        <label>Name:</label><br>
                        <input type="text" name="name" value="{provider.name}" required style="padding: 8px; width: 200px;">
                    </p>
                    <p>
                        <label>Phone:</label><br>
                        <input type="text" name="phone" value="{provider.phone}" required style="padding: 8px; width: 200px;">
                    </p>
                    <p>
                        <button type="submit" style="padding: 10px 20px; background: #007cba; color: white; border: none; cursor: pointer;">Update Provider</button>
                        <a href="/providers/manage" style="margin-left: 10px;">Cancel</a>
                    </p>
                </form>
            </body>
            </html>
            """
        
        # Handle POST - update provider
        name = request.form.get('name')
        phone = request.form.get('phone')
        
        if not all([name, phone]):
            return jsonify({"error": "Missing required fields"}), 400
        
        # Update provider in database
        provider.name = name
        provider.phone = phone
        db.session.commit()
        
        return f"""
        <html>
        <head><title>Provider Updated</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>✅ Provider Updated Successfully!</h2>
            <p><strong>ID:</strong> {provider_id}</p>
            <p><strong>Name:</strong> {name}</p>
            <p><strong>Phone:</strong> {phone}</p>
            <p><a href="/providers/manage">Back to Manage Providers</a></p>
        </body>
        </html>
        """
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/providers/delete/<provider_id>', methods=['GET'])
def delete_provider(provider_id):
    """Delete a provider"""
    try:
        provider = Provider.query.get(provider_id)
        
        if not provider:
            return jsonify({"error": "Provider not found"}), 404
        
        # Store provider info before deletion
        deleted_name = provider.name
        deleted_phone = provider.phone
        
        # Remove provider from database
        db.session.delete(provider)
        db.session.commit()
        
        return f"""
        <html>
        <head><title>Provider Deleted</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>🗑️ Provider Deleted</h2>
            <p><strong>Deleted:</strong> {deleted_name} ({deleted_phone})</p>
            <p><a href="/providers/manage">Back to Manage Providers</a></p>
        </body>
        </html>
        """
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/debug-webhook', methods=['POST'])
def debug_webhook():
    """Debug endpoint to test webhook processing without TextMagic"""
    try:
        # Get the most recent pending booking
        booking = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).first()
        
        if not booking:
            return jsonify({
                "status": "error", 
                "message": "No pending bookings found",
                "debug_info": {
                    "total_bookings": Booking.query.count(),
                    "pending_bookings": Booking.query.filter_by(status='pending').count()
                }
            }), 404
        
        # Simulate provider confirmation
        booking.status = 'confirmed'
        booking.updated_at = datetime.utcnow()
        db.session.commit()
        
        # Get provider info
        provider = get_provider(booking.provider_id)
        provider_name = provider.get('name', 'the provider') if provider else 'the provider'
        
        # Format messages (but don't send them)
        provider_message = (
            "You've confirmed the booking! The customer has been notified.\n\n"
            f"Customer: {getattr(booking, 'customer_name', '')} - {booking.customer_phone}\n"
            f"Service: {booking.service_type}\n"
            f"When: {booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'}\n"
            f"Address: {booking.address or 'Not specified'}"
        )
        
        customer_message = (
            f"Your booking with {provider_name} has been confirmed!\n\n"
            f"Service: {booking.service_type or 'Not specified'}\n"
            f"When: {booking.appointment_time.strftime('%A, %B %d at %I:%M %p') if booking.appointment_time else 'Not specified'}\n"
            f"Address: {booking.address or 'Not specified'}\n\n"
            "Thank you for choosing our service!"
        )
        
        return jsonify({
            "status": "success",
            "message": "Booking confirmed (debug mode - no SMS sent)",
            "booking_id": booking.id,
            "provider_message": provider_message,
            "customer_message": customer_message,
            "debug_info": {
                "booking_status": booking.status,
                "provider_phone": provider.get('phone') if provider else 'Unknown',
                "customer_phone": booking.customer_phone,
                "textmagic_configured": bool(TEXTMAGIC_USERNAME and TEXTMAGIC_API_KEY)
            }
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "type": type(e).__name__
        }), 500

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

@app.route('/migrate-providers', methods=['GET'])
def migrate_providers():
    """Manual endpoint to migrate providers from JSON to database"""
    try:
        # Check current database state
        existing_count = Provider.query.count()
        
        # Define providers file path
        providers_file = Path(__file__).parent / 'providers.json'
        
        # Check if JSON file exists
        if not providers_file.exists():
            return jsonify({
                "status": "error",
                "message": "providers.json file not found",
                "existing_providers": existing_count
            }), 404
        
        # Load providers from JSON
        with open(providers_file, 'r') as f:
            json_providers = json.load(f)
        
        migrated_count = 0
        skipped_count = 0
        
        for provider_id, provider_data in json_providers.items():
            # Check if provider already exists
            existing_provider = Provider.query.get(provider_id)
            
            if existing_provider:
                skipped_count += 1
                print(f"Provider {provider_id} already exists, skipping")
                continue
            
            # Create new provider
            new_provider = Provider(
                id=provider_id,
                name=provider_data.get('name', ''),
                phone=provider_data.get('phone', '')
            )
            db.session.add(new_provider)
            migrated_count += 1
            print(f"Added provider {provider_id}: {provider_data.get('name')} - {provider_data.get('phone')}")
        
        # Commit all changes
        db.session.commit()
        
        final_count = Provider.query.count()
        
        return jsonify({
            "status": "success",
            "message": f"Migration completed successfully",
            "details": {
                "providers_in_json": len(json_providers),
                "existing_before": existing_count,
                "migrated": migrated_count,
                "skipped": skipped_count,
                "total_after": final_count
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Migration failed: {str(e)}",
            "type": type(e).__name__
        }), 500

@app.route('/debug-providers', methods=['GET'])
def debug_providers():
    """Debug endpoint to check provider status"""
    try:
        # Check database providers
        db_providers = Provider.query.all()
        db_count = len(db_providers)
        
        # Check JSON file
        providers_file = Path(__file__).parent / 'providers.json'
        json_exists = providers_file.exists()
        json_count = 0
        json_sample = {}
        
        if json_exists:
            try:
                with open(providers_file, 'r') as f:
                    json_data = json.load(f)
                json_count = len(json_data)
                # Get first 3 providers as sample
                json_sample = dict(list(json_data.items())[:3])
            except Exception as e:
                json_sample = {"error": str(e)}
        
        # Get database sample
        db_sample = []
        for provider in db_providers[:3]:
            db_sample.append({
                "id": provider.id,
                "name": provider.name,
                "phone": provider.phone
            })
        
        return jsonify({
            "database": {
                "count": db_count,
                "sample": db_sample
            },
            "json_file": {
                "exists": json_exists,
                "count": json_count,
                "sample": json_sample
            },
            "migration_url": "/migrate-providers",
            "file_path": str(providers_file)
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "type": type(e).__name__
        }), 500

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
        "phone_number": test_number
    })

@app.route('/debug-customer-sms', methods=['GET'])
def debug_customer_sms():
    """Debug endpoint to test customer SMS scenarios"""
    try:
        customer_phone = request.args.get('customer_phone')
        scenario = request.args.get('scenario', 'confirmation')  # confirmation, rejection, timeout
        
        if not customer_phone:
            return jsonify({
                "status": "error",
                "message": "Missing 'customer_phone' parameter"
            }), 400
        
        # Clean the phone number
        cleaned_phone = clean_phone_number(customer_phone)
        
        # Test different customer SMS scenarios
        if scenario == 'confirmation':
            message = (
                "Your booking with Test Provider has been confirmed!\n\n"
                "Service: Test Service\n"
                "When: Test Time\n"
                "Address: Test Address\n\n"
                "The provider will contact you shortly."
            )
        elif scenario == 'rejection':
            message = (
                "The provider you selected isn't available at this time, but you can easily choose another provider here: goldtouchmobile.com/providers.\n"
                "As a thank-you for your flexibility, we'd like to offer you $15 off your next massage. We appreciate your understanding and look forward to serving you."
            )
        elif scenario == 'timeout':
            message = (
                "We're sorry, but the provider hasn't responded to your booking request. "
                "We're working to find you an alternative provider. "
                "You can also book with another provider here: goldtouchmobile.com/providers.\n\n"
                "We apologize for any inconvenience and hope to serve you soon!"
            )
        else:
            return jsonify({
                "status": "error",
                "message": "Invalid scenario. Use: confirmation, rejection, or timeout"
            }), 400
        
        print(f"=== DEBUGGING CUSTOMER SMS ===")
        print(f"Original phone: {customer_phone}")
        print(f"Cleaned phone: {cleaned_phone}")
        print(f"Scenario: {scenario}")
        print(f"Message: {message}")
        
        success, result = send_sms(cleaned_phone, message)
        
        return jsonify({
            "status": "success" if success else "error",
            "message": result,
            "original_phone": customer_phone,
            "cleaned_phone": cleaned_phone,
            "scenario": scenario,
            "sms_message": message
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Debug error: {str(e)}"
        }), 500

@app.route('/test-webhook', methods=['POST'])
def test_webhook():
    """Test endpoint to simulate a webhook response"""
    try:
        # Get test parameters
        provider_phone = request.json.get('provider_phone', '+15551234567')
        response_text = request.json.get('response', 'Y')
        
        # Create test webhook data in TextMagic format
        test_webhook_data = {
            'from': provider_phone,
            'text': response_text,
            'receiver': TEXTMAGIC_FROM_NUMBER,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        print(f"=== SIMULATING WEBHOOK RESPONSE ===")
        print(f"Test data: {test_webhook_data}")
        
        # Simulate the webhook request
        with app.test_request_context('/webhook/sms', 
                                    method='POST', 
                                    json=test_webhook_data,
                                    headers={'Content-Type': 'application/json'}):
            response = sms_webhook()
            
        return jsonify({
            'status': 'success',
            'message': 'Test webhook processed',
            'test_data': test_webhook_data,
            'webhook_response': response.get_json() if hasattr(response, 'get_json') else str(response)
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__
        }), 500

@app.route('/test-db', methods=['GET'])
def test_db():
    """Test endpoint to verify database and model functionality"""
    try:
        # Test database connection
        db.session.execute(text('SELECT 1'))
        
        # Test creating a test booking
        test_booking = Booking(
            customer_phone='+15551234567',
            customer_name='Test User',
            provider_phone='+15559876543',
            provider_id='test_provider',
            service_type='Test Service',
            status='test',
            appointment_time=datetime.utcnow(),
            response_deadline=datetime.utcnow() + timedelta(hours=1)
        )
        
        db.session.add(test_booking)
        db.session.commit()
        
        # Clean up
        db.session.delete(test_booking)
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Database and model test passed',
            'database_url': os.getenv('DATABASE_URL', 'sqlite:///bookings.db')
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__,
            'database_url': os.getenv('DATABASE_URL', 'sqlite:///bookings.db')
        }), 500

@app.route('/routes', methods=['GET'])
def list_routes():
    """List all available routes for debugging"""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': str(rule)
        })
    return jsonify({'routes': routes})

@app.route('/webhook-status', methods=['GET'])
def webhook_status():
    """Check webhook configuration and recent activity"""
    try:
        # Check recent bookings
        recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(5).all()
        
        # Check TextMagic configuration
        textmagic_config = {
            'username_set': bool(TEXTMAGIC_USERNAME),
            'api_key_set': bool(TEXTMAGIC_API_KEY),
            'from_number': TEXTMAGIC_FROM_NUMBER,
            'webhook_url': 'https://client-provider-sms-response-clicksend-1.onrender.com/webhook/sms'
        }
        
        # Format booking data
        bookings_data = []
        for booking in recent_bookings:
            bookings_data.append({
                'id': booking.id,
                'status': booking.status,
                'customer_phone': booking.customer_phone,
                'provider_phone': getattr(booking, 'provider_phone', 'N/A'),
                'provider_id': booking.provider_id,
                'created_at': booking.created_at.isoformat() if booking.created_at else None,
                'updated_at': booking.updated_at.isoformat() if booking.updated_at else None
            })
        
        return jsonify({
            'status': 'success',
            'webhook_url': 'https://client-provider-sms-response-clicksend-1.onrender.com/webhook/sms',
            'textmagic_config': textmagic_config,
            'recent_bookings': bookings_data,
            'pending_bookings_count': Booking.query.filter_by(status='pending').count(),
            'total_bookings_count': Booking.query.count(),
            'instructions': {
                'test_webhook': 'Send SMS "Y" to your TextMagic number and check logs',
                'check_textmagic': 'Verify webhook URL is set in TextMagic dashboard',
                'debug_booking': 'Use POST /debug-webhook to test confirmation flow'
            }
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__
        }), 500

if __name__ == '__main__':
    # Run the app (background tasks already started above)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
