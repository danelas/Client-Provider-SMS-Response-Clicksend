from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import os
import base64
import json
import re
import requests
from pathlib import Path
from dotenv import load_dotenv
from models import db, Booking, Provider, MessageLog
from datetime import datetime, timedelta
import pytz
import openai

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-here-change-in-production')

# Database configuration
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    # Fix for newer SQLAlchemy versions that require postgresql://
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///bookings.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Add SSL configuration for PostgreSQL with fallback options
if database_url and 'postgresql://' in database_url:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'connect_args': {
            'sslmode': 'prefer',
            'connect_timeout': 10,
            'application_name': 'goldtouch_app'
        },
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_reset_on_return': 'commit',
        'pool_size': 5,
        'max_overflow': 10
    }

print(f"Using database: {app.config['SQLALCHEMY_DATABASE_URI'][:20]}...")

# Initialize database
db.init_app(app)

# Database tables will be created automatically when first accessed
# Removed startup db.create_all() to prevent app crashes on database connection issues

# Background scheduler will be initialized after function definitions

# TextMagic API credentials
TEXTMAGIC_USERNAME = os.getenv('TEXTMAGIC_USERNAME')
TEXTMAGIC_API_KEY = os.getenv('TEXTMAGIC_API_KEY')
TEXTMAGIC_FROM_NUMBER = os.getenv('TEXTMAGIC_FROM_NUMBER')

# TextMagic API endpoint
TEXTMAGIC_API_URL = 'https://rest.textmagic.com/api/v2/messages'

# OpenAI configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    print("OpenAI API configured")
else:
    print("Warning: OPENAI_API_KEY not set - AI customer support disabled")

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

def clean_phone_number_for_registration(phone):
    """Clean phone number for provider registration - removes brackets, dashes, spaces and ensures +1 prefix"""
    if not phone:
        return None
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', str(phone))
    
    # Remove any + that's not at the beginning
    if '+' in cleaned[1:]:
        cleaned = cleaned[0] + cleaned[1:].replace('+', '')
    
    # If it starts with 1 but no +, add the +
    if cleaned.startswith('1') and not cleaned.startswith('+1'):
        cleaned = '+' + cleaned
    
    # If it's 10 digits (US number without country code), add +1
    elif len(cleaned) == 10 and cleaned.isdigit():
        cleaned = '+1' + cleaned
    
    # If it doesn't start with + but has 11 digits starting with 1, add +
    elif len(cleaned) == 11 and cleaned.startswith('1') and not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    
    return cleaned

def generate_next_provider_id():
    """Generate the next available provider ID (provider60, provider61, etc.)"""
    try:
        # Get all existing provider IDs
        existing_providers = Provider.query.all()
        existing_ids = [p.id for p in existing_providers if p.id]
        
        # Extract numbers from provider IDs (provider60 -> 60)
        numbers = []
        for provider_id in existing_ids:
            if provider_id.startswith('provider'):
                try:
                    number = int(provider_id.replace('provider', ''))
                    numbers.append(number)
                except ValueError:
                    continue
        
        # Find the next available number
        if not numbers:
            next_number = 60  # Start from provider60
        else:
            next_number = max(numbers) + 1
        
        return f'provider{next_number}'
    
    except Exception as e:
        print(f"Error generating provider ID: {e}")
        # Fallback to timestamp-based ID
        import time
        return f'provider{int(time.time())}'

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

def format_appointment_time_et(appointment_time):
    """Convert UTC appointment time to Eastern Time for display"""
    if not appointment_time:
        return 'Not specified'
    
    utc = pytz.UTC
    et = pytz.timezone('US/Eastern')
    
    # Handle both timezone-aware and naive datetime objects
    if appointment_time.tzinfo is None:
        appointment_time_utc = utc.localize(appointment_time)
    else:
        appointment_time_utc = appointment_time
    
    appointment_time_et = appointment_time_utc.astimezone(et)
    return appointment_time_et.strftime('%A, %B %d at %I:%M %p ET')

def detect_cancellation_request(message):
    """Detect if customer message contains cancellation/rescheduling keywords"""
    cancellation_keywords = [
        'cancel', 'cancellation', 'cancelled', 'canceling',
        'reschedule', 'rescheduling', 'reschedule',
        'postpone', 'postponing', 'postponed',
        'move', 'moving', 'change', 'changing',
        'something came up', 'emergency', 'can\'t make it',
        'need to cancel', 'need to reschedule', 'need to change',
        'have to cancel', 'have to reschedule', 'have to change',
        'sorry', 'apologies', 'apologize'
    ]
    
    message_lower = message.lower()
    
    # Check for direct cancellation/rescheduling keywords
    for keyword in cancellation_keywords:
        if keyword in message_lower:
            return True
    
    # Check for phrases that indicate cancellation intent
    cancellation_phrases = [
        'something came up',
        'can\'t make it',
        'won\'t be able to',
        'need to move',
        'have to move',
        'different time',
        'later time',
        'another day',
        'another time'
    ]
    
    for phrase in cancellation_phrases:
        if phrase in message_lower:
            return True
    
    return False

def notify_provider_of_cancellation(customer_phone, customer_message, booking=None):
    """Notify provider when customer requests cancellation/rescheduling"""
    try:
        # Find the most recent confirmed booking for this customer
        if not booking:
            customer_phone_normalized = clean_phone_number(customer_phone).replace('+', '').replace('-', '').replace(' ', '')
            
            # Look for confirmed bookings from this customer in the last 7 days
            cutoff_time = datetime.utcnow() - timedelta(days=7)
            booking = Booking.query.filter(
                Booking.status == 'confirmed',
                Booking.created_at >= cutoff_time
            ).filter(
                Booking.customer_phone.like(f'%{customer_phone_normalized[-10:]}%')  # Match last 10 digits
            ).order_by(Booking.created_at.desc()).first()
        
        if not booking:
            print(f"⚠️ No recent confirmed booking found for customer {customer_phone}")
            return False
        
        # Get provider info
        provider = get_provider(booking.provider_id)
        if not provider:
            print(f"⚠️ Provider not found for booking {booking.id}")
            return False
        
        # Create notification message for provider
        customer_name = getattr(booking, 'customer_name', '') or 'Customer'
        appointment_time = format_appointment_time_et(booking.appointment_time)
        
        provider_message = (
            f"🚨 Cancellation Notice\n\n"
            f"Customer: {customer_name} ({booking.customer_phone})\n"
            f"Appointment: {appointment_time}\n\n"
            f"Please contact the customer to confirm cancellation/rescheduling."
        )
        
        # Send notification to provider
        success, result = send_sms(provider['phone'], provider_message)
        if success:
            print(f"✓ Cancellation notification sent to provider {provider['name']}")
            
            # Update booking status to indicate cancellation requested
            booking.status = 'cancellation_requested'
            booking.updated_at = datetime.utcnow()
            db.session.commit()
            
            return True
        else:
            print(f"✗ Failed to send cancellation notification to provider: {result}")
            return False
            
    except Exception as e:
        print(f"Error notifying provider of cancellation: {str(e)}")
        return False

