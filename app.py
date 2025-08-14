from flask import Flask, request, jsonify
import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# ClickSend API credentials
CLICKSEND_USERNAME = os.getenv('CLICKSEND_USERNAME')
CLICKSEND_API_KEY = os.getenv('CLICKSEND_API_KEY')
CLICKSEND_FROM_NUMBER = os.getenv('CLICKSEND_FROM_NUMBER', '+17865241227')

# ClickSend API endpoint
CLICKSEND_API_URL = 'https://rest.clicksend.com/v3/sms/send'

def send_sms(to_number, message):
    """Send SMS using ClickSend API"""
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Basic {CLICKSEND_API_KEY}'
    }
    
    payload = {
        'messages': [
            {
                'source': 'python',
                'from': CLICKSEND_FROM_NUMBER,
                'to': to_number,
                'body': message
            }
        ]
    }
    
    try:
        response = requests.post(
            CLICKSEND_API_URL,
            json=payload,
            headers=headers,
            auth=(CLICKSEND_USERNAME, '')
        )
        response.raise_for_status()
        return True, "SMS sent successfully"
    except requests.exceptions.RequestException as e:
        return False, str(e)

@app.route('/webhook/sms', methods=['POST'])
def sms_webhook():
    """Handle incoming SMS webhook from ClickSend"""
    try:
        data = request.json
        
        # Extract relevant data from webhook
        if 'data' in data and len(data['data']) > 0:
            message_data = data['data'][0]
            sender_number = message_data.get('from', '')
            message_text = message_data.get('body', '').strip().lower()
            
            # Check if message is a response to confirmation
            if message_text in ['yes', 'y']:
                # Send confirmation message
                send_sms(sender_number, "You are confirmed with the provider.")
            elif message_text in ['no', 'n']:
                # Send alternative provider message
                message = (
                    "Hi, we are sorry for the inconvenience, but the provider you selected is not available. "
                    "You can book with another provider here: goldtouchmobile.com/providers. Thanks!"
                )
                send_sms(sender_number, message)
            
            return jsonify({"status": "success"}), 200
        
        return jsonify({"status": "error", "message": "Invalid webhook data"}), 400
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'false').lower() == 'true')
