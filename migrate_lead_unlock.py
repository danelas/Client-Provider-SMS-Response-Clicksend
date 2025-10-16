#!/usr/bin/env python3
"""
Database migration script for Lead Unlock system
Creates the new tables: leads and lead_unlocks
"""

import os
import sys
from dotenv import load_dotenv
from models import db, Lead, LeadUnlock
from app import app

# Load environment variables
load_dotenv()

def create_tables():
    """Create the new tables for lead unlock system"""
    try:
        with app.app_context():
            print("🔄 Creating Lead Unlock system tables...")
            
            # Create tables
            db.create_all()
            
            print("✅ Tables created successfully!")
            print("   - leads table")
            print("   - lead_unlocks table")
            
            # Verify tables exist
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            
            if 'leads' in tables and 'lead_unlocks' in tables:
                print("✅ Table verification passed")
                return True
            else:
                print("❌ Table verification failed")
                print(f"   Available tables: {tables}")
                return False
                
    except Exception as e:
        print(f"❌ Error creating tables: {str(e)}")
        return False

def create_sample_data():
    """Create some sample lead data for testing"""
    try:
        with app.app_context():
            print("\n🔄 Creating sample lead data...")
            
            # Check if sample data already exists
            existing_lead = Lead.query.filter_by(id='lead_sample01').first()
            if existing_lead:
                print("⚠️ Sample data already exists, skipping creation")
                return True
            
            # Create sample lead
            sample_lead = Lead(
                id='lead_sample01',
                city='Miami',
                service_type='60 min Mobile Massage',
                preferred_time_window='Evening (6-9 PM)',
                budget_range='$150-200',
                notes_snippet='Client prefers deep tissue massage, has lower back pain',
                client_name='John Smith',
                client_phone='+15551234567',
                client_email='john.smith@email.com',
                exact_address='456 Collins Avenue, Miami Beach, FL 33140'
            )
            
            db.session.add(sample_lead)
            db.session.commit()
            
            print("✅ Sample lead created:")
            print(f"   Lead ID: {sample_lead.id}")
            print(f"   City: {sample_lead.city}")
            print(f"   Service: {sample_lead.service_type}")
            print(f"   Client: {sample_lead.client_name}")
            
            return True
            
    except Exception as e:
        print(f"❌ Error creating sample data: {str(e)}")
        return False

def verify_migration():
    """Verify the migration was successful"""
    try:
        with app.app_context():
            print("\n🔍 Verifying migration...")
            
            # Check table structure
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            
            # Check leads table
            leads_columns = [col['name'] for col in inspector.get_columns('leads')]
            expected_leads_columns = [
                'id', 'city', 'service_type', 'preferred_time_window', 
                'budget_range', 'notes_snippet', 'client_name', 
                'client_phone', 'client_email', 'exact_address',
                'created_at', 'updated_at'
            ]
            
            missing_leads_cols = [col for col in expected_leads_columns if col not in leads_columns]
            if missing_leads_cols:
                print(f"❌ Missing columns in leads table: {missing_leads_cols}")
                return False
            
            # Check lead_unlocks table
            unlocks_columns = [col['name'] for col in inspector.get_columns('lead_unlocks')]
            expected_unlocks_columns = [
                'id', 'lead_id', 'provider_id', 'status', 'last_sent_at',
                'payment_link_url', 'checkout_session_id', 'unlocked_at',
                'idempotency_key', 'ttl_expires_at', 'price_cents',
                'currency', 'ttl_hours', 'created_at', 'updated_at'
            ]
            
            missing_unlocks_cols = [col for col in expected_unlocks_columns if col not in unlocks_columns]
            if missing_unlocks_cols:
                print(f"❌ Missing columns in lead_unlocks table: {missing_unlocks_cols}")
                return False
            
            # Test basic queries
            leads_count = Lead.query.count()
            unlocks_count = LeadUnlock.query.count()
            
            print("✅ Migration verification passed!")
            print(f"   Leads table: {len(leads_columns)} columns, {leads_count} records")
            print(f"   Lead_unlocks table: {len(unlocks_columns)} columns, {unlocks_count} records")
            
            return True
            
    except Exception as e:
        print(f"❌ Error verifying migration: {str(e)}")
        return False

def main():
    """Run the migration"""
    print("🚀 Lead Unlock System Database Migration")
    print("=" * 50)
    
    # Step 1: Create tables
    if not create_tables():
        print("❌ Migration failed at table creation step")
        sys.exit(1)
    
    # Step 2: Create sample data
    if not create_sample_data():
        print("⚠️ Sample data creation failed, but migration can continue")
    
    # Step 3: Verify migration
    if not verify_migration():
        print("❌ Migration verification failed")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("🎉 Migration completed successfully!")
    print()
    print("📋 What was created:")
    print("   ✅ leads table - stores client inquiry information")
    print("   ✅ lead_unlocks table - tracks provider unlock payments")
    print("   ✅ Sample lead data for testing")
    print()
    print("🔧 Next steps:")
    print("   1. Configure Stripe API keys in .env file:")
    print("      STRIPE_SECRET_KEY=sk_test_...")
    print("      STRIPE_WEBHOOK_SECRET=whsec_...")
    print("   2. Test the system with: python test_lead_unlock.py")
    print("   3. Set up Stripe webhook endpoint at: /webhook/stripe")

if __name__ == "__main__":
    main()
