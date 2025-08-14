# ClickSend SMS Response Handler

A Flask application that processes SMS responses via ClickSend webhooks and sends appropriate replies based on the received message.

## Features

- Receives SMS webhooks from ClickSend
- Processes "yes"/"no" or "Y"/"N" responses
- Sends appropriate confirmation or alternative provider message
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
4. Create a `.env` file with your ClickSend credentials:
   ```
   CLICKSEND_USERNAME=your_username
   CLICKSEND_API_KEY=your_api_key
   CLICKSEND_FROM_NUMBER=+17865241227
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

## ClickSend Webhook Setup

1. Log in to your ClickSend account
2. Go to SMS > Settings > API
3. Under "Inbound SMS Settings", set the Webhook URL to your deployed application's URL (e.g., `https://your-render-app.onrender.com/webhook/sms`)
4. Set the Webhook Method to `POST`
5. Save the settings

## License

MIT
