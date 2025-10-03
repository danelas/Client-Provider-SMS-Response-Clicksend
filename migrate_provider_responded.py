#!/usr/bin/env python3
"""
Migration script to add provider_responded column to bookings table.
This prevents providers from accepting bookings after sending non-Y/N responses.
"""

import os
import sys
from pathlib import Path

# Add the project directory to Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

from dotenv import load_dotenv
load_dotenv()

# Import after setting up the path
from models import db, Booking
from app import app

def migrate_provider_responded():
    """Add provider_responded column to existing bookings table"""
    try:
        with app.app_context():
            # Check if the column already exists
            from sqlalchemy import text, inspect
            
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('bookings')]
            
            if 'provider_responded' in columns:
                print("✓ provider_responded column already exists")
                return True
            
            print("Adding provider_responded column to bookings table...")
            
            # Add the column with default value False
            db.session.execute(text('ALTER TABLE bookings ADD COLUMN provider_responded BOOLEAN DEFAULT FALSE'))
            
            # Update existing bookings based on their status
            # If booking is confirmed or rejected, provider must have responded
            db.session.execute(text("""
                UPDATE bookings 
                SET provider_responded = TRUE 
                WHERE status IN ('confirmed', 'rejected')
            """))
            
            db.session.commit()
            
            print("✓ Successfully added provider_responded column")
            print("✓ Updated existing confirmed/rejected bookings to provider_responded=TRUE")
            
            # Verify the migration
            result = db.session.execute(text("SELECT COUNT(*) FROM bookings WHERE provider_responded = TRUE")).fetchone()
            print(f"✓ {result[0]} existing bookings marked as provider_responded=TRUE")
            
            return True
            
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        db.session.rollback()
        return False

if __name__ == '__main__':
    print("=== Provider Response Migration ===")
    success = migrate_provider_responded()
    
    if success:
        print("\n✅ Migration completed successfully!")
        print("The system will now only accept Y/N responses as the first response from providers.")
    else:
        print("\n❌ Migration failed!")
        sys.exit(1)
