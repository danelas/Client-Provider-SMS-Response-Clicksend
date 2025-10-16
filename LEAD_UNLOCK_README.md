# Lead Unlock SMS System

A pay-per-lead system that allows providers to unlock client contact details for $20 via SMS and Stripe payments.

## Overview

The Lead Unlock system implements a complete state machine for managing lead distribution to massage providers:

1. **Lead Creation**: Client inquiries are converted into leads with locked contact details
2. **Teaser SMS**: Providers receive preview information (city, service type, budget, time window)
3. **Payment Flow**: Providers pay $20 to unlock full client contact details
4. **Detail Reveal**: After payment, providers receive complete client information

## State Machine

```
NEW_LEAD → TEASER_SENT → AWAIT_CONFIRM
  ↓ (on "Y")
CHECK_EXISTING_PAYMENT → CREATE_PAYMENT_LINK → PAYMENT_LINK_SENT → AWAITING_PAYMENT
  ↓ (on Stripe webhook)
PAID → REVEAL_DETAILS_SENT → DONE

Alternative flows:
- "N" or TTL expiry → EXPIRED
- "STOP" → OPTED_OUT
```

## Database Schema

### Leads Table
- `id` (PK): Unique lead identifier (e.g., "lead_abc12345")
- `city`: Service location city
- `service_type`: Type of massage service requested
- `preferred_time_window`: Client's preferred appointment time
- `budget_range`: Client's budget range
- `notes_snippet`: Brief notes about client preferences
- **Locked Fields** (only revealed after payment):
  - `client_name`: Full client name
  - `client_phone`: Client phone number
  - `client_email`: Client email address
  - `exact_address`: Complete service address

### Lead Unlocks Table
- `id` (PK): Auto-increment ID
- `lead_id` (FK): Reference to leads table
- `provider_id` (FK): Reference to providers table
- `status`: Current state in the unlock process
- `payment_link_url`: Stripe payment link URL
- `checkout_session_id`: Stripe session ID after payment
- `unlocked_at`: Timestamp when details were revealed
- `ttl_expires_at`: When the lead offer expires
- `price_cents`: Cost in cents (default: 2000 = $20.00)
- `currency`: Payment currency (default: "usd")

## API Endpoints

### Create Lead
```http
POST /api/leads
Content-Type: application/json

{
  "city": "Miami",
  "service_type": "60 min Mobile Massage",
  "preferred_time_window": "Evening (6-9 PM)",
  "budget_range": "$150-200",
  "notes_snippet": "Client prefers deep tissue massage",
  "client_name": "Sarah Johnson",
  "client_phone": "+1234567890",
  "client_email": "sarah.johnson@email.com",
  "exact_address": "123 Ocean Drive, Miami Beach, FL 33139",
  "provider_ids": ["provider60", "provider61"],
  "config": {
    "price_cents": 2000,
    "currency": "usd",
    "ttl_hours": 24
  }
}
```

### Get Lead Details
```http
GET /api/leads/{lead_id}
GET /api/leads/{lead_id}?include_locked=true  # Admin only
```

### Send Lead to Additional Providers
```http
POST /api/leads/{lead_id}/send
Content-Type: application/json

{
  "provider_ids": ["provider62", "provider63"],
  "config": {
    "price_cents": 2000,
    "currency": "usd",
    "ttl_hours": 24
  }
}
```

### Stripe Webhook
```http
POST /webhook/stripe
```
Handles payment completion events and triggers detail revelation.

## SMS Message Templates

### Teaser Message
```
Amy, new client inquiry in Miami. Type: 60 min Mobile Massage. 
Time window: Evening (6-9 PM). Budget: $150-200. 
Reply Y to unlock contact details for $20. Reply N to skip. Lead lead_abc12345.
```

### Payment Link Message
```
Amy, complete your $20 payment to unlock client details: 
https://buy.stripe.com/... (Lead lead_abc12345)
```

### Reveal Message (After Payment)
```
Amy, here are the client details:

Name: Sarah Johnson
Phone: +1234567890
Email: sarah.johnson@email.com
Address: 123 Ocean Drive, Miami Beach, FL 33139
Notes: Client prefers deep tissue massage

Gold Touch List provides advertising access to client inquiries. 
We do not arrange or guarantee appointments.
```

## SMS Response Processing

The system automatically processes provider SMS responses:

- **"Y" or "Yes"**: Creates payment link and sends to provider
- **"N" or "No"**: Marks lead as opted out for this provider
- **"STOP"**: Unsubscribes provider from all lead notifications
- **Messages containing "lead_"**: Automatically processed as lead responses

## Environment Variables

Add these to your `.env` file:

```bash
# Stripe Configuration
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Existing TextMagic Configuration
TEXTMAGIC_USERNAME=your_username
TEXTMAGIC_API_KEY=your_api_key
TEXTMAGIC_FROM_NUMBER=+1234567890
```

## Setup Instructions

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Database Migration**
   ```bash
   python migrate_lead_unlock.py
   ```

3. **Configure Stripe**
   - Set up Stripe account and get API keys
   - Configure webhook endpoint: `https://yourdomain.com/webhook/stripe`
   - Add webhook events: `checkout.session.completed`, `payment_link.payment_succeeded`

4. **Test the System**
   ```bash
   python test_lead_unlock.py
   ```

## Security Features

- **Contact Protection**: Client details never sent via SMS until payment confirmed
- **Idempotency**: Prevents duplicate payments for same lead/provider combination
- **TTL Expiry**: Leads automatically expire after 24 hours (configurable)
- **Webhook Verification**: Stripe webhook signatures verified for security
- **Opt-out Support**: Providers can unsubscribe with "STOP"

## Refund Policy

- Fees are for access to contact information
- Non-refundable once client details are revealed
- Auto-retry if reveal fails due to system error
- Escalation process for failed reveals

## Testing

Use the provided test script to verify functionality:

```bash
python test_lead_unlock.py
```

This will:
1. Create a sample lead
2. Send to test providers
3. Demonstrate the SMS flow
4. Show API responses

## Integration with Existing System

The Lead Unlock system integrates seamlessly with the existing booking system:

- Uses same SMS webhook handler (`/webhook/textmagic`)
- Shares provider database and SMS infrastructure
- Processes lead responses before booking responses
- Falls back to existing support system for non-lead messages

## Monitoring and Analytics

Track system performance through:
- Lead conversion rates (teaser → payment)
- Provider response times
- Payment success rates
- Revenue per lead
- Geographic distribution of leads

## Support and Troubleshooting

Common issues:
1. **Payment link not working**: Check Stripe API keys and webhook configuration
2. **SMS not sending**: Verify TextMagic credentials and phone number format
3. **Details not revealing**: Check webhook endpoint and signature verification
4. **Provider not receiving teasers**: Verify provider phone number and opt-out status
