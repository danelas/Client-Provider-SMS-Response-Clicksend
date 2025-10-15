#!/usr/bin/env python3
"""
Sync providers from main SMS system to Stripe system
This ensures both systems have the same provider data
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

from app import Provider, app, db

def sync_provider_to_stripe(provider_id, provider_name, provider_phone):
    """Sync a single provider to the Stripe system"""
    try:
        print(f"🔄 Syncing {provider_name} ({provider_id}) to Stripe system...")
        
        # Check if your Stripe service has a provider registration endpoint
        # You may need to add this endpoint to your Stripe service
        stripe_payload = {
            'providerId': provider_id,
            'name': provider_name,
            'phone': provider_phone
        }
        
        # Try to register/update provider in Stripe system
        response = requests.post(
            'https://stripe-45lh.onrender.com/provider/register',  # You'll need to add this endpoint
            json=stripe_payload,
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Successfully synced {provider_name} to Stripe")
            return True, "Success"
        else:
            print(f"❌ Failed to sync {provider_name}: {response.status_code} - {response.text}")
            return False, f"HTTP {response.status_code}: {response.text}"
            
    except Exception as e:
        print(f"❌ Error syncing {provider_name}: {str(e)}")
        return False, str(e)

def sync_all_providers_to_stripe():
    """Sync all providers from main database to Stripe system"""
    print("🚀 Starting provider sync to Stripe system...")
    print("=" * 60)
    
    results = {
        'success': [],
        'failed': [],
        'total': 0
    }
    
    try:
        with app.app_context():
            # Get all providers from main database
            providers = Provider.query.all()
            results['total'] = len(providers)
            
            print(f"📊 Found {len(providers)} providers to sync")
            print("-" * 40)
            
            for provider in providers:
                success, message = sync_provider_to_stripe(
                    provider.id, 
                    provider.name, 
                    provider.phone
                )
                
                if success:
                    results['success'].append({
                        'id': provider.id,
                        'name': provider.name,
                        'phone': provider.phone
                    })
                else:
                    results['failed'].append({
                        'id': provider.id,
                        'name': provider.name,
                        'phone': provider.phone,
                        'error': message
                    })
                
                # Small delay to avoid rate limiting
                import time
                time.sleep(0.5)
    
    except Exception as e:
        print(f"❌ Critical error during sync: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 SYNC SUMMARY")
    print("=" * 60)
    print(f"📋 Total providers: {results['total']}")
    print(f"✅ Successfully synced: {len(results['success'])}")
    print(f"❌ Failed to sync: {len(results['failed'])}")
    
    if results['success']:
        print(f"\n✅ SUCCESS ({len(results['success'])}):")
        for item in results['success']:
            print(f"  • {item['name']} ({item['id']}) - {item['phone']}")
    
    if results['failed']:
        print(f"\n❌ FAILED ({len(results['failed'])}):")
        for item in results['failed']:
            print(f"  • {item['name']} ({item['id']}) - {item['error']}")
    
    return results

def add_sync_to_provider_management():
    """Add automatic sync when providers are added/updated in main system"""
    sync_code = '''
# Add this to your app.py provider management functions

def sync_provider_to_stripe_system(provider):
    """Auto-sync provider to Stripe system when added/updated"""
    try:
        import requests
        
        stripe_payload = {
            'providerId': provider.id,
            'name': provider.name,
            'phone': provider.phone
        }
        
        response = requests.post(
            'https://stripe-45lh.onrender.com/provider/register',
            json=stripe_payload,
            timeout=5
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Auto-synced {provider.name} to Stripe")
        else:
            print(f"⚠️ Failed to auto-sync {provider.name} to Stripe")
            
    except Exception as e:
        print(f"⚠️ Error auto-syncing {provider.name}: {e}")

# Then call this function after adding/updating providers:
# sync_provider_to_stripe_system(new_provider)
'''
    
    print("📝 To enable automatic syncing, add this code to your app.py:")
    print(sync_code)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync providers to Stripe system')
    parser.add_argument('--sync-all', action='store_true', help='Sync all providers to Stripe')
    parser.add_argument('--show-code', action='store_true', help='Show auto-sync code to add to app.py')
    
    args = parser.parse_args()
    
    if args.show_code:
        add_sync_to_provider_management()
    elif args.sync_all:
        print("🔄 This will sync ALL providers to your Stripe system")
        response = input("Are you sure you want to proceed? (yes/no): ").lower().strip()
        if response in ['yes', 'y']:
            results = sync_all_providers_to_stripe()
        else:
            print("❌ Cancelled by user")
    else:
        print("Usage:")
        print("  python sync_providers_to_stripe.py --sync-all    # Sync all providers")
        print("  python sync_providers_to_stripe.py --show-code   # Show auto-sync code")