def get_ai_support_response(message, phone=None, is_provider=False):
    """Generate AI support response for both customers and providers using OpenAI"""
    if not OPENAI_API_KEY:
        return None
    
    try:
        if is_provider:
            # Provider-specific knowledge base
            system_prompt = """You are a helpful support agent for Gold Touch Mobile Massage providers. You assist massage therapists who work with our platform.

PROVIDER INFORMATION:
- Business Zelle: goldtouchmassage1@gmail.com (share this with customers if they ask)
- Booking Process: You receive SMS requests, reply Y to accept or N to decline
- Response Time: You have 15 minutes to respond to booking requests
- Service Areas: All of Florida
- Platform: Manage bookings through goldtouchmobile.com

PROVIDER EARNINGS BREAKDOWN:
MASSAGE SERVICES:
• 60 min Mobile $150 → You earn: $100 (Gold Touch retains: $50)
• 90 min Mobile $200 → You earn: $130 (Gold Touch retains: $70)
• 60 min In-Studio $120 → You earn: $72 (Gold Touch retains: $48)
• 90 min In-Studio $170 → You earn: $120 (Gold Touch retains: $50)
• Reflexology (60 min) $150 → You earn: $100 (Gold Touch retains: $50)

WELLNESS & ADD-ON SERVICES:
• Aromatherapy $15 → You earn: $15 (100% yours)
• Scalp Treatments $15 → You earn: $15 (100% yours)
• Hot Stones $30 → You earn: $30 (100% yours)
• Body Scrubs/Wraps $40 → You earn: $30 (Gold Touch retains: $10)
• Cupping Therapy (45 min) $100 → You earn: $65 (Gold Touch retains: $35)

FACIALS & MAKEUP:
• Facial (45 min) $100 → You earn: $65 (Gold Touch retains: $35)
• Basic Makeup $100 → You earn: $65 (Gold Touch retains: $35)
• Full Glam Makeup $140 → You earn: $90 (Gold Touch retains: $50)
• Bridal Makeup $240 → You earn: $160 (Gold Touch retains: $80)
• Brow Shaping $60 → You earn: $40 (Gold Touch retains: $20)

ACUPUNCTURE:
• Acupuncture (60 min) $140 → You earn: $95 (Gold Touch retains: $45)
• Acupuncture (90 min) $180 → You earn: $120 (Gold Touch retains: $60)

• Tips are 100% yours and go directly to you

PROVIDER AGREEMENT TERMS:
- Independent Contractor Status: You are NOT an employee, responsible for own licensing/taxes
- Equipment: You provide your own massage table, linens, supplies, transportation
- Licensing: If no FL massage license, services are non-clinical wellness only
- Client Payment Methods: Phone (954) 872-4058, Zelle goldtouchmassage1@gmail.com, Venmo
- Dispatch Number: Save (954) 466-5191 - ALL bookings come from this number
- Photo Required: Clear recent photo for scheduling and safety verification
- Client Booking Policy: Gold Touch clients MUST continue booking through our platform (no direct bookings)

COMPREHENSIVE PROVIDER FAQ:

1. How does the appointment system work?
Clients book directly through our online system. Once a booking is made, you'll get notified right away by text or email (whichever you prefer). You'll always be able to confirm or decline an appointment.

PROFILE SETUP:
- We take care of your profile setup for you
- We also have upgrades if you want to build your own customized premium profile and more at https://goldtouchmobile.com/feature-my-profile/

2. How much notice will I get before a client appointment?
Ideally, you'll be notified several hours in advance or more. We don't allow last-minute bookings unless you've specifically marked yourself as available. You'll always have the ability to accept or reject any appointment.

3. Can I set custom hours or time frames for each day? Can I start on a specific date?
We're still working on the scheduling feature for providers to set their own availability.

For start dates: No problem, we will put you on the site at that time. Just let us know your preferred start date and we'll handle it.

4. How long is the agreement valid?
The agreement is open and ongoing — it doesn't lock you into a time period. It simply outlines expectations, payment structure, and client policies.

5. Can I pause or stop when I need to?
Yes, absolutely. You can pause your availability at any time or step away when needed — just give us a heads-up so we can adjust accordingly.

6. What if I have to cancel or I'm unavailable?
We ask that you give us as much notice as possible. Repeated unresponsiveness or missed sessions without notice may lead to removal from the site. After three unnotified absences or cancellations, your profile will be deactivated and you'll no longer be able to work with us unless you contact us in advance to let us know you'll be away.

8. How do client payments work? Do I need to collect money? Are payouts weekly or bi-weekly? Where do I set up the account to be paid?
Payment is made by the client after the massage directly to you. You then send Gold Touch its portion through:
- Zelle: goldtouchmassage1@gmail.com 
- Venmo: https://www.venmo.com/u/goldtouchmassage

You do not need to set up any payment account - everything is done for you as part of being with Gold Touch Massage brand. We do this to keep things smooth. You'll be informed before each appointment of the total price and your earnings breakdown based on:
- The location
- The massage type  
- Specialty/Add-on Type
- Duration

You keep your portion and send Gold Touch our portion after collecting payment from the client. There are no scheduled payouts since you receive payment directly from clients immediately after each service.

9. How does Gold Touch Massage protect providers?
We send a quick text after every massage to check in and ensure everything went smoothly. Your safety is our priority. Every client who books through Gold Touch agrees to our terms, which include:
- Contact information
- Agreement to our Terms of Service and Privacy Policy
- Consent to receive appointment-related text messages
- Willingness to provide brief ID verification if requested by the provider

This gives you the right to request a simple ID check before confirming a booking. It's a small step that goes a long way in keeping you informed and confident about who you're seeing.

You Choose Your Availability: You're never assigned a session without your approval. You control when and where you work.

Location Visibility: Before any session, you'll see the exact address, client name, and type of environment (home, hotel, condo gym).

Discreet & Professional Brand: We emphasize wellness, not anything that invites inappropriate requests. We take misconduct seriously and immediately ban any client who crosses the line.

PROVIDER PROTECTIONS & SAFETY:
- You control your availability and approve all sessions
- See exact address, client name, environment type before accepting
- Right to request client ID verification from any client
- Immediate client ban for misconduct
- Post-session safety check-ins via text
- Professional wellness brand that deters inappropriate requests

IMPORTANT CLARIFICATIONS:
- Gold Touch does NOT provide clients or guarantee bookings to providers
- We are a booking platform - clients find and book services through our website
- Your bookings depend on client demand, your availability, and service quality
- We handle marketing the platform, but individual provider success varies

WHEN PROVIDERS SAY "I NEED CLIENTS":
Respond with: "We are growing every day and doing our best to get you as many clients as we can. We're constantly working on marketing the platform to bring in more bookings for all our providers."

WHEN PROVIDERS REPORT CLIENT CANCELLATIONS:
Respond with: "Sorry about the cancellation - we know that's disappointing when you've set aside the time. If you need to discuss anything about the booking, feel free to contact goldtouchmobile.com/contact-us."

WHEN PROVIDERS ASK "WHERE IS THIS?" OR ABOUT MISSING BOOKING INFORMATION:
Respond with: "It looks like the customer may have entered incomplete booking information (missing address or selected 'at therapist location'). Please accept the booking with Y, then ask the client directly for the correct address and any missing details."

WHAT WE DON'T OFFER:
- Client referrals or leads to individual providers
- Guaranteed minimum bookings or income
- Marketing services for individual providers
- Real-time client matching or assignment

TONE: Be supportive and professional. Providers are your partners. Keep responses concise for SMS. Be honest about what Gold Touch does and doesn't provide. Always direct complex issues to goldtouchmobile.com/contact-us.

If you cannot answer a provider question, direct them to goldtouchmobile.com/contact-us for support."""
        else:
            # Customer-specific knowledge base
            system_prompt = """You are a helpful customer support agent for Gold Touch Mobile Massage, a professional massage service. 

CUSTOMER INFORMATION:
- Payment: We accept Zelle payments to goldtouchmassage1@gmail.com
- Service Areas: All of Florida
- Services: Mobile massage (we come to you) and In-Studio massage
- Pricing: Visit goldtouchmobile.com for current pricing and booking
- Booking: Customers book through goldtouchmobile.com
- Response Time: Providers have 15 minutes to respond to booking requests

CUSTOMER COMMON QUESTIONS & ANSWERS:
- Zelle payment: Send to goldtouchmassage1@gmail.com
- Cancellation: Contact us ASAP, preferably 2+ hours before appointment
- Rescheduling: Text us and we'll help find a new time
- Provider didn't show: We'll immediately find a replacement and may offer compensation
- Service quality issues: We take this seriously and will make it right
- Booking changes: We can modify time, location, or service type if provider agrees
- Tipping: Optional but appreciated, typically 15-20%
- What to prepare: Clean towels, comfortable space, parking for provider
- Booking confirmation: You'll receive SMS confirmation when provider accepts
- $15 Discount: YES, we do offer a $15 discount for your next massage when your original provider isn't available

TONE: Be friendly, professional, and helpful. Keep responses concise (under 160 characters when possible for SMS). Always try to resolve issues or direct them to contact goldtouchmassage1@gmail.com for complex matters.

If you cannot answer a question, direct them to email goldtouchmassage1@gmail.com or call our support line."""

        # Use OpenAI legacy format (compatible with 0.28.1)
        openai.api_key = OPENAI_API_KEY
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Message: {message}"}
            ],
            max_tokens=150,
            temperature=0.7
        )
        
        ai_response = response.choices[0].message.content.strip()
        user_type = "provider" if is_provider else "customer"
        print(f"AI generated {user_type} response for '{message}': {ai_response}")
        return ai_response
        
    except Exception as e:
        print(f"Error generating AI response: {str(e)}")
        return None

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
        
        # Check database connection with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with app.app_context():
                    from sqlalchemy import text
                    db.session.execute(text('SELECT 1'))
                    print("Database connection successful")
                    break
            except Exception as e:
                error_msg = f"Database connection error (attempt {attempt + 1}/{max_retries}): {str(e)}"
                print(f"DATABASE ERROR: {error_msg}")
                
                if attempt == max_retries - 1:
                    # Last attempt failed, return error
                    return jsonify({
                        "status": "error", 
                        "message": "Database connection failed after multiple attempts",
                        "details": str(e)
                    }), 500
                else:
                    # Wait before retry
                    import time
                    time.sleep(1)
        
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
                appointment_dt_naive = datetime.strptime(data['datetime'], '%m/%d/%Y %I:%M %p')
            except ValueError:
                # Fall back to ISO format if AM/PM format fails
                appointment_dt_naive = datetime.fromisoformat(data['datetime'])
            
            # Convert appointment time from Eastern Time to UTC for proper comparison
            et = pytz.timezone('US/Eastern')
            appointment_dt_et = et.localize(appointment_dt_naive)
            appointment_dt = appointment_dt_et.astimezone(pytz.UTC)
                
            # Calculate response deadline (15 minutes from now) - make it timezone aware
            utc = pytz.UTC
            current_time = datetime.utcnow()
            current_time_utc = utc.localize(current_time)
            response_deadline = current_time_utc + timedelta(minutes=15)
            
            # Check if this is a last-minute booking (appointment within 1 hour)
            # Both times are now in UTC for proper comparison
            time_until_appointment = appointment_dt - current_time_utc
            is_last_minute = time_until_appointment <= timedelta(hours=1)
            
            print(f"=== TIMEZONE DEBUG ===")
            print(f"Appointment time (naive): {appointment_dt_naive}")
            print(f"Appointment time (ET): {appointment_dt_et}")
            print(f"Appointment time (UTC): {appointment_dt}")
            print(f"Current time (UTC): {current_time_utc}")
            print(f"Time until appointment: {time_until_appointment}")
            print(f"Is last minute: {is_last_minute}")
            print("=====================")
            
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
                    add_ons=data.get('add', '') or data.get('Add-on / Specialty Treatments', '') or data.get('addon', '') or data.get('addons', ''),  # Store add-ons from multiple possible field names
                    address=data.get('address', ''),
                    appointment_time=appointment_dt,  # Now properly in UTC
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
            
            # Add add-ons line if present
            add_ons_text = (data.get('add', '') or data.get('Add-on / Specialty Treatments', '') or data.get('addon', '') or data.get('addons', '')).strip()
            add_ons_line = f"\nAdd-ons: {add_ons_text}" if add_ons_text else ""
            
            if is_in_studio:
                message = (
                    f"Gold Touch Mobile - Hey {provider['name']}, New Request: {data['service_type']} "
                    f"on {formatted_time}.{add_ons_line}{short_notice_line}"
                    f"\n\nReply Y to ACCEPT or N to DECLINE"
                )
            else:
                message = (
                    f"Gold Touch Mobile - Hey {provider['name']}, New Request: {data['service_type']} "
                    f"at {data['address']} on {formatted_time}.{add_ons_line}{short_notice_line}"
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
        appointment_time = format_appointment_time_et(booking.appointment_time)
        
        provider_message = (
            "✅ BOOKING CONFIRMED!\n\n"
            f"Customer: {customer_name} - {booking.customer_phone}\n\n"
            "Please contact the customer to arrange details."
        )
        
        success, msg = send_sms(provider['phone'], provider_message)
        if not success:
            print(f"Failed to send confirmation to provider: {msg}")
        
        # Send confirmation to customer
        add_ons_info = f"\nAdd-ons: {booking.add_ons}" if booking.add_ons and booking.add_ons.strip() else ""
        customer_message = (
            f"Gold Touch Mobile - Your booking with {provider_name} has been confirmed!\n\n"
            f"Service: {booking.service_type or 'Not specified'}{add_ons_info}\n"
            f"When: {appointment_time}\n"
            f"Address: {booking.address or 'Not specified'}\n\n"
            "The provider will contact you shortly."
        )
        
        success, msg = send_sms(booking.customer_phone, customer_message)
        if not success:
            print(f"Failed to send confirmation to customer: {msg}")
        
        add_ons_display = f"<p>Add-ons: {booking.add_ons}</p>" if booking.add_ons and booking.add_ons.strip() else ""
        return f"""
        <html>
        <head><title>Booking Confirmed</title></head>
        <body style="font-family: Arial; padding: 20px; text-align: center;">
            <h2>✅ Booking Confirmed!</h2>
            <p>Customer details have been sent to your phone.</p>
            <p>Customer: {customer_name} - {booking.customer_phone}</p>
            <p>Service: {booking.service_type}</p>
            {add_ons_display}
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
            "You can book with another provider here: goldtouchmobile.com\n\n"
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
        
        # Filter out iPhone reactions and similar automated responses
        reaction_keywords = ['loved', 'liked', 'disliked', 'laughed', 'emphasized', 'questioned']
        if any(keyword in text.lower() for keyword in reaction_keywords):
            print(f"Ignoring iPhone reaction: '{text}'")
            return jsonify({"status": "ok"}), 200
        
        # First, check if this message is from a provider with a pending booking
        provider_phone_normalized = from_number.replace('+', '').replace('-', '').replace(' ', '')
        
        # Find the most recent pending booking for this provider
        all_pending = Booking.query.filter_by(status='pending').order_by(Booking.created_at.desc()).all()
        
        provider_booking = None
        for b in all_pending:
            if hasattr(b, 'provider_phone') and b.provider_phone:
                booking_phone_normalized = clean_phone_number(b.provider_phone).replace('+', '').replace('-', '').replace(' ', '')
                
                if booking_phone_normalized == provider_phone_normalized:
                    # Add safety check: only process responses within 30 minutes of booking creation
                    time_since_booking = datetime.utcnow() - b.created_at
                    if time_since_booking.total_seconds() <= 1800:  # 30 minutes
                        provider_booking = b
                        print(f"✓ Found most recent booking for provider: {provider_booking.id} (created {time_since_booking.total_seconds():.0f}s ago)")
                        break
                    else:
                        print(f"⚠️ Booking {b.id} is too old ({time_since_booking.total_seconds():.0f}s), skipping")
        
        # Check if this is a provider Y/N response or a customer support message
        response_type = None
        is_provider_response = False
        
        if provider_booking:
            # This is from a provider with a pending booking
            if not provider_booking.provider_responded:
                # First response from provider - only accept Y/N
                if text.lower() in ['y', 'yes']:
                    response_type = 'y'
                    is_provider_response = True
                    print(f"✓ Provider's FIRST response is Y - accepting booking {provider_booking.id}")
                elif text.lower() in ['n', 'no']:
                    response_type = 'n'
                    is_provider_response = True
                    print(f"✓ Provider's FIRST response is N - rejecting booking {provider_booking.id}")
                else:
                    # Provider's first response is not Y/N - mark as responded and treat as support message
                    provider_booking.provider_responded = True
                    db.session.commit()
                    print(f"⚠️ Provider's FIRST response '{text}' is not Y/N - marking booking {provider_booking.id} as responded, treating as support message")
                    is_provider_response = False
            else:
                # Provider already responded - ignore any Y/N and treat as support message
                print(f"⚠️ Provider already responded to booking {provider_booking.id} - ignoring '{text}' and treating as support message")
                is_provider_response = False
        else:
            # Not from a provider with pending booking - check if it's Y/N (should be ignored)
            if text.lower() in ['y', 'yes', 'n', 'no']:
                print(f"⚠️ Received '{text}' from {from_number} but no pending booking found - ignoring Y/N response")
                return jsonify({"status": "ok"}), 200
            else:
                # Regular support message
                print(f"Message '{text}' is not a Y/N response - checking if it's a customer support request")
                is_provider_response = False
        
        if is_provider_response:
            # Handle provider Y/N responses - use the booking we already found
            booking = provider_booking
            
            # Mark that the provider has now responded
            booking.provider_responded = True
            db.session.commit()
        else:
            # Handle customer or unknown user support messages with AI
            # First check if this is a known provider asking a non-Y/N question
            is_known_provider = False
            provider_phone_normalized = from_number.replace('+', '').replace('-', '').replace(' ', '')
            
            # Check if this phone matches any provider in database
            all_providers = Provider.query.all()
            for provider in all_providers:
                if provider.phone:
                    provider_db_normalized = clean_phone_number(provider.phone).replace('+', '').replace('-', '').replace(' ', '')
                    if provider_db_normalized == provider_phone_normalized:
                        is_known_provider = True
                        print(f"✓ Recognized provider {provider.name} asking a question: '{text}'")
                        break
            
            if is_known_provider:
                # Check if this is a follow-up response (COMPLETED/ISSUE)
                if text.lower() in ['completed', 'issue']:
                    print(f"📋 Provider follow-up response: {text.upper()}")
                    
                    if text.lower() == 'completed':
                        response_message = "Thank you for confirming! Glad everything went smoothly."
                    else:  # 'issue'
                        response_message = "Thanks for letting us know. We'll follow up with you shortly to address any concerns."
                    
                    success, result = send_sms(from_number, response_message)
                    if success:
                        print(f"✓ Follow-up acknowledgment sent to provider")
                    else:
                        print(f"✗ Failed to send follow-up acknowledgment: {result}")
                else:
                    # Handle provider questions with AI (always respond to providers)
                    user_type = "provider"
                    print(f"Processing {user_type} support message from {from_number}: '{text}'")
                    
                    # Generate AI response for provider
                    ai_response = get_ai_support_response(text, from_number, is_provider=True)
                    
                    if ai_response:
                        print(f"Sending AI {user_type} response: {ai_response}")
                        success, result = send_sms(from_number, ai_response)
                        if success:
                            print(f"✓ AI {user_type} support response sent successfully")
                        else:
                            print(f"✗ Failed to send AI {user_type} response: {result}")
                    else:
                        print("AI response generation failed, sending fallback message")
                        fallback_message = "Thanks for contacting Gold Touch Mobile Massage! For provider support, please email goldtouchmobile.com"
                        send_sms(from_number, fallback_message)
            else:
                # Check if this is a verified customer (has made a booking)
                customer_phone_normalized = from_number.replace('+', '').replace('-', '').replace(' ', '')
                print(f"🔍 Checking if {from_number} (normalized: {customer_phone_normalized}) is a verified customer")
                
                # Look for any booking with this customer phone number (more efficient query)
                is_verified_customer = False
                try:
                    # Get all bookings for debugging
                    all_bookings = Booking.query.all()
                    print(f"📊 Total bookings in database: {len(all_bookings)}")
                    
                    for booking in all_bookings:
                        if booking.customer_phone:
                            booking_phone_normalized = clean_phone_number(booking.customer_phone).replace('+', '').replace('-', '').replace(' ', '')
                            print(f"📞 Comparing {customer_phone_normalized} with booking {booking.id} phone: {booking_phone_normalized}")
                            if booking_phone_normalized == customer_phone_normalized:
                                is_verified_customer = True
                                print(f"✅ MATCH! Recognized verified customer from booking {booking.id}: '{text}'")
                                break
                        else:
                            print(f"⚠️ Booking {booking.id} has no customer_phone")
                    
                    if not is_verified_customer:
                        print(f"❌ No matching booking found for {customer_phone_normalized}")
                        
                except Exception as e:
                    print(f"🚨 Error checking customer verification: {str(e)}")
                    is_verified_customer = False
                
                if is_verified_customer:
                    # Handle verified customer questions with AI
                    user_type = "customer"
                    print(f"Processing {user_type} support message from {from_number}: '{text}'")
                    
                    # Check if this is a cancellation/rescheduling request
                    is_cancellation_request = detect_cancellation_request(text)
                    
                    if is_cancellation_request:
                        print(f"🚨 Detected cancellation/rescheduling request from {from_number}")
                        
                        # Notify the provider
                        cancellation_sent = notify_provider_of_cancellation(from_number, text)
                        
                        # Send simple confirmation to customer regardless of provider notification status
                        customer_response = "Your massage has been cancelled. Thank you for letting us know."
                        
                        success, result = send_sms(from_number, customer_response)
                        if success:
                            print(f"✓ Cancellation confirmation sent to customer")
                        else:
                            print(f"✗ Failed to send cancellation confirmation: {result}")
                    else:
                        # Regular customer support with AI
                        ai_response = get_ai_support_response(text, from_number, is_provider=False)
                        
                        if ai_response:
                            print(f"Sending AI {user_type} response: {ai_response}")
                            success, result = send_sms(from_number, ai_response)
                            if success:
                                print(f"✓ AI {user_type} support response sent successfully")
                            else:
                                print(f"✗ Failed to send AI {user_type} response: {result}")
                        else:
                            print("AI response generation failed, sending fallback message")
                            fallback_message = "Thanks for contacting Gold Touch Mobile Massage! For immediate assistance, please email goldtouchmobile.com"
                            send_sms(from_number, fallback_message)
                else:
                    # Unknown/unverified number - check if we've already sent basic redirect
                    normalized_phone = clean_phone_number(from_number).replace('+', '').replace('-', '').replace(' ', '')
                    
                    # Check if we've already sent a basic redirect to this number
                    existing_redirect = MessageLog.query.filter_by(
                        phone_number=normalized_phone, 
                        message_type='basic_redirect'
                    ).first()
                    
                    if existing_redirect:
                        print(f"⚠️ Unknown number {from_number} already received basic redirect on {existing_redirect.created_at} - ignoring: '{text}'")
                    else:
                        # Send basic booking redirect message (first time only)
                        print(f"⚠️ Unknown number {from_number} - sending first-time basic booking redirect: '{text}'")
                        basic_message = "Hi! Please visit goldtouchmobile.com to book your massage appointment."
                        
                        success, result = send_sms(from_number, basic_message)
                        if success:
                            # Log that we sent the basic redirect
                            message_log = MessageLog(
                                phone_number=normalized_phone,
                                message_type='basic_redirect',
                                message_content=basic_message
                            )
                            db.session.add(message_log)
                            db.session.commit()
                            print(f"✓ Basic booking redirect sent to unknown number and logged")
                        else:
                            print(f"✗ Failed to send basic redirect: {result}")
            
            return jsonify({"status": "ok"}), 200
        
        # Get provider info
        provider = get_provider(booking.provider_id)
        
        # Process Y/N response
        if response_type == 'y':
            print(f"Processing CONFIRMATION for booking {booking.id}")
            
            # Update booking status
            booking.status = 'confirmed'
            booking.updated_at = datetime.utcnow()
            db.session.commit()
            
            # Get customer name
            customer_name = getattr(booking, 'customer_name', '')
            appointment_time = format_appointment_time_et(booking.appointment_time)
            
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
            
            # Call Stripe checkout when provider accepts
            payment_link = None
            try:
                import requests
                
                # Get provider name for Stripe payload
                provider_name = provider.get('name', 'Provider') if provider else 'Provider'
                
                # Use service name for dynamic pricing lookup (Stripe service will find correct price)
                service_type = booking.service_type or 'Service'
                
                stripe_payload = {
                    'providerId': booking.provider_id,
                    'serviceName': service_type,  # Let Stripe service look up pricing
                    'customerPhone': booking.customer_phone,
                    'customerName': customer_name or 'Customer',
                    'providerName': provider_name
                    # Removed amountCents - let Stripe service calculate from serviceName
                }
                
                print(f"=== CALLING STRIPE CHECKOUT ===")
                print(f"Stripe payload: {stripe_payload}")
                
                # Use regular checkout with fuzzy matching for service names
                stripe_response = requests.post(
                    'https://stripe-45lh.onrender.com/checkout',
                    json=stripe_payload,
                    timeout=10
                )
                
                if stripe_response.status_code == 200:
                    print(f"✓ Stripe checkout initiated successfully")
                    print(f"Stripe response: {stripe_response.text}")
                    
                    # Try to extract payment link from response
                    try:
                        stripe_data = stripe_response.json()
                        payment_link = stripe_data.get('checkout_url') or stripe_data.get('payment_link') or stripe_data.get('url')
                        if payment_link:
                            print(f"✓ Payment link received: {payment_link}")
                        else:
                            print(f"⚠️ No payment link found in Stripe response")
                    except Exception as json_error:
                        print(f"⚠️ Could not parse Stripe response as JSON: {json_error}")
                else:
                    print(f"✗ Stripe checkout failed: {stripe_response.status_code} - {stripe_response.text}")
                    
            except Exception as stripe_error:
                print(f"✗ Error calling Stripe checkout: {str(stripe_error)}")
            
            # Send confirmation to customer with payment link if available
            provider_name = provider.get('name', 'the provider') if provider else 'the provider'
            add_ons_info = f"\nAdd-ons: {booking.add_ons}" if booking.add_ons and booking.add_ons.strip() else ""
            
            # Add payment link to message if available
            payment_info = f"\n\n💳 Pay after your service: {payment_link}" if payment_link else "\n\nPayment details will be sent separately."
            
            customer_message = (
                f"Gold Touch Mobile - Your booking with {provider_name} has been confirmed!\n\n"
                f"Service: {booking.service_type or 'Not specified'}{add_ons_info}\n"
                f"When: {appointment_time}\n"
                f"Address: {booking.address or 'Not specified'}\n\n"
                f"The provider will contact you shortly."
                f"{payment_info}"  # ✅ NOW INCLUDES THE PAYMENT LINK!
            )
            
            success, msg = send_sms(booking.customer_phone, customer_message)
            if success:
                print(f"✓ Successfully sent confirmation to customer: {msg}")
            else:
                print(f"✗ FAILED to send confirmation to customer: {msg}")
            
            print(f"Booking {booking.id} confirmed successfully")
            
        elif response_type == 'n':
            print(f"Processing REJECTION for booking {booking.id}")
            
            # Update booking status
            booking.status = 'rejected'
            booking.updated_at = datetime.utcnow()
            db.session.commit()
            
            # Send rejection message to customer
            alt_message = (
                "The provider you selected isn't available at this time, but you can easily choose another provider here: https://goldtouchmobile.com. "
                "We appreciate your understanding and look forward to serving you."
            )
            success, msg = send_sms(booking.customer_phone, alt_message)
            if not success:
                print(f"Failed to send rejection to customer: {msg}")
            
            print(f"Booking {booking.id} rejected successfully")
        else:
            print(f"Unexpected response type: '{response_type}'. This should not happen.")
        
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

@app.route('/check-customer/<phone>', methods=['GET'])
def check_customer_status(phone):
    """Check if a phone number is recognized as a verified customer"""
    try:
        # Normalize the phone number
        normalized_phone = clean_phone_number(phone).replace('+', '').replace('-', '').replace(' ', '')
        
        # Get all bookings
        all_bookings = Booking.query.all()
        matching_bookings = []
        
        for booking in all_bookings:
            if booking.customer_phone:
                booking_phone_normalized = clean_phone_number(booking.customer_phone).replace('+', '').replace('-', '').replace(' ', '')
                if booking_phone_normalized == normalized_phone:
                    matching_bookings.append({
                        'booking_id': booking.id,
                        'customer_phone': booking.customer_phone,
                        'status': booking.status,
                        'created_at': booking.created_at.isoformat()
                    })
        
        return jsonify({
            'phone_input': phone,
            'normalized_phone': normalized_phone,
            'is_verified_customer': len(matching_bookings) > 0,
            'matching_bookings': matching_bookings,
            'total_bookings_in_db': len(all_bookings)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/providers', methods=['GET'])
@app.route('/providers/', methods=['GET'])
def list_providers():
    """List all providers - redirect to management interface"""
    return redirect(url_for('manage_providers'))

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
            return f"""
            <html>
            <head><title>Error</title></head>
            <body style="font-family: Arial; padding: 20px;">
                <h2>❌ Error</h2>
                <p>Missing required fields. Please fill in all fields.</p>
                <p><a href="/providers/add">Try Again</a> | <a href="/providers/manage">Back to Manage</a></p>
            </body>
            </html>
            """
        
        # Check if provider already exists
        existing_provider = Provider.query.get(provider_id)
        if existing_provider:
            return f"""
            <html>
            <head><title>Error</title></head>
            <body style="font-family: Arial; padding: 20px;">
                <h2>❌ Error</h2>
                <p>Provider with ID '{provider_id}' already exists.</p>
                <p><a href="/providers/add">Try Again</a> | <a href="/providers/manage">Back to Manage</a></p>
            </body>
            </html>
            """
        
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
        return f"""
        <html>
        <head><title>Database Error</title></head>
        <body style="font-family: Arial; padding: 20px;">
            <h2>⚠️ Database Connection Issue</h2>
            <p>Unable to add provider due to database connection problems.</p>
            <p><strong>Error:</strong> {str(e)[:200]}...</p>
            <p>Please try again later when the database connection is restored.</p>
            <p><a href="/providers/add">Try Again</a> | <a href="/providers/manage">Back to Manage</a></p>
        </body>
        </html>
        """

@app.route('/providers/manage', methods=['GET'])
def manage_providers():
    """Provider management interface"""
    try:
        providers = Provider.query.all()
        provider_rows = ""
        for provider in providers:
            # URL encode the provider ID to handle spaces and special characters
            from urllib.parse import quote
            encoded_id = quote(provider.id.strip())
            provider_rows += f"""
            <tr>
                <td>{provider.id}</td>
                <td>{provider.name}</td>
                <td>{provider.phone}</td>
                <td>
                    <a href="/providers/edit/{encoded_id}" style="color: #007cba;">Edit</a> | 
                    <a href="/providers/delete/{encoded_id}" style="color: #d63384;" onclick="return confirm('Delete {provider.name}?')">Delete</a>
                </td>
            </tr>
            """
        db_status = f"✅ Database connected - {len(providers)} providers found"
        db_color = "#d4edda"
        
    except Exception as e:
        # Database connection failed - show interface anyway
        provider_rows = """
        <tr>
            <td colspan="4" style="text-align: center; padding: 20px; color: #856404; background: #fff3cd;">
                Database temporarily unavailable. Provider data will load when connection is restored.
            </td>
        </tr>
        """
        db_status = f"⚠️ Database connection issue: {str(e)[:100]}..."
        db_color = "#f8d7da"
    
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
        
        <div style="margin-top: 30px; padding: 15px; background: {db_color}; border-radius: 5px;">
            <h3>Database Status</h3>
            <p>{db_status}</p>
            <p><small>Providers are stored in the database and changes persist across deployments.</small></p>
        </div>
    </body>
    </html>
    """

@app.route('/providers/edit/<provider_id>', methods=['GET', 'POST'])
def edit_provider(provider_id):
    """Edit an existing provider"""
    try:
        # URL decode the provider ID to handle spaces and special characters
        from urllib.parse import unquote
        decoded_id = unquote(provider_id)
        
        # Debug: Show what we're looking for and what exists
        all_providers = Provider.query.all()
        provider_ids = [p.id for p in all_providers]
        print(f"DEBUG: URL provider_id: '{provider_id}'")
        print(f"DEBUG: Decoded provider_id: '{decoded_id}'")
        print(f"DEBUG: Available provider IDs: {provider_ids}")
        
        # Query provider directly - try exact match first, then with trailing space
        provider = Provider.query.get(decoded_id)
        if not provider:
            # Try with trailing space
            provider = Provider.query.get(decoded_id + ' ')
        if not provider:
            # Try trimming spaces from database IDs
            all_providers_exact = Provider.query.all()
            for p in all_providers_exact:
                if p.id.strip() == decoded_id.strip():
                    provider = p
                    break
        
        if not provider:
            return f"""
            <html>
            <head><title>Provider Not Found</title></head>
            <body style="font-family: Arial; padding: 20px;">
                <h2>❌ Provider Not Found</h2>
                <p><strong>Looking for:</strong> '{provider_id}'</p>
                <p><strong>Available providers:</strong> {', '.join(provider_ids) if provider_ids else 'None'}</p>
                <p><a href="/providers/manage">Back to Manage Providers</a></p>
            </body>
            </html>
            """
        
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
        # URL decode the provider ID to handle spaces and special characters
        from urllib.parse import unquote
        decoded_id = unquote(provider_id)
        
        # Debug: Show what we're looking for and what exists
        all_providers = Provider.query.all()
        provider_ids = [p.id for p in all_providers]
        print(f"DEBUG DELETE: URL provider_id: '{provider_id}'")
        print(f"DEBUG DELETE: Decoded provider_id: '{decoded_id}'")
        print(f"DEBUG DELETE: Available provider IDs: {provider_ids}")
        
        # Query provider directly - try exact match first, then with trailing space
        provider = Provider.query.filter_by(id=decoded_id).first()
        if not provider:
            # Try with trailing space
            provider = Provider.query.filter_by(id=decoded_id + ' ').first()
        if not provider:
            # Try trimming spaces from database IDs
            all_providers_exact = Provider.query.all()
            for p in all_providers_exact:
                if p.id.strip() == decoded_id.strip():
                    provider = p
                    break
        
        if not provider:
            return f"""
            <html>
            <head><title>Provider Not Found</title></head>
            <body style="font-family: Arial; padding: 20px;">
                <h2>❌ Provider Not Found</h2>
                <p><strong>Looking for:</strong> '{provider_id}'</p>
                <p><strong>Available providers:</strong> {', '.join(provider_ids) if provider_ids else 'None'}</p>
                <p><a href="/providers/manage">Back to Manage Providers</a></p>
            </body>
            </html>
            """
        
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
        print(f"Error deleting provider: {str(e)}")
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
        appointment_time = format_appointment_time_et(booking.appointment_time)
        
        add_ons_info = f"\nAdd-ons: {booking.add_ons}" if booking.add_ons and booking.add_ons.strip() else ""
        
        provider_message = (
            "You've confirmed the booking! The customer has been notified.\n\n"
            f"Customer: {getattr(booking, 'customer_name', '')} - {booking.customer_phone}\n"
            f"Service: {booking.service_type}{add_ons_info}\n"
            f"When: {appointment_time}\n"
            f"Address: {booking.address or 'Not specified'}"
        )
        
        customer_message = (
            f"Gold Touch Mobile - Your booking with {provider_name} has been confirmed!\n\n"
            f"Service: {booking.service_type or 'Not specified'}{add_ons_info}\n"
            f"When: {appointment_time}\n"
            f"Address: {booking.address or 'Not specified'}\n\n"
            "Thank you for choosing our service!"
        )
        
        return jsonify({
            "status": "success",
            "message": f"Debug webhook processed for booking {booking.id}",
            "booking_id": booking.id,
            "provider_message": provider_message,
            "customer_message": customer_message,
            "response_format": {
                "accept": "Y",
                "decline": "N",
                "note": "Simple Y/N responses - uses timestamp-based matching"
            },
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

def send_followup_messages():
    """Background task to send follow-up messages 30 minutes after confirmed bookings"""
    with app.app_context():
        try:
            # Check if provider_responded column exists before proceeding
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('bookings')]
            
            if 'provider_responded' not in columns:
                print("⚠️ provider_responded column not found - skipping follow-up messages. Please run migration at /migrate-provider-responded")
                return
            
            now = datetime.utcnow()
            
            # Look for confirmed bookings from the last 24 hours that need follow-up
            cutoff_time = now - timedelta(hours=24)
            
            # Get all confirmed bookings that might need follow-up
            potential_bookings = Booking.query.filter(
                Booking.status == 'confirmed',
                Booking.appointment_time >= cutoff_time,    # Appointment within last 24 hours
                Booking.created_at >= cutoff_time           # Only recent bookings
            ).all()
            
            bookings_needing_followup = []
            for booking in potential_bookings:
                # Extract session duration from service_type
                service_duration = 60  # Default to 60 minutes
                if booking.service_type and '90 min' in booking.service_type:
                    service_duration = 90
                elif booking.service_type and '60 min' in booking.service_type:
                    service_duration = 60
                elif booking.service_type and '45 min' in booking.service_type:
                    service_duration = 45
                elif booking.service_type and '30 min' in booking.service_type:
                    service_duration = 30
                
                # Calculate when follow-up should be sent: appointment_time + session_duration + 30 min buffer
                followup_send_time = booking.appointment_time + timedelta(minutes=service_duration + 30)
                
                # Check if it's time to send follow-up (appointment completed + 30 min buffer has passed)
                if now >= followup_send_time:
                    bookings_needing_followup.append(booking)
            
            for booking in bookings_needing_followup:
                try:
                    # Check if we've already sent follow-up for this booking
                    existing_followup = MessageLog.query.filter_by(
                        phone_number=clean_phone_number(booking.customer_phone).replace('+', '').replace('-', '').replace(' ', ''),
                        message_type=f'followup_booking_{booking.id}'
                    ).first()
                    
                    if existing_followup:
                        continue  # Already sent follow-up for this booking
                    
                    # Get provider info
                    provider = get_provider(booking.provider_id)
                    if not provider:
                        print(f"⚠️ Provider not found for booking {booking.id}")
                        continue
                    
                    customer_name = getattr(booking, 'customer_name', '') or 'Customer'
                    provider_name = provider.get('name', 'your provider')
                    
                    # Send follow-up to customer
                    customer_message = (
                        f"Hi! How was your massage with {provider_name}? "
                        f"We'd love to hear about your experience - please leave us a review on Google: "
                        f"https://g.page/r/Cdv1UlWh_ZPLEAE/review"
                    )
                    
                    customer_success, customer_result = send_sms(booking.customer_phone, customer_message)
                    if customer_success:
                        print(f"✓ Follow-up sent to customer for booking {booking.id}")
                    else:
                        print(f"✗ Failed to send follow-up to customer: {customer_result}")
                    
                    # Send follow-up to provider
                    provider_message = (
                        f"Hi {provider_name}! How did the appointment with {customer_name} go? "
                        f"Please reply with: COMPLETED if everything went smoothly, or ISSUE if there were any problems. Thanks!"
                    )
                    
                    provider_success, provider_result = send_sms(provider['phone'], provider_message)
                    if provider_success:
                        print(f"✓ Follow-up sent to provider for booking {booking.id}")
                    else:
                        print(f"✗ Failed to send follow-up to provider: {provider_result}")
                    
                    # Log that we sent follow-up messages
                    if customer_success or provider_success:
                        normalized_customer_phone = clean_phone_number(booking.customer_phone).replace('+', '').replace('-', '').replace(' ', '')
                        followup_log = MessageLog(
                            phone_number=normalized_customer_phone,
                            message_type=f'followup_booking_{booking.id}',
                            message_content=f'Follow-up sent for booking {booking.id}'
                        )
                        db.session.add(followup_log)
                        db.session.commit()
                        
                        print(f"✓ Follow-up messages sent for booking {booking.id}")
                    
                except Exception as e:
                    print(f"Error sending follow-up for booking {booking.id}: {str(e)}")
                    
        except Exception as e:
            print(f"Error in send_followup_messages: {str(e)}")

def check_expired_bookings():
    """Background task to check for and handle expired bookings"""
    with app.app_context():
        try:
            # Check if provider_responded column exists before proceeding
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('bookings')]
            
            if 'provider_responded' not in columns:
                print("⚠️ provider_responded column not found - skipping expired bookings check. Please run migration at /migrate-provider-responded")
                return
            
            now = datetime.utcnow()
            # Only check bookings from the last 24 hours to prevent processing old bookings
            cutoff_time = now - timedelta(hours=24)
            
            expired_bookings = Booking.query.filter(
                Booking.status == 'pending',
                Booking.response_deadline <= now,
                Booking.created_at >= cutoff_time  # Only recent bookings
            ).all()
            
            for booking in expired_bookings:
                try:
                    # Update booking status
                    booking.status = 'expired'
                    booking.updated_at = datetime.utcnow()
                    db.session.commit()
                    
                    # Notify customer with same message as rejection
                    alt_message = (
                        "The provider you selected isn't available at this time, but you can easily choose another provider here: goldtouchmobile.com. "
                        "We appreciate your understanding and look forward to serving you."
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
    scheduler.add_job(
        func=send_followup_messages,
        trigger='interval',
        minutes=5,  # Check every 5 minutes for follow-ups
        id='followup_messages_check',
        name='Send follow-up messages',
        replace_existing=True
    )
    scheduler.start()
    return scheduler

# Start background tasks for production (after function is defined)
try:
    scheduler = start_background_tasks()
    print("Background tasks started successfully - checking for expired bookings every minute")
except Exception as e:
    print(f"Warning: Could not start background tasks: {e}")
    scheduler = None

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

@app.route('/migrate-add-ons', methods=['GET'])
def migrate_add_ons_endpoint():
    """Web endpoint to add the add_ons column to bookings table"""
    try:
        # Check if the column already exists
        from sqlalchemy import text, inspect
        
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('bookings')]
        
        if 'add_ons' in columns:
            return jsonify({
                "status": "success",
                "message": "add_ons column already exists",
                "columns": columns
            })
        
        # Add the column
        alter_query = text("""
            ALTER TABLE bookings 
            ADD COLUMN add_ons TEXT;
        """)
        
        db.session.execute(alter_query)
        db.session.commit()
        
        # Verify the column was added
        verify_result = db.session.execute(check_query)
        if verify_result.fetchone():
            return jsonify({
                "status": "success",
                "message": "Successfully added add_ons column to bookings table",
                "action": "column_added"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Migration verification failed",
                "action": "verification_failed"
            }), 500
            
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Migration failed: {str(e)}",
            "type": type(e).__name__
        }), 500

