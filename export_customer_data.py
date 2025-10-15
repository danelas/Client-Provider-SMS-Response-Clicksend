#!/usr/bin/env python3
"""
Export customer data from booking history
Extracts all customers who have made bookings with Gold Touch Mobile
"""

import os
import sys
import csv
import json
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict

# Add the app directory to Python path to import from app.py
sys.path.append(str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from app import Booking, app, db

def clean_phone_for_export(phone):
    """Clean phone number for consistent formatting"""
    if not phone:
        return ""
    # Remove all non-digit characters except +
    cleaned = ''.join(c for c in str(phone) if c == '+' or c.isdigit())
    return cleaned

def export_customer_data(format_type='csv', include_duplicates=False):
    """
    Export customer data from bookings
    
    Args:
        format_type (str): 'csv', 'json', or 'both'
        include_duplicates (bool): If False, deduplicate by phone number
    """
    print("🚀 Extracting customer data from bookings...")
    print("=" * 60)
    
    customers_data = []
    phone_to_customer = {}  # For deduplication
    
    try:
        with app.app_context():
            # Get all bookings
            bookings = Booking.query.order_by(Booking.created_at.desc()).all()
            
            print(f"📊 Found {len(bookings)} total bookings")
            print("-" * 40)
            
            for booking in bookings:
                if not booking.customer_phone:
                    continue
                    
                cleaned_phone = clean_phone_for_export(booking.customer_phone)
                if not cleaned_phone:
                    continue
                
                customer_data = {
                    'customer_name': getattr(booking, 'customer_name', '') or 'Unknown',
                    'customer_phone': cleaned_phone,
                    'original_phone_format': booking.customer_phone,
                    'first_booking_date': booking.created_at.isoformat() if booking.created_at else '',
                    'last_booking_date': booking.created_at.isoformat() if booking.created_at else '',
                    'total_bookings': 1,
                    'booking_statuses': [booking.status],
                    'services_used': [booking.service_type] if booking.service_type else [],
                    'providers_used': [booking.provider_id] if booking.provider_id else [],
                    'addresses_used': [booking.address] if booking.address else [],
                    'add_ons_used': [booking.add_ons] if getattr(booking, 'add_ons', None) else [],
                    'booking_ids': [booking.id]
                }
                
                if include_duplicates:
                    # Include all bookings separately
                    customers_data.append(customer_data)
                else:
                    # Deduplicate and merge data by phone number
                    if cleaned_phone in phone_to_customer:
                        # Merge with existing customer data
                        existing = phone_to_customer[cleaned_phone]
                        
                        # Update name if current booking has a name and existing doesn't
                        if customer_data['customer_name'] != 'Unknown' and existing['customer_name'] == 'Unknown':
                            existing['customer_name'] = customer_data['customer_name']
                        
                        # Update dates
                        if booking.created_at:
                            booking_date = booking.created_at.isoformat()
                            if booking_date < existing['first_booking_date']:
                                existing['first_booking_date'] = booking_date
                            if booking_date > existing['last_booking_date']:
                                existing['last_booking_date'] = booking_date
                        
                        # Increment counters and add to lists
                        existing['total_bookings'] += 1
                        existing['booking_statuses'].append(booking.status)
                        
                        if booking.service_type and booking.service_type not in existing['services_used']:
                            existing['services_used'].append(booking.service_type)
                        
                        if booking.provider_id and booking.provider_id not in existing['providers_used']:
                            existing['providers_used'].append(booking.provider_id)
                        
                        if booking.address and booking.address not in existing['addresses_used']:
                            existing['addresses_used'].append(booking.address)
                        
                        if getattr(booking, 'add_ons', None) and booking.add_ons not in existing['add_ons_used']:
                            existing['add_ons_used'].append(booking.add_ons)
                        
                        existing['booking_ids'].append(booking.id)
                        
                    else:
                        # New customer
                        phone_to_customer[cleaned_phone] = customer_data
                        customers_data.append(customer_data)
            
            if not include_duplicates:
                customers_data = list(phone_to_customer.values())
            
            print(f"📋 Processed {len(customers_data)} unique customers")
            
            # Sort by total bookings (most active customers first)
            customers_data.sort(key=lambda x: x['total_bookings'], reverse=True)
            
            # Export data
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if format_type in ['csv', 'both']:
                csv_filename = f'customers_export_{timestamp}.csv'
                export_to_csv(customers_data, csv_filename)
            
            if format_type in ['json', 'both']:
                json_filename = f'customers_export_{timestamp}.json'
                export_to_json(customers_data, json_filename)
            
            # Print summary statistics
            print_customer_statistics(customers_data)
            
            return customers_data
    
    except Exception as e:
        print(f"❌ Error extracting customer data: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

def export_to_csv(customers_data, filename):
    """Export customer data to CSV file"""
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            if not customers_data:
                print("⚠️ No customer data to export")
                return
            
            fieldnames = [
                'customer_name', 'customer_phone', 'original_phone_format',
                'first_booking_date', 'last_booking_date', 'total_bookings',
                'booking_statuses', 'services_used', 'providers_used',
                'addresses_used', 'add_ons_used', 'booking_ids'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for customer in customers_data:
                # Convert lists to strings for CSV
                row = customer.copy()
                for key in ['booking_statuses', 'services_used', 'providers_used', 
                           'addresses_used', 'add_ons_used', 'booking_ids']:
                    if isinstance(row[key], list):
                        row[key] = '; '.join(str(item) for item in row[key] if item)
                
                writer.writerow(row)
        
        print(f"✅ CSV exported to: {filename}")
        
    except Exception as e:
        print(f"❌ Error exporting CSV: {str(e)}")

def export_to_json(customers_data, filename):
    """Export customer data to JSON file"""
    try:
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump(customers_data, jsonfile, indent=2, ensure_ascii=False)
        
        print(f"✅ JSON exported to: {filename}")
        
    except Exception as e:
        print(f"❌ Error exporting JSON: {str(e)}")

def print_customer_statistics(customers_data):
    """Print summary statistics about customers"""
    if not customers_data:
        return
    
    print("\n" + "=" * 60)
    print("📊 CUSTOMER STATISTICS")
    print("=" * 60)
    
    total_customers = len(customers_data)
    total_bookings = sum(c['total_bookings'] for c in customers_data)
    
    # Booking frequency analysis
    single_booking = sum(1 for c in customers_data if c['total_bookings'] == 1)
    repeat_customers = total_customers - single_booking
    
    # Most active customers
    top_customers = customers_data[:10]  # Already sorted by total_bookings
    
    print(f"👥 Total unique customers: {total_customers}")
    print(f"📅 Total bookings: {total_bookings}")
    print(f"🔄 Repeat customers: {repeat_customers} ({repeat_customers/total_customers*100:.1f}%)")
    print(f"1️⃣ One-time customers: {single_booking} ({single_booking/total_customers*100:.1f}%)")
    print(f"📈 Average bookings per customer: {total_bookings/total_customers:.1f}")
    
    if top_customers:
        print(f"\n🏆 TOP 10 MOST ACTIVE CUSTOMERS:")
        for i, customer in enumerate(top_customers, 1):
            name = customer['customer_name'] if customer['customer_name'] != 'Unknown' else 'No name'
            print(f"  {i:2d}. {name} ({customer['customer_phone']}) - {customer['total_bookings']} bookings")
    
    # Service popularity
    all_services = []
    for customer in customers_data:
        all_services.extend(customer['services_used'])
    
    service_counts = defaultdict(int)
    for service in all_services:
        if service:
            service_counts[service] += 1
    
    if service_counts:
        print(f"\n🎯 MOST POPULAR SERVICES:")
        sorted_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)
        for service, count in sorted_services[:10]:
            print(f"  • {service}: {count} customers")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Export customer data from bookings')
    parser.add_argument('--format', choices=['csv', 'json', 'both'], default='both',
                       help='Export format (default: both)')
    parser.add_argument('--include-duplicates', action='store_true',
                       help='Include duplicate entries (one per booking)')
    parser.add_argument('--confirm', action='store_true',
                       help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    if not args.confirm:
        print("📋 This will export all customer data from your booking history.")
        print(f"📁 Format: {args.format}")
        print(f"🔄 Include duplicates: {args.include_duplicates}")
        
        response = input("\nProceed with export? (yes/no): ").lower().strip()
        if response not in ['yes', 'y']:
            print("❌ Export cancelled")
            sys.exit(0)
    
    print("\n🚀 Starting customer data export...")
    customers = export_customer_data(
        format_type=args.format,
        include_duplicates=args.include_duplicates
    )
    
    print(f"\n🏁 Export complete! Found {len(customers)} customers.")
