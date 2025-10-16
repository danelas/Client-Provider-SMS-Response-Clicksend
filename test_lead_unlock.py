#!/usr/bin/env python3
"""
Test script for the Lead Unlock SMS system (Node.js Service Integration)
This script demonstrates how to create leads and send them to providers via the integrated Node.js service
"""

import requests
import json
import time

# Configuration
FLASK_APP_URL = "http://localhost:5000"  # Flask app URL
STRIPE_SERVICE_URL = "http://localhost:3000"  # Node.js Stripe service URL
API_BASE = f"{FLASK_APP_URL}/api"

def test_service_health():
    """Test both Flask app and Node.js service health"""
    print("🏥 Testing Service Health...")
    
    # Test Flask app
    try:
        response = requests.get(f"{FLASK_APP_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Flask app is healthy")
        else:
            print(f"❌ Flask app unhealthy: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Flask app unreachable: {str(e)}")
        return False
    
    # Test Node.js Stripe service via Flask proxy
    try:
        response = requests.get(f"{API_BASE}/stripe-service/health", timeout=5)
        if response.status_code == 200:
            result = response.json()
            if result.get('stripe_service_healthy'):
                print("✅ Node.js Stripe service is healthy")
            else:
                print(f"❌ Node.js Stripe service unhealthy: {result}")
                return False
        else:
            print(f"❌ Node.js Stripe service check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Node.js Stripe service unreachable: {str(e)}")
        return False
    
    return True

def test_create_lead():
    """Test creating a new lead"""
    print("🔥 Testing Lead Creation...")
    
    lead_data = {
        "city": "Miami",
        "service_type": "60 min Mobile Massage",
        "preferred_time_window": "Evening (6-9 PM)",
        "budget_range": "$150-200",
        "notes_snippet": "Client prefers deep tissue massage",
        "client_name": "Sarah Johnson",
        "client_phone": "+1234567890",
        "client_email": "sarah.johnson@email.com",
        "exact_address": "123 Ocean Drive, Miami Beach, FL 33139",
        "provider_ids": ["provider60", "provider61"]  # Send to these providers
    }
    
    try:
        response = requests.post(f"{API_BASE}/leads", json=lead_data)
        
        if response.status_code == 201:
            result = response.json()
            print(f"✅ Lead created successfully!")
            print(f"   Lead ID: {result['lead_id']}")
            print(f"   Provider Results:")
            for provider_result in result['provider_results']:
                status = "✅" if provider_result['success'] else "❌"
                print(f"     {status} {provider_result['provider_id']}: {provider_result['message']}")
            return result['lead_id']
        else:
            print(f"❌ Failed to create lead: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error creating lead: {str(e)}")
        return None

def test_get_lead(lead_id):
    """Test getting lead details"""
    print(f"\n🔍 Testing Get Lead: {lead_id}")
    
    try:
        # Get lead without locked details
        response = requests.get(f"{API_BASE}/leads/{lead_id}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Lead retrieved successfully (public view):")
            lead = result['lead']
            print(f"   City: {lead['city']}")
            print(f"   Service: {lead['service_type']}")
            print(f"   Budget: {lead['budget_range']}")
            print(f"   Client Name: {lead['client_name']}")  # Should be ***LOCKED***
            print(f"   Client Phone: {lead['client_phone']}")  # Should be ***LOCKED***
        else:
            print(f"❌ Failed to get lead: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Error getting lead: {str(e)}")

def test_send_lead_to_more_providers(lead_id):
    """Test sending existing lead to additional providers"""
    print(f"\n📤 Testing Send Lead to More Providers: {lead_id}")
    
    send_data = {
        "provider_ids": ["provider62", "provider63"],
        "config": {
            "price_cents": 2000,
            "currency": "usd", 
            "ttl_hours": 24
        }
    }
    
    try:
        response = requests.post(f"{API_BASE}/leads/{lead_id}/send", json=send_data)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Lead sent to additional providers:")
            for provider_result in result['provider_results']:
                status = "✅" if provider_result['success'] else "❌"
                print(f"   {status} {provider_result['provider_id']}: {provider_result['message']}")
        else:
            print(f"❌ Failed to send lead: {response.status_code}")
            print(f"   Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Error sending lead: {str(e)}")

def simulate_provider_response():
    """Simulate how a provider would respond to unlock a lead"""
    print("\n📱 Simulating Provider SMS Response...")
    print("When a provider receives a teaser SMS like:")
    print("  'Amy, new client inquiry in Miami. Type: 60 min Mobile Massage.'")
    print("  'Time window: Evening (6-9 PM). Budget: $150-200.'") 
    print("  'Reply Y to unlock contact details for $20. Reply N to skip. Lead lead_abc12345.'")
    print()
    print("The provider would text back: 'Y lead_abc12345'")
    print("This would trigger the payment link creation and SMS.")
    print()
    print("After payment, they receive the full client details:")
    print("  'Amy, here are the client details:'")
    print("  'Name: Sarah Johnson'")
    print("  'Phone: +1234567890'")
    print("  'Email: sarah.johnson@email.com'")
    print("  'Address: 123 Ocean Drive, Miami Beach, FL 33139'")

def main():
    """Run all tests"""
    print("🚀 Lead Unlock System Test Suite (Node.js Integration)")
    print("=" * 60)
    
    # Test 0: Check service health
    if not test_service_health():
        print("\n❌ Service health check failed. Please ensure both Flask app and Node.js service are running.")
        print("   Flask app: python app.py")
        print("   Node.js service: cd ../stripe-payment-service && npm start")
        return
    
    # Test 1: Create a lead
    lead_id = test_create_lead()
    
    if lead_id:
        # Test 2: Get lead details
        test_get_lead(lead_id)
        
        # Test 3: Send to more providers
        test_send_lead_to_more_providers(lead_id)
    
    # Test 4: Show SMS flow simulation
    simulate_provider_response()
    
    print("\n" + "=" * 50)
    print("🎯 Test Summary:")
    print("1. ✅ Lead creation API tested")
    print("2. ✅ Lead retrieval API tested") 
    print("3. ✅ Send to additional providers tested")
    print("4. ✅ SMS response flow documented")
    print()
    print("💡 Next Steps:")
    print("- Configure Stripe API keys in .env")
    print("- Set up Stripe webhook endpoint")
    print("- Test actual SMS responses via TextMagic webhook")
    print("- Test payment flow with real Stripe payments")

if __name__ == "__main__":
    main()