@app.route('/migrate-provider-responded', methods=['GET'])
def migrate_provider_responded_endpoint():
    """Web endpoint to add the provider_responded column to bookings table"""
    try:
        # Check if the column already exists
        from sqlalchemy import text, inspect
        
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('bookings')]
        
        if 'provider_responded' in columns:
            return jsonify({
                "status": "success",
                "message": "provider_responded column already exists",
                "columns": columns
            })
        
        # Add the column with default value False
        db.session.execute(text('ALTER TABLE bookings ADD COLUMN provider_responded BOOLEAN DEFAULT FALSE'))
        
        # Update existing bookings based on their status
        # If booking is confirmed or rejected, provider must have responded
        db.session.execute(text("""
            UPDATE bookings 
            SET provider_responded = TRUE 
            WHERE status IN ('confirmed', 'rejected')
        """))
        
        db.session.commit()
        
        # Verify the migration
        result = db.session.execute(text("SELECT COUNT(*) FROM bookings WHERE provider_responded = TRUE")).fetchone()
        updated_count = result[0] if result else 0
        
        # Verify the column was added
        inspector = inspect(db.engine)
        new_columns = [col['name'] for col in inspector.get_columns('bookings')]
        
        return jsonify({
            "status": "success",
            "message": "provider_responded column added successfully",
            "columns_before": columns,
            "columns_after": new_columns,
            "updated_bookings": updated_count,
            "note": "Existing confirmed/rejected bookings marked as provider_responded=TRUE"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

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

@app.route('/cleanup-old-bookings', methods=['GET'])
def cleanup_old_bookings():
    """Manually clean up old pending bookings without sending SMS"""
    try:
        now = datetime.utcnow()
        # Mark all old pending bookings as expired without SMS
        cutoff_time = now - timedelta(hours=1)  # Older than 1 hour
        
        old_bookings = Booking.query.filter(
            Booking.status == 'pending',
            Booking.created_at < cutoff_time
        ).all()
        
        updated_count = 0
        for booking in old_bookings:
            booking.status = 'expired'
            booking.updated_at = now
            updated_count += 1
        
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Cleaned up {updated_count} old pending bookings",
            "updated_count": updated_count
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": f"Error cleaning up bookings: {str(e)}"
        }), 500

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
                "The provider you selected isn't available at this time, but you can easily choose another provider here: goldtouchmobile.com. "
                "We appreciate your understanding and look forward to serving you."
            )
        elif scenario == 'timeout':
            message = (
                "We're sorry, but the provider hasn't responded to your booking request. "
                "We're working to find you an alternative provider. "
                "You can also book with another provider here: goldtouchmobile.com.\n\n"
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

@app.route('/test-ai-support', methods=['GET', 'POST'])
def test_ai_support():
    """Test endpoint for AI customer and provider support"""
    try:
        if request.method == 'GET':
            # Show test form
            return """
            <html>
            <head><title>Test AI Support System</title></head>
            <body style="font-family: Arial; padding: 20px;">
                <h2>🤖 Test AI Support System</h2>
                <form method="POST">
                    <p>
                        <label>Message:</label><br>
                        <textarea name="message" placeholder="What's your Zelle info?" rows="3" cols="50" required></textarea>
                    </p>
                    <p>
                        <label>Phone (optional):</label><br>
                        <input type="text" name="phone" placeholder="+1234567890">
                    </p>
                    <p>
                        <label>User Type:</label><br>
                        <input type="radio" name="user_type" value="customer" checked> Customer<br>
                        <input type="radio" name="user_type" value="provider"> Provider
                    </p>
                    <p>
                        <button type="submit">Get AI Response</button>
                    </p>
                </form>
                
                <div style="display: flex; gap: 30px;">
                    <div>
                        <h3>Customer Test Messages:</h3>
                        <ul>
                            <li>"What's your Zelle info?"</li>
                            <li>"How do I cancel my appointment?"</li>
                            <li>"My provider didn't show up"</li>
                            <li>"What should I prepare for the massage?"</li>
                            <li>"How much should I tip?"</li>
                        </ul>
                    </div>
                    <div>
                        <h3>Provider Test Messages:</h3>
                        <ul>
                            <li>"What's the business Zelle for customers?"</li>
                            <li>"Can I accept cash from customers?"</li>
                            <li>"Customer wants to pay me directly, is that ok?"</li>
                            <li>"How much do I earn per booking?"</li>
                            <li>"Customer didn't show up, what now?"</li>
                            <li>"When will I get paid?"</li>
                        </ul>
                    </div>
                </div>
            </body>
            </html>
            """
        
        # Handle POST request
        data = request.get_json()
        message = data.get('message', '')
        is_provider = data.get('is_provider', False)
        phone = data.get('phone', '+15551234567')
        
        if not message:
            return jsonify({
                "error": "Message is required"
            }), 400
        
        # Generate AI response
        ai_response = get_ai_support_response(message, phone, is_provider)
        
        return jsonify({
            "status": "success",
            "input": {
                "message": message,
                "is_provider": is_provider,
                "phone": phone
            },
            "ai_response": ai_response,
            "openai_configured": bool(OPENAI_API_KEY),
            "test_info": {
                "note": "This tests the AI response generation without sending SMS",
                "to_send_sms": "Use the actual webhook or phone number"
            }
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error",
            "type": type(e).__name__
        }), 500

@app.route('/register-provider', methods=['GET', 'POST'])
def register_provider():
    """Endpoint to automatically register a new provider from onboarding form"""
    
    # Handle GET request for testing
    if request.method == 'GET':
        return jsonify({
            "message": "register-provider endpoint is working",
            "method": "GET",
            "note": "Use POST with name and phone to register a provider",
            "test_form": {
                "url": "/register-provider",
                "method": "POST",
                "fields": ["name", "phone"]
            },
            "textmagic_configured": bool(TEXTMAGIC_USERNAME and TEXTMAGIC_API_KEY)
        })
    
    # Handle POST request for actual registration
    try:
        # Log the incoming request for debugging
        print(f"\n🚀 REGISTER-PROVIDER ENDPOINT CALLED!")
        print(f"=== PROVIDER REGISTRATION REQUEST ===")
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        print(f"Content-Type: {request.content_type}")
        print(f"Is JSON: {request.is_json}")
        print(f"Form data: {dict(request.form)}")
        print(f"Raw data: {request.get_data()}")
        print(f"Request method: {request.method}")
        print(f"Request URL: {request.url}")
        print(f"Request headers: {dict(request.headers)}")
        
        # Get data from either JSON or form data
        if request.is_json:
            data = request.get_json()
            print(f"JSON data: {data}")
        else:
            # Handle form data (application/x-www-form-urlencoded)
            data = request.form.to_dict()
            print(f"Form data parsed: {data}")
        
        if not data:
            print("❌ No data provided")
            return jsonify({
                "status": "error",
                "message": "No data provided"
            }), 400
        
        # Handle both lowercase and capitalized field names
        provider_name = (data.get('name') or data.get('Name') or '').strip()
        provider_phone = (data.get('phone') or data.get('Phone') or '').strip()
        
        # Validate required fields
        print(f"Provider name: '{provider_name}'")
        print(f"Provider phone: '{provider_phone}'")
        
        if not provider_name:
            print("❌ Provider name is missing")
            return jsonify({
                "status": "error",
                "message": "Provider name is required"
            }), 400
        
        if not provider_phone:
            print("❌ Provider phone is missing")
            return jsonify({
                "status": "error",
                "message": "Provider phone number is required"
            }), 400
        
        # Clean phone number
        cleaned_phone = clean_phone_number_for_registration(provider_phone)
        if not cleaned_phone:
            return jsonify({
                "status": "error",
                "message": "Invalid phone number format"
            }), 400
        
        # Check if phone number already exists
        existing_provider = Provider.query.filter_by(phone=cleaned_phone).first()
        if existing_provider:
            return jsonify({
                "status": "error",
                "message": f"Provider with phone {cleaned_phone} already exists",
                "existing_provider_id": existing_provider.id
            }), 409
        
        # Generate next provider ID
        provider_id = generate_next_provider_id()
        
        # Create new provider
        new_provider = Provider(
            id=provider_id,
            name=provider_name,
            phone=cleaned_phone
        )
        
        db.session.add(new_provider)
        db.session.commit()
        
        print(f" New provider registered: {provider_id} - {provider_name} ({cleaned_phone})")
        
        # Send welcome SMS to new provider with comprehensive debugging
        print(f"\n=== WELCOME SMS DEBUGGING ===")
        print(f" Target: {provider_name} at {cleaned_phone}")
        print(f" Provider ID: {provider_id}")
        
        # Check TextMagic credentials before attempting SMS
        print(f" SMS Configuration Check:")
        print(f"  - TEXTMAGIC_USERNAME: {' Set' if TEXTMAGIC_USERNAME else 'Missing'}")
        print(f"  - TEXTMAGIC_API_KEY: {' Set' if TEXTMAGIC_API_KEY else 'Missing'}")
        print(f"  - TEXTMAGIC_FROM_NUMBER: {TEXTMAGIC_FROM_NUMBER if TEXTMAGIC_FROM_NUMBER else 'Missing'}")
        
        if not TEXTMAGIC_USERNAME or not TEXTMAGIC_API_KEY:
            print(" CRITICAL: TextMagic credentials not configured - SMS will fail")
            sms_success = False
            sms_result = "TextMagic credentials not configured"
        else:
            # Create welcome message
            welcome_message = (
                f"🎉 Welcome to Gold Touch, {provider_name}!\n\n"
                f"You're now part of our provider network. No action needed right now.\n\n"
                f"HOW IT WORKS:\n"
                f"• When booking requests come in, you'll get a separate SMS\n"
                f"• Reply Y to accept or N to decline those future requests\n"
                f"• You'll have 15 minutes to respond to each booking request\n"
                f"• Feel free to ask me anything! I'm here to help.\n"
                f"• For system errors, contact: 954-614-4683\n\n"
                f"This is an automated AI assistant welcoming you aboard!"
            )
            
            print(f" Welcome message created:")
            print(f"  - Length: {len(welcome_message)} characters")
            print(f"  - Content preview: {welcome_message[:100]}...")
            
            # Validate phone number format
            if not cleaned_phone or not cleaned_phone.startswith('+'):
                print(f" Invalid phone format: '{cleaned_phone}'")
                sms_success = False
                sms_result = f"Invalid phone number format: {cleaned_phone}"
            else:
                print(f" Phone number format valid: {cleaned_phone}")
                
                # Attempt to send SMS with detailed logging
                print(f" Attempting to send welcome SMS...")
                try:
                    sms_success, sms_result = send_sms(cleaned_phone, welcome_message)
                    
                    print(f" SMS Send Result:")
                    print(f"  - Success: {sms_success}")
                    print(f"  - Result: {sms_result}")
                    
                    if sms_success:
                        print(f" Welcome SMS sent successfully to {provider_name}")
                        print(f"   Phone: {cleaned_phone}")
                        print(f"   Provider: {provider_id}")
                    else:
                        print(f" Failed to send welcome SMS to {provider_name}")
                        print(f"   Phone: {cleaned_phone}")
                        print(f"   Error: {sms_result}")
                        print(f"   Possible causes:")
                        print(f"     - Invalid phone number format")
                        print(f"     - TextMagic API issues")
                        print(f"     - Network connectivity problems")
                        print(f"     - TextMagic account balance/limits")
                        
                except Exception as sms_error:
                    print(f" EXCEPTION during SMS send:")
                    print(f"   Error type: {type(sms_error).__name__}")
                    print(f"   Error message: {str(sms_error)}")
                    print(f"   Provider: {provider_name} ({cleaned_phone})")
                    sms_success = False
                    sms_result = f"Exception during SMS send: {str(sms_error)}"
        
        print(f"=== WELCOME SMS DEBUGGING END ===\n")
        
        # Log final SMS status
        if not sms_success:
            print(f" PROVIDER REGISTERED BUT SMS FAILED:")
            print(f"   Provider: {provider_name} ({provider_id})")
            print(f"   Phone: {cleaned_phone}")
            print(f"   SMS Error: {sms_result}")
            print(f"   Action: Provider registered successfully, but welcome SMS not sent")
        
        return jsonify({
            "status": "success",
            "message": "Provider registered successfully",
            "provider_id": provider_id,
            "name": provider_name,
            "phone": cleaned_phone,
            "dashboard_url": f"/providers",
            "welcome_sms_sent": sms_success,
            "sms_result": sms_result if not sms_success else "SMS sent successfully",
            "debug_info": {
                "textmagic_configured": bool(TEXTMAGIC_USERNAME and TEXTMAGIC_API_KEY),
                "phone_format_valid": cleaned_phone.startswith('+') if cleaned_phone else False,
                "message_length": len(welcome_message) if 'welcome_message' in locals() else 0
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"\nCRITICAL ERROR during provider registration:")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error message: {str(e)}")
        print(f"   Provider data: name='{provider_name if 'provider_name' in locals() else 'N/A'}', phone='{provider_phone if 'provider_phone' in locals() else 'N/A'}'")
        print(f"   Cleaned phone: '{cleaned_phone if 'cleaned_phone' in locals() else 'N/A'}'")
        print(f"   Provider ID: '{provider_id if 'provider_id' in locals() else 'N/A'}'")
        
        # Import traceback for detailed error info
        import traceback
        print(f"   Full traceback:")
        traceback.print_exc()
        
        return jsonify({
            "status": "error",
            "message": f"Registration failed: {str(e)}",
            "error_type": type(e).__name__,
            "debug_info": {
                "provider_name": provider_name if 'provider_name' in locals() else None,
                "provider_phone": provider_phone if 'provider_phone' in locals() else None,
                "cleaned_phone": cleaned_phone if 'cleaned_phone' in locals() else None,
                "provider_id": provider_id if 'provider_id' in locals() else None,
                "textmagic_configured": bool(TEXTMAGIC_USERNAME and TEXTMAGIC_API_KEY)
            }
        }), 500

@app.route('/debug-endpoints', methods=['GET'])
def debug_endpoints():
    """Debug endpoint to check server status and available routes"""
    import time
    
    # Get all routes
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods - {'HEAD', 'OPTIONS'}),
            'rule': str(rule)
        })
    
    # Find register-provider routes
    register_routes = [r for r in routes if 'register-provider' in r['rule']]
    
    return jsonify({
        "server_status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "server_time": time.time(),
        "register_provider_routes": register_routes,
        "all_routes_count": len(routes),
        "textmagic_configured": bool(TEXTMAGIC_USERNAME and TEXTMAGIC_API_KEY),
        "test_instructions": {
            "1": "Try GET /register-provider-info",
            "2": "Try GET /register-provider", 
            "3": "Try POST /test-welcome-sms with JSON data",
            "4": "Check if form submits to /register-provider"
        }
    })

