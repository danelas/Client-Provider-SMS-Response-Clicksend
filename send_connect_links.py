#!/usr/bin/env python3
"""
Mass SMS sender for Stripe Connect onboarding links
Sends personalized Connect links to all Gold Touch Mobile providers
"""

import os
import sys
import requests
import json
from pathlib import Path
from dotenv import load_dotenv

# Add the app directory to Python path to import from app.py
sys.path.append(str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from app import send_sms, Provider, app, db

def generate_provider_connect_link(provider_id):
    """Generate Stripe Connect onboarding link for a specific provider"""
    try:
        print(f"🔗 Generating Connect link for {provider_id}...")
        
        response = requests.post(
            'https://stripe-45lh.onrender.com/provider/account-link',
            json={'providerId': provider_id},
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            connect_url = data.get('account_link_url') or data.get('url') or data.get('link')
            if connect_url:
                print(f"✅ Connect link generated for {provider_id}")
                return connect_url
            else:
                print(f"⚠️ No URL found in response for {provider_id}: {data}")
                return None
        else:
            print(f"❌ Failed to generate link for {provider_id}: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error generating Connect link for {provider_id}: {str(e)}")
        return None

def send_connect_link_sms(provider_id, provider_name, provider_phone, connect_url):
    """Send Connect link via SMS to provider"""
    try:
        message = (
            f"Gold Touch Mobile - Hi {provider_name}! 👋\n\n"
            f"We're migrating to Stripe for faster payments! Clients will now pay at the end of service with same-day payouts to you.\n\n"
            f"Complete your payment setup here:\n"
            f"{connect_url}\n\n"
            f"This secure link sets up your Stripe account for direct deposits. Questions? Reply to this message."
        )
        
        print(f"📱 Sending SMS to {provider_name} ({provider_phone})...")
        success, result = send_sms(provider_phone, message)
        
        if success:
            print(f"✅ SMS sent successfully to {provider_name}")
            return True, result
        else:
            print(f"❌ Failed to send SMS to {provider_name}: {result}")
            return False, result
            
    except Exception as e:
        print(f"❌ Error sending SMS to {provider_name}: {str(e)}")
        return False, str(e)

def load_providers_from_json():
    """Load providers from JSON file as backup"""
    try:
        providers_file = Path(__file__).parent / 'providers.json'
        with open(providers_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not load providers.json: {e}")
        return {}

def mass_send_connect_links(test_mode=False, specific_providers=None):
    """
    Mass send Connect links to all providers
    
    Args:
        test_mode (bool): If True, only send to test_provider
        specific_providers (list): List of provider IDs to send to (optional)
    """
    print("🚀 Starting mass Connect link distribution...")
    print("=" * 60)
    
    results = {
        'success': [],
        'failed_link_generation': [],
        'failed_sms': [],
        'skipped': []
    }
    
    try:
        with app.app_context():
            # Get providers from database first
            db_providers = Provider.query.all()
            providers_dict = {}
            
            if db_providers:
                print(f"📊 Found {len(db_providers)} providers in database")
                for p in db_providers:
                    providers_dict[p.id] = {'name': p.name, 'phone': p.phone}
            
            # Always also load from JSON to get any missing providers
            json_providers = load_providers_from_json()
            if json_providers:
                print(f"📊 Found {len(json_providers)} providers in JSON file")
                # Merge JSON providers (JSON takes precedence for conflicts)
                for pid, pinfo in json_providers.items():
                    providers_dict[pid] = pinfo
                print(f"📊 Total providers after merge: {len(providers_dict)}")
            
            if not providers_dict:
                print("❌ No providers found in database or JSON file!")
                return results
            
            # Filter providers if specified
            if test_mode:
                if 'test_provider' in providers_dict:
                    providers_dict = {'test_provider': providers_dict['test_provider']}
                else:
                    print("❌ test_provider not found!")
                    return results
                    
            if specific_providers:
                filtered_dict = {}
                for pid in specific_providers:
                    if pid in providers_dict:
                        filtered_dict[pid] = providers_dict[pid]
                    else:
                        print(f"⚠️ Provider {pid} not found, skipping...")
                providers_dict = filtered_dict
            
            print(f"📋 Processing {len(providers_dict)} providers...")
            print("-" * 40)
            
            for provider_id, provider_info in providers_dict.items():
                provider_name = provider_info['name']
                provider_phone = provider_info['phone']
                
                print(f"\n🔄 Processing {provider_name} ({provider_id})...")
                
                # Generate Connect link
                connect_url = generate_provider_connect_link(provider_id)
                
                if not connect_url:
                    results['failed_link_generation'].append({
                        'provider_id': provider_id,
                        'name': provider_name,
                        'phone': provider_phone,
                        'error': 'Could not generate Connect link'
                    })
                    continue
                
                # Send SMS
                sms_success, sms_result = send_connect_link_sms(
                    provider_id, provider_name, provider_phone, connect_url
                )
                
                if sms_success:
                    results['success'].append({
                        'provider_id': provider_id,
                        'name': provider_name,
                        'phone': provider_phone,
                        'connect_url': connect_url
                    })
                else:
                    results['failed_sms'].append({
                        'provider_id': provider_id,
                        'name': provider_name,
                        'phone': provider_phone,
                        'connect_url': connect_url,
                        'error': sms_result
                    })
                
                # Small delay to avoid rate limiting
                import time
                time.sleep(1)
    
    except Exception as e:
        print(f"❌ Critical error during mass send: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 MASS SEND SUMMARY")
    print("=" * 60)
    print(f"✅ Successfully sent: {len(results['success'])}")
    print(f"❌ Failed link generation: {len(results['failed_link_generation'])}")
    print(f"❌ Failed SMS: {len(results['failed_sms'])}")
    print(f"⏭️ Skipped: {len(results['skipped'])}")
    
    if results['success']:
        print(f"\n✅ SUCCESS ({len(results['success'])}):")
        for item in results['success']:
            print(f"  • {item['name']} ({item['provider_id']}) - {item['phone']}")
    
    if results['failed_link_generation']:
        print(f"\n❌ FAILED LINK GENERATION ({len(results['failed_link_generation'])}):")
        for item in results['failed_link_generation']:
            print(f"  • {item['name']} ({item['provider_id']}) - {item['error']}")
    
    if results['failed_sms']:
        print(f"\n❌ FAILED SMS ({len(results['failed_sms'])}):")
        for item in results['failed_sms']:
            print(f"  • {item['name']} ({item['provider_id']}) - {item['error']}")
    
    return results

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Mass send Stripe Connect links to providers')
    parser.add_argument('--test', action='store_true', help='Test mode - only send to test_provider')
    parser.add_argument('--providers', nargs='+', help='Specific provider IDs to send to')
    parser.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    if args.test:
        print("🧪 TEST MODE - Only sending to test_provider")
    elif args.providers:
        print(f"🎯 TARGETED MODE - Sending to: {', '.join(args.providers)}")
    else:
        print("🌍 FULL MODE - Sending to ALL providers")
    
    if not args.confirm:
        response = input("\nAre you sure you want to proceed? (yes/no): ").lower().strip()
        if response not in ['yes', 'y']:
            print("❌ Cancelled by user")
            sys.exit(0)
    
    print("\n🚀 Starting mass send...")
    results = mass_send_connect_links(
        test_mode=args.test,
        specific_providers=args.providers
    )
    
    print(f"\n🏁 Complete! Check the summary above for results.")
