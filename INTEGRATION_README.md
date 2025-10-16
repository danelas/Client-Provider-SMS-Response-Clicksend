# Lead Unlock SMS System - Node.js Service Integration

This Flask application now integrates with the existing Node.js Stripe Payment Service to provide a comprehensive lead unlock system. Instead of duplicating Stripe functionality, the Flask app acts as a bridge between SMS interactions and the Node.js service.

## Architecture Overview

```
Client Inquiry → Flask App → Node.js Service → Stripe → SMS Notifications
     ↓              ↓            ↓             ↓         ↓
  Web Form      SMS Handler   Lead Storage   Payment   Provider SMS
                              & Processing   Processing
```

## Integration Components

### 1. Flask App (Python)
- **SMS Webhook Handler**: Processes incoming SMS from providers
- **Lead API Proxy**: Forwards lead creation requests to Node.js service
- **Provider Management**: Manages provider database and SMS interactions
- **Integration Layer**: Bridges SMS system with Node.js payment service

### 2. Node.js Stripe Service
- **Lead Storage**: PostgreSQL database for lead information
- **Payment Processing**: Stripe integration for $20 lead unlock payments
- **SMS Notifications**: TextMagic integration for payment links and reveals
- **Webhook Handling**: Stripe webhook processing for payment completion

## Setup Instructions

### Prerequisites
1. **Flask App** running on port 5000
2. **Node.js Stripe Service** running on port 3000
3. Both services configured with proper environment variables

### Environment Variables

#### Flask App (.env)
```bash
# Database
DATABASE_URL=postgresql://...

# TextMagic SMS
TEXTMAGIC_USERNAME=your_username
TEXTMAGIC_API_KEY=your_api_key
TEXTMAGIC_FROM_NUMBER=+1234567890

# OpenAI (optional)
OPENAI_API_KEY=sk-...

# Stripe Service Integration
STRIPE_SERVICE_URL=http://localhost:3000
STRIPE_SERVICE_API_KEY=optional_api_key
```

#### Node.js Service (.env)
```bash
# Stripe Configuration
STRIPE_SECRET=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Database Configuration  
DATABASE_URL=postgres://username:password@host:port/database

# TextMagic Configuration
TEXTMAGIC_USERNAME=your_username
TEXTMAGIC_API_KEY=your_api_key
TEXTMAGIC_FROM_NUMBER=+1234567890

# Domain Configuration
DOMAIN=https://yourdomain.com
```

## API Flow

### 1. Lead Creation
```http
POST /api/leads (Flask App)
↓
POST /api/leads (Node.js Service)
↓
SMS sent to providers via TextMagic
```

### 2. SMS Response Processing
```
Provider SMS → TextMagic Webhook → Flask App → Node.js Service
↓
Payment link creation → SMS to provider
```

### 3. Payment Completion
```
Stripe Payment → Webhook → Node.js Service → Client details SMS
```

## Key Integration Files

### `stripe_service_integration.py`
- **StripeServiceClient**: HTTP client for Node.js service communication
- **Health checks**: Service availability monitoring
- **Error handling**: Graceful fallback for service unavailability

### Modified `app.py`
- **Removed**: Direct Stripe integration
- **Added**: Node.js service proxy endpoints
- **Enhanced**: SMS processing with lead unlock detection

### `test_lead_unlock.py`
- **Service health checks**: Tests both Flask and Node.js services
- **Integration testing**: End-to-end lead creation and processing
- **Error scenarios**: Handles service unavailability

## SMS Message Flow

### 1. Teaser Message (Node.js → TextMagic)
```
Amy, new client inquiry in Miami. Type: 60 min Mobile Massage. 
Time window: Evening (6-9 PM). Budget: $150-200. 
Reply Y to unlock contact details for $20. Reply N to skip. Lead lead_abc12345.
```