@app.route('/register-provider-info', methods=['GET'])
def register_provider_info():
    """GET endpoint to check if register-provider is accessible"""
    return jsonify({
        "message": "register-provider endpoint is accessible",
        "methods": ["POST"],
        "description": "Use POST to register a new provider",
        "required_fields": ["name", "phone"],
        "test_endpoint": "/test-welcome-sms",
        "register_endpoint": "/register-provider",
        "textmagic_configured": bool(TEXTMAGIC_USERNAME and TEXTMAGIC_API_KEY)
    })

@app.route('/test-welcome-sms', methods=['POST'])
def test_welcome_sms():
    """Test endpoint to manually test welcome SMS functionality"""
    try:
        print(f"\n🧪 TESTING WELCOME SMS FUNCTIONALITY")
        
        # Get test data
        data = request.get_json() if request.is_json else request.form.to_dict()
        test_name = data.get('name', 'Test Provider')
        test_phone = data.get('phone', '+15551234567')
        test_provider_id = data.get('provider_id', 'test_provider_123')
        
        print(f"📋 Test Parameters:")
        print(f"  - Name: {test_name}")
        print(f"  - Phone: {test_phone}")
        print(f"  - Provider ID: {test_provider_id}")
        
        # Check TextMagic credentials
        print(f"🔧 SMS Configuration Check:")
        print(f"  - TEXTMAGIC_USERNAME: {'✅ Set' if TEXTMAGIC_USERNAME else '❌ Missing'}")
        print(f"  - TEXTMAGIC_API_KEY: {'✅ Set' if TEXTMAGIC_API_KEY else '❌ Missing'}")
        print(f"  - TEXTMAGIC_FROM_NUMBER: {TEXTMAGIC_FROM_NUMBER if TEXTMAGIC_FROM_NUMBER else '❌ Missing'}")
        
        if not TEXTMAGIC_USERNAME or not TEXTMAGIC_API_KEY:
            return jsonify({
                "status": "error",
                "message": "TextMagic credentials not configured",
                "debug": {
                    "username_set": bool(TEXTMAGIC_USERNAME),
                    "api_key_set": bool(TEXTMAGIC_API_KEY),
                    "from_number": TEXTMAGIC_FROM_NUMBER
                }
            }), 400
        
        # Create welcome message
        welcome_message = (
            f"🎉 Welcome to Gold Touch, {test_name}!\n\n"
            f"You're now part of our provider network. No action needed right now.\n\n"
            f"HOW IT WORKS:\n"
            f"• When booking requests come in, you'll get a separate SMS\n"
            f"• Reply Y to accept or N to decline those future requests\n"
            f"• You'll have 15 minutes to respond to each booking request\n"
            f"• Feel free to ask me anything! I'm here to help.\n"
            f"• For system errors, contact: 954-614-4683\n\n"
            f"This is an automated AI assistant welcoming you aboard!"
        )
        
        print(f"📝 Welcome Message:")
        print(f"  - Length: {len(welcome_message)} characters")
        print(f"  - Content: {welcome_message}")
        
        # Send SMS
        print(f"📱 Sending test welcome SMS...")
        sms_success, sms_result = send_sms(test_phone, welcome_message)
        
        print(f"📊 SMS Result:")
        print(f"  - Success: {sms_success}")
        print(f"  - Result: {sms_result}")
        
        return jsonify({
            "status": "success" if sms_success else "error",
            "message": "Test welcome SMS completed",
            "sms_sent": sms_success,
            "sms_result": sms_result,
            "test_data": {
                "name": test_name,
                "phone": test_phone,
                "provider_id": test_provider_id,
                "message_length": len(welcome_message)
            },
            "config": {
                "textmagic_username_set": bool(TEXTMAGIC_USERNAME),
                "textmagic_api_key_set": bool(TEXTMAGIC_API_KEY),
                "textmagic_from_number": TEXTMAGIC_FROM_NUMBER
            }
        })
        
    except Exception as e:
        print(f"💥 Error in test welcome SMS: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "message": f"Test failed: {str(e)}",
            "error_type": type(e).__name__
        }), 500

