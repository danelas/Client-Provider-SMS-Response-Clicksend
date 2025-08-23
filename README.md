# TextMagic SMS Response Handler

A Flask application that processes SMS responses via TextMagic webhooks and manages customer-provider communication.

## Features

- Stores customer-provider relationships in a database
- Uses provider IDs (e.g., `prov_amy`) to look up provider details
- Maintains a JSON file of providers with their contact information
- Receives form submissions with customer details and provider ID
- Handles SMS webhooks from TextMagic
- Processes "yes"/"no" or "Y"/"N" responses from providers
- Sends detailed confirmation or alternative provider messages
- Fallback to test number if primary provider fails
- Deployable on Render

## Setup

1. Clone the repository
2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Create a `.env` file with your configuration:
   ```
   # Environment Variables

   # Database
   DATABASE_URL=sqlite:///bookings.db

   # TextMagic API
   TEXTMAGIC_USERNAME=your_username
   TEXTMAGIC_API_KEY=your_api_key
   TEXTMAGIC_FROM_NUMBER=+1234567890  # Your TextMagic dedicated number

   # Optional
   FLASK_DEBUG=1  # Set to 0 in production
   TEST_PHONE_NUMBER=+1234567890  # For testing and fallback
   ```
5. Initialize the database:
   ```
   python
   >>> from app import app, db
   >>> with app.app_context():
   ...     db.create_all()
   ```

## Running Locally

1. Start the Flask development server:
   ```
   python app.py
   ```
2. Use a tool like ngrok to expose your local server to the internet:
   ```
   ngrok http 5000
   ```
3. Set up the ClickSend webhook to point to your ngrok URL (e.g., `https://your-ngrok-url.ngrok.io/webhook/sms`)

## Deployment to Render

1. Push your code to a GitHub repository
2. Create a new Web Service on Render and connect your GitHub repository
3. Set the following environment variables in the Render dashboard:
   - `CLICKSEND_USERNAME`: Your ClickSend username
   - `CLICKSEND_API_KEY`: Your ClickSend API key
   - `CLICKSEND_FROM_NUMBER`: +17865241227
4. Deploy the application

## API Endpoints

### 1. Create a New Booking
```
POST /api/booking
Content-Type: application/json

{
    "customer_phone": "+1234567890",
    "provider_phone": "+1987654321"
}
```

### 2. ClickSend Webhook
This endpoint is called by ClickSend when a provider responds to an SMS.
```
POST /webhook/sms
```

## Integration with Fluent Forms

1. In your Fluent Forms submission handler, make a POST request to `/api/booking` with:
   - `customer_phone`: The customer's phone number (format: +1234567890)
   - `provider_phone`: The provider's phone number (format: +1234567890)

2. The system will store this mapping and wait for the provider's response.

## TextMagic Webhook Setup

### For Dedicated Number
1. Log in to your TextMagic account
2. Go to Settings > API & Webhooks
3. Under "Reply Callback URLs", add a new entry:
   - **URL**: `https://your-render-app.onrender.com/webhook/sms`
   - **Method**: `POST`
   - **Dedicated Number**: Select your dedicated number
4. Save the settings

### If Using Shared Webhook
If you can't set up a dedicated webhook, the application will automatically filter messages by the `TEXTMAGIC_FROM_NUMBER` environment variable. Make sure this is set to your dedicated number.

## ClickSend Webhook Setup

1. Log in to your ClickSend account
2. Go to SMS > Settings > API
3. Under "Inbound SMS Settings", set the Webhook URL to your deployed application's URL (e.g., `https://your-render-app.onrender.com/webhook/sms`)
4. Set the Webhook Method to `POST`
5. Save the settings

## License

MIT