### 2. Provider Response (TextMagic → Flask → Node.js)
```
Provider: "Y lead_abc12345"
→ Flask detects "lead" keyword
→ Forwards to Node.js service
→ Payment link created and sent
```

### 3. Payment Link (Node.js → TextMagic)
```
Amy, complete your $20 payment to unlock client details: 
https://buy.stripe.com/... (Lead lead_abc12345)
```

### 4. Client Details Reveal (After Payment)
```
Amy, here are the client details:

Name: Sarah Johnson
Phone: +1234567890
Email: sarah.johnson@email.com
Address: 123 Ocean Drive, Miami Beach, FL 33139

Gold Touch List provides advertising access to client inquiries.
```

## Testing the Integration

### 1. Start Both Services
```bash
# Terminal 1: Flask App
cd Client-Provider-SMS-Response-Clicksend
python app.py

# Terminal 2: Node.js Service
cd stripe-payment-service
npm start
```

### 2. Run Integration Tests
```bash
cd Client-Provider-SMS-Response-Clicksend
python test_lead_unlock.py
```

### 3. Test Health Endpoints
```bash
# Flask app health
curl http://localhost:5000/health

# Node.js service health via Flask proxy
curl http://localhost:5000/api/stripe-service/health
```

## Monitoring and Troubleshooting

### Health Checks
- **Flask App**: `GET /health`
- **Node.js Service**: `GET /api/stripe-service/health`
- **Integration Status**: Both services must be healthy for lead processing

### Common Issues

1. **Service Unavailable**
   - Check if Node.js service is running on port 3000
   - Verify STRIPE_SERVICE_URL in Flask app environment

2. **SMS Not Sending**
   - Verify TextMagic credentials in both services
   - Check webhook configuration

3. **Payment Processing Fails**
   - Verify Stripe API keys in Node.js service
   - Check webhook endpoint configuration

4. **Database Connectivity**
   - Ensure PostgreSQL is accessible from both services
   - Verify DATABASE_URL in both environments

### Logs and Debugging
- **Flask App**: Console output shows integration status
- **Node.js Service**: PM2 logs or console output
- **Stripe Dashboard**: Payment and webhook logs
- **TextMagic Dashboard**: SMS delivery status

## Deployment Considerations

### Production Setup
1. **Load Balancing**: Both services behind reverse proxy
2. **SSL Termination**: HTTPS for webhook endpoints
3. **Database**: Shared PostgreSQL instance
4. **Monitoring**: Health checks and alerting
5. **Secrets Management**: Environment variables via secrets manager

### Scaling
- **Horizontal**: Multiple instances of each service
- **Database**: Connection pooling and read replicas
- **Caching**: Redis for frequently accessed data
- **Queue**: Background job processing for SMS

## Security Features

### Data Protection
- **Client PII**: Stored only in Node.js service database
- **Payment Data**: Handled entirely by Stripe
- **SMS Content**: No sensitive data in Flask app logs

### API Security
- **Service-to-Service**: Optional API key authentication
- **Webhook Verification**: Stripe signature validation
- **Rate Limiting**: Prevent abuse of lead creation endpoints

### Compliance
- **PCI DSS**: Payment processing via Stripe
- **GDPR**: Data retention and deletion policies
- **SMS Compliance**: Opt-out mechanisms and consent tracking

## Future Enhancements

### Planned Features
1. **Real-time Notifications**: WebSocket integration
2. **Analytics Dashboard**: Lead conversion metrics
3. **Provider Preferences**: Service area and pricing filters
4. **Automated Retries**: Failed payment and SMS handling
5. **Multi-language Support**: Localized SMS templates

### Integration Opportunities
1. **CRM Systems**: Salesforce, HubSpot integration
2. **Calendar Systems**: Appointment scheduling
3. **Notification Services**: Push notifications, email
4. **Analytics Platforms**: Google Analytics, Mixpanel
5. **Customer Support**: Zendesk, Intercom integration