@app.route('/api/send-payment-sms', methods=['POST'])
def send_payment_sms():
    """Send payment SMS using TextMagic"""
    try:
        # Get phone and message from request
        data = request.get_json()
        if not data:
            data = request.form
        
        phone = data.get('phone')
        message = data.get('message')
        
        if not phone or not message:
            return jsonify({
                'success': False,
                'error': 'Phone and message are required'
            }), 400
        
        # Use existing TextMagic SMS function
        success, result = send_sms(phone, message)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'SMS sent successfully',
                'result': result
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to send SMS: {result}'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Server error: {str(e)}'
        }), 500

@app.route('/check-all-providers', methods=['GET'])
def check_all_providers():
    """Check all providers in the database"""
    try:
        providers = Provider.query.all()
        provider_list = []
        
        for provider in providers:
            provider_list.append({
                "id": provider.id,
                "name": provider.name,
                "phone": provider.phone,
                "created_at": provider.created_at.isoformat() if provider.created_at else None
            })
        
        return jsonify({
            "status": "success",
            "total_providers": len(provider_list),
            "providers": provider_list
        })
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/test-cancellation-detection', methods=['GET'])
def test_cancellation_detection():
    """Test endpoint to check cancellation detection logic"""
    test_messages = [
        "Hello, my apologies. Something came up and I need to reschedule with Joseli at a later time this coming week.",
        "I need to cancel my appointment",
        "Can we reschedule for tomorrow?",
        "Sorry, I can't make it today",
        "Emergency came up, need to postpone",
        "Hi, how are you?",  # Should not detect
        "Thank you for the massage"  # Should not detect
    ]
    
    results = []
    for message in test_messages:
        is_cancellation = detect_cancellation_request(message)
        results.append({
            "message": message,
            "is_cancellation": is_cancellation
        })
    
    return jsonify({
        "status": "success",
        "test_results": results
    })

