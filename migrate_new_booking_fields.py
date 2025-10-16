#!/usr/bin/env python3
"""
Database migration script to add new booking fields.

This script adds the following new fields to the bookings table:
- city_zip: City or ZIP code
- session_length: Session Length Preference  
- location_type: Location Type (Mobile/In-Studio)
- contact_preference: How would you like to be contacted?

Usage:
    python migrate_new_booking_fields.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError

# Add the current directory to the path so we can import our models
sys.path.append(str(Path(__file__).parent))

# Load environment variables
load_dotenv()

def get_database_url():
    """Get the database URL from environment variables"""
    database_url = os.getenv('DATABASE_URL')
    if database_url and database_url.startswith('postgres://'):
        # Fix for newer SQLAlchemy versions that require postgresql://
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    return database_url or 'sqlite:///bookings.db'

def check_column_exists(engine, table_name, column_name):
    """Check if a column exists in a table"""
    try:
        inspector = inspect(engine)
        columns = inspector.get_columns(table_name)
        return any(col['name'] == column_name for col in columns)
    except Exception as e:
        print(f"Error checking column {column_name}: {e}")
        return False

def add_column_if_not_exists(engine, table_name, column_name, column_definition):
    """Add a column to a table if it doesn't already exist"""
    try:
        if check_column_exists(engine, table_name, column_name):
            print(f"✓ Column '{column_name}' already exists in table '{table_name}'")
            return True
        
        # Add the column
        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        print(f"Adding column: {sql}")
        
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        
        print(f"✓ Successfully added column '{column_name}' to table '{table_name}'")
        return True
        
    except SQLAlchemyError as e:
        print(f"✗ Error adding column '{column_name}': {e}")
        return False

def main():
    """Run the migration"""
    print("=== Booking Fields Migration Script ===")
    print("Adding new fields to bookings table...")
    
    # Get database URL
    database_url = get_database_url()
    print(f"Database URL: {database_url[:20]}...")
    
    try:
        # Create engine
        if 'postgresql://' in database_url:
            engine = create_engine(
                database_url,
                connect_args={
                    'sslmode': 'prefer',
                    'connect_timeout': 10,
                    'application_name': 'booking_migration'
                },
                pool_pre_ping=True
            )
        else:
            engine = create_engine(database_url)
        
        # Test connection
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print("✓ Database connection successful")
        
        # Check if bookings table exists
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'bookings' not in tables:
            print("⚠️ Bookings table does not exist. Creating tables...")
            # Import and create all tables
            from models import db
            from flask import Flask
            
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = database_url
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            
            if 'postgresql://' in database_url:
                app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
                    'connect_args': {
                        'sslmode': 'prefer',
                        'connect_timeout': 10,
                        'application_name': 'booking_migration'
                    },
                    'pool_pre_ping': True
                }
            
            db.init_app(app)
            
            with app.app_context():
                db.create_all()
            
            print("✓ All tables created")
            return
        
        # Define new columns to add
        new_columns = [
            ('city_zip', 'VARCHAR(100)'),
            ('session_length', 'VARCHAR(50)'),
            ('location_type', 'VARCHAR(50)'),
            ('contact_preference', 'VARCHAR(50)')
        ]
        
        # Add each new column
        success_count = 0
        for column_name, column_definition in new_columns:
            if add_column_if_not_exists(engine, 'bookings', column_name, column_definition):
                success_count += 1
        
        print(f"\n=== Migration Summary ===")
        print(f"Successfully processed {success_count}/{len(new_columns)} columns")
        
        if success_count == len(new_columns):
            print("✅ Migration completed successfully!")
        else:
            print("⚠️ Migration completed with some issues")
        
        # Verify the new columns exist
        print("\n=== Verification ===")
        inspector = inspect(engine)
        columns = inspector.get_columns('bookings')
        column_names = [col['name'] for col in columns]
        
        for column_name, _ in new_columns:
            if column_name in column_names:
                print(f"✓ {column_name}: Present")
            else:
                print(f"✗ {column_name}: Missing")
        
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
