#!/usr/bin/env python3
"""
Migration script to add the add_ons column to the bookings table.
This fixes the PostgreSQL schema to match the updated models.py
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

def migrate_add_ons_column():
    """Add the add_ons column to the bookings table if it doesn't exist"""
    
    # Get database URL from environment variable
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set")
        return False
    
    try:
        # Create engine
        engine = create_engine(database_url)
        
        print("Connecting to PostgreSQL database...")
        
        with engine.connect() as conn:
            # Check if add_ons column already exists
            check_query = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'bookings' AND column_name = 'add_ons';
            """)
            
            result = conn.execute(check_query)
            existing_column = result.fetchone()
            
            if existing_column:
                print("✅ add_ons column already exists in bookings table")
                return True
            
            # Add the add_ons column
            print("Adding add_ons column to bookings table...")
            alter_query = text("""
                ALTER TABLE bookings 
                ADD COLUMN add_ons TEXT;
            """)
            
            conn.execute(alter_query)
            conn.commit()
            
            print("✅ Successfully added add_ons column to bookings table")
            
            # Verify the column was added
            verify_result = conn.execute(check_query)
            if verify_result.fetchone():
                print("✅ Migration completed successfully!")
                return True
            else:
                print("❌ Migration verification failed")
                return False
                
    except ProgrammingError as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("=== PostgreSQL Schema Migration: Add add_ons Column ===")
    success = migrate_add_ons_column()
    if success:
        print("\n🎉 Migration completed successfully!")
        sys.exit(0)
    else:
        print("\n💥 Migration failed!")
        sys.exit(1)