@app.route('/routes', methods=['GET'])
def list_routes():
    """List all available routes"""
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

@app.route('/admin/export-customers', methods=['GET'])
def admin_export_customers():
    """Admin endpoint to export customer data"""
    try:
        format_type = request.args.get('format', 'json')  # json, csv, or both
        include_duplicates = request.args.get('duplicates', 'false').lower() == 'true'
        
        customers_data = []
        phone_to_customer = {}
        
        # Get all bookings
        bookings = Booking.query.order_by(Booking.created_at.desc()).all()
        
        for booking in bookings:
            if not booking.customer_phone:
                continue
                
            cleaned_phone = clean_phone_number(booking.customer_phone)
            if not cleaned_phone:
                continue
            
            customer_data = {
                'customer_name': getattr(booking, 'customer_name', '') or 'Unknown',
                'customer_phone': cleaned_phone,
                'original_phone_format': booking.customer_phone,
                'first_booking_date': booking.created_at.isoformat() if booking.created_at else '',
                'last_booking_date': booking.created_at.isoformat() if booking.created_at else '',
                'total_bookings': 1,
                'booking_statuses': [booking.status],
                'services_used': [booking.service_type] if booking.service_type else [],
                'providers_used': [booking.provider_id] if booking.provider_id else [],
                'addresses_used': [booking.address] if booking.address else [],
                'add_ons_used': [getattr(booking, 'add_ons', '')] if getattr(booking, 'add_ons', '') else [],
                'booking_ids': [booking.id]
            }
            
            if include_duplicates:
                customers_data.append(customer_data)
            else:
                # Deduplicate by phone
                if cleaned_phone in phone_to_customer:
                    existing = phone_to_customer[cleaned_phone]
                    
                    # Update name if current has name and existing doesn't
                    if customer_data['customer_name'] != 'Unknown' and existing['customer_name'] == 'Unknown':
                        existing['customer_name'] = customer_data['customer_name']
                    
                    # Update dates
                    if booking.created_at:
                        booking_date = booking.created_at.isoformat()
                        if booking_date < existing['first_booking_date']:
                            existing['first_booking_date'] = booking_date
                        if booking_date > existing['last_booking_date']:
                            existing['last_booking_date'] = booking_date
                    
                    # Increment and merge
                    existing['total_bookings'] += 1
                    existing['booking_statuses'].append(booking.status)
                    
                    if booking.service_type and booking.service_type not in existing['services_used']:
                        existing['services_used'].append(booking.service_type)
                    
                    if booking.provider_id and booking.provider_id not in existing['providers_used']:
                        existing['providers_used'].append(booking.provider_id)
                    
                    if booking.address and booking.address not in existing['addresses_used']:
                        existing['addresses_used'].append(booking.address)
                    
                    addon = getattr(booking, 'add_ons', '')
                    if addon and addon not in existing['add_ons_used']:
                        existing['add_ons_used'].append(addon)
                    
                    existing['booking_ids'].append(booking.id)
                    
                else:
                    phone_to_customer[cleaned_phone] = customer_data
                    customers_data.append(customer_data)
        
        if not include_duplicates:
            customers_data = list(phone_to_customer.values())
        
        # Sort by total bookings
        customers_data.sort(key=lambda x: x['total_bookings'], reverse=True)
        
        # Generate statistics
        total_customers = len(customers_data)
        total_bookings = sum(c['total_bookings'] for c in customers_data)
        repeat_customers = sum(1 for c in customers_data if c['total_bookings'] > 1)
        
        stats = {
            'total_customers': total_customers,
            'total_bookings': total_bookings,
            'repeat_customers': repeat_customers,
            'one_time_customers': total_customers - repeat_customers,
            'repeat_rate': (repeat_customers / total_customers * 100) if total_customers > 0 else 0,
            'avg_bookings_per_customer': (total_bookings / total_customers) if total_customers > 0 else 0
        }
        
        if format_type == 'csv':
            # Return CSV file
            import io
            import csv
            
            output = io.StringIO()
            if customers_data:
                fieldnames = [
                    'customer_name', 'customer_phone', 'original_phone_format',
                    'first_booking_date', 'last_booking_date', 'total_bookings',
                    'booking_statuses', 'services_used', 'providers_used',
                    'addresses_used', 'add_ons_used', 'booking_ids'
                ]
                
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                
                for customer in customers_data:
                    row = customer.copy()
                    # Convert lists to strings for CSV
                    for key in ['booking_statuses', 'services_used', 'providers_used', 
                               'addresses_used', 'add_ons_used', 'booking_ids']:
                        if isinstance(row[key], list):
                            row[key] = '; '.join(str(item) for item in row[key] if item)
                    writer.writerow(row)
            
            output.seek(0)
            
            # Create file-like object for download
            mem = io.BytesIO()
            mem.write(output.getvalue().encode('utf-8'))
            mem.seek(0)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'customers_export_{timestamp}.csv'
            
            return send_file(
                mem,
                as_attachment=True,
                download_name=filename,
                mimetype='text/csv'
            )
        
        else:
            # Return JSON
            return jsonify({
                'status': 'success',
                'statistics': stats,
                'customers': customers_data,
                'export_info': {
                    'format': format_type,
                    'include_duplicates': include_duplicates,
                    'exported_at': datetime.now().isoformat(),
                    'total_records': len(customers_data)
                }
            })
    
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__
        }), 500

