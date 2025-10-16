#!/usr/bin/env python3
"""
Integration module for connecting Flask app with existing Node.js Stripe Payment Service
This module handles communication between the Python Flask app and the Node.js lead generation service
"""

import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration
STRIPE_SERVICE_URL = os.getenv('STRIPE_SERVICE_URL', 'http://localhost:3000')
STRIPE_SERVICE_API_KEY = os.getenv('STRIPE_SERVICE_API_KEY')  # Optional API key for authentication

class StripeServiceClient:
    """Client for communicating with the Node.js Stripe Payment Service"""
    
    def __init__(self, base_url=None, api_key=None):
        self.base_url = base_url or STRIPE_SERVICE_URL
        self.api_key = api_key or STRIPE_SERVICE_API_KEY
        self.session = requests.Session()
        
        # Set up authentication headers if API key is provided
        if self.api_key:
            self.session.headers.update({'Authorization': f'Bearer {self.api_key}'})
    
    def create_lead(self, lead_data, provider_ids=None):
        """
        Create a new lead in the Node.js service
        
        Args:
            lead_data (dict): Lead information
            provider_ids (list): Optional list of provider IDs to notify
            
        Returns:
            tuple: (success, result_data)
        """
        try:
            payload = {
                'lead_id': lead_data.get('id'),
                'city': lead_data.get('city'),
                'service_type': lead_data.get('service_type'),
                'preferred_time_window': lead_data.get('preferred_time_window'),
                'budget_range': lead_data.get('budget_range'),
                'client_name': lead_data.get('client_name'),
                'client_phone': lead_data.get('client_phone'),
                'client_email': lead_data.get('client_email'),
                'exact_address': lead_data.get('exact_address'),
                'original_notes': lead_data.get('notes_snippet'),
                'provider_ids': provider_ids or []
            }
            
            response = self.session.post(f'{self.base_url}/api/leads', json=payload)
            
            if response.status_code in [200, 201]:
                return True, response.json()
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except Exception as e:
            return False, f"Error creating lead: {str(e)}"
    
    def send_lead_to_providers(self, lead_id, provider_ids):
        """
        Send existing lead to additional providers
        
        Args:
            lead_id (str): Lead identifier
            provider_ids (list): List of provider IDs
            
        Returns:
            tuple: (success, result_data)
        """
        try:
            payload = {'provider_ids': provider_ids}
            
            response = self.session.post(
                f'{self.base_url}/api/leads/{lead_id}/send',
                json=payload
            )
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except Exception as e:
            return False, f"Error sending lead: {str(e)}"
    
    def get_lead_status(self, lead_id):
        """
        Get lead status from Node.js service
        
        Args:
            lead_id (str): Lead identifier
            
        Returns:
            tuple: (success, lead_data)
        """
        try:
            response = self.session.get(f'{self.base_url}/api/leads/{lead_id}')
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except Exception as e:
            return False, f"Error getting lead: {str(e)}"
    
    def handle_sms_response(self, provider_phone, message_content):
        """
        Forward SMS response to Node.js service for processing
        
        Args:
            provider_phone (str): Provider phone number
            message_content (str): SMS message content
            
        Returns:
            tuple: (success, result_data)
        """
        try:
            payload = {
                'provider_phone': provider_phone,
                'message': message_content,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            response = self.session.post(
                f'{self.base_url}/api/leads/sms-response',
                json=payload
            )
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"HTTP {response.status_code}: {response.text}"
                
        except Exception as e:
            return False, f"Error processing SMS response: {str(e)}"
    
    def check_service_health(self):
        """
        Check if the Node.js service is healthy
        
        Returns:
            tuple: (is_healthy, status_info)
        """
        try:
            response = self.session.get(f'{self.base_url}/health', timeout=5)
            
            if response.status_code == 200:
                return True, response.json()
            else:
                return False, f"Service unhealthy: HTTP {response.status_code}"
                
        except Exception as e:
            return False, f"Service unavailable: {str(e)}"

# Global client instance
stripe_service = StripeServiceClient()

def test_integration():
    """Test the integration with the Node.js service"""
    print("🔧 Testing Stripe Service Integration...")
    
    # Test 1: Health check
    healthy, status = stripe_service.check_service_health()
    if healthy:
        print(f"✅ Service is healthy: {status}")
    else:
        print(f"❌ Service health check failed: {status}")
        return False
    
    # Test 2: Create a test lead
    test_lead = {
        'id': 'lead_test_integration',
        'city': 'Miami',
        'service_type': '60 min Mobile Massage',
        'preferred_time_window': 'Evening (6-9 PM)',
        'budget_range': '$150-200',
        'client_name': 'Integration Test Client',
        'client_phone': '+15551234567',
        'client_email': 'test@example.com',
        'exact_address': '123 Test Street, Miami, FL 33139',
        'notes_snippet': 'Test lead for integration'
    }
    
    success, result = stripe_service.create_lead(test_lead, ['provider60'])
    if success:
        print(f"✅ Test lead created: {result}")
    else:
        print(f"❌ Test lead creation failed: {result}")
    
    return True

if __name__ == "__main__":
    test_integration()