@app.route('/admin/customer-stats', methods=['GET'])
def admin_customer_stats():
    """Get customer statistics without full export"""
    try:
        from collections import defaultdict
        
        bookings = Booking.query.all()
        
        # Quick stats
        total_bookings = len(bookings)
        unique_phones = set()
        phone_booking_counts = defaultdict(int)
        
        for booking in bookings:
            if booking.customer_phone:
                cleaned_phone = clean_phone_number(booking.customer_phone)
                if cleaned_phone:
                    unique_phones.add(cleaned_phone)
                    phone_booking_counts[cleaned_phone] += 1
        
        total_customers = len(unique_phones)
        repeat_customers = sum(1 for count in phone_booking_counts.values() if count > 1)
        
        # Service popularity
        service_counts = defaultdict(int)
        for booking in bookings:
            if booking.service_type:
                service_counts[booking.service_type] += 1
        
        top_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Recent activity
        recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(10).all()
        recent_activity = []
        for booking in recent_bookings:
            recent_activity.append({
                'id': booking.id,
                'customer_phone': booking.customer_phone,
                'customer_name': getattr(booking, 'customer_name', 'Unknown'),
                'service_type': booking.service_type,
                'status': booking.status,
                'created_at': booking.created_at.isoformat() if booking.created_at else None
            })
        
        return jsonify({
            'status': 'success',
            'statistics': {
                'total_customers': total_customers,
                'total_bookings': total_bookings,
                'repeat_customers': repeat_customers,
                'one_time_customers': total_customers - repeat_customers,
                'repeat_rate': (repeat_customers / total_customers * 100) if total_customers > 0 else 0,
                'avg_bookings_per_customer': (total_bookings / total_customers) if total_customers > 0 else 0
            },
            'top_services': top_services,
            'recent_activity': recent_activity
        })
    
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    # Run the app (background tasks already started above)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

