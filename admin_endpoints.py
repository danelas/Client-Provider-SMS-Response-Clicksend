"""
Admin endpoints to add to your main app.py
These provide web-based access to export customer data and manage providers
"""

from flask import jsonify, request, send_file
import csv
import json
import io
from datetime import datetime
from collections import defaultdict

# Add these endpoints to your app.py file:

@app.route('/admin/export-customers', methods=['GET'])
def admin_export_customers():
    """Admin endpoint to export customer data"""
    try:
        format_type = request.args.get('format', 'json')  # json, csv, or both
        include_duplicates = request.args.get('duplicates', 'false').lower() == 'true'
        
        customers_data = []
        phone_to_customer = {}
        
        # Get all bookings
        bookings = Booking.query.order_by(Booking.created_at.desc()).all()
        
        for booking in bookings:
            if not booking.customer_phone:
                continue
                
            cleaned_phone = clean_phone_number(booking.customer_phone)
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
                'add_ons_used': [getattr(booking, 'add_ons', '')] if getattr(booking, 'add_ons', '') else [],
                'booking_ids': [booking.id]
            }
            
            if include_duplicates:
                customers_data.append(customer_data)
            else:
                # Deduplicate by phone
                if cleaned_phone in phone_to_customer:
                    existing = phone_to_customer[cleaned_phone]
                    
                    # Update name if current has name and existing doesn't
                    if customer_data['customer_name'] != 'Unknown' and existing['customer_name'] == 'Unknown':
                        existing['customer_name'] = customer_data['customer_name']
                    
                    # Update dates
                    if booking.created_at:
                        booking_date = booking.created_at.isoformat()
                        if booking_date < existing['first_booking_date']:
                            existing['first_booking_date'] = booking_date
                        if booking_date > existing['last_booking_date']:
                            existing['last_booking_date'] = booking_date
                    
                    # Increment and merge
                    existing['total_bookings'] += 1
                    existing['booking_statuses'].append(booking.status)
                    
                    if booking.service_type and booking.service_type not in existing['services_used']:
                        existing['services_used'].append(booking.service_type)
                    
                    if booking.provider_id and booking.provider_id not in existing['providers_used']:
                        existing['providers_used'].append(booking.provider_id)
                    
                    if booking.address and booking.address not in existing['addresses_used']:
                        existing['addresses_used'].append(booking.address)
                    
                    addon = getattr(booking, 'add_ons', '')
                    if addon and addon not in existing['add_ons_used']:
                        existing['add_ons_used'].append(addon)
                    
                    existing['booking_ids'].append(booking.id)
                    
                else:
                    phone_to_customer[cleaned_phone] = customer_data
                    customers_data.append(customer_data)
        
        if not include_duplicates:
            customers_data = list(phone_to_customer.values())
        
        # Sort by total bookings
        customers_data.sort(key=lambda x: x['total_bookings'], reverse=True)
        
        # Generate statistics
        total_customers = len(customers_data)
        total_bookings = sum(c['total_bookings'] for c in customers_data)
        repeat_customers = sum(1 for c in customers_data if c['total_bookings'] > 1)
        
        stats = {
            'total_customers': total_customers,
            'total_bookings': total_bookings,
            'repeat_customers': repeat_customers,
            'one_time_customers': total_customers - repeat_customers,
            'repeat_rate': (repeat_customers / total_customers * 100) if total_customers > 0 else 0,
            'avg_bookings_per_customer': (total_bookings / total_customers) if total_customers > 0 else 0
        }
        
        if format_type == 'csv':
            # Return CSV file
            output = io.StringIO()
            if customers_data:
                fieldnames = [
                    'customer_name', 'customer_phone', 'original_phone_format',
                    'first_booking_date', 'last_booking_date', 'total_bookings',
                    'booking_statuses', 'services_used', 'providers_used',
                    'addresses_used', 'add_ons_used', 'booking_ids'
                ]
                
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                
                for customer in customers_data:
                    row = customer.copy()
                    # Convert lists to strings for CSV
                    for key in ['booking_statuses', 'services_used', 'providers_used', 
                               'addresses_used', 'add_ons_used', 'booking_ids']:
                        if isinstance(row[key], list):
                            row[key] = '; '.join(str(item) for item in row[key] if item)
                    writer.writerow(row)
            
            output.seek(0)
            
            # Create file-like object for download
            mem = io.BytesIO()
            mem.write(output.getvalue().encode('utf-8'))
            mem.seek(0)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'customers_export_{timestamp}.csv'
            
            return send_file(
                mem,
                as_attachment=True,
                download_name=filename,
                mimetype='text/csv'
            )
        
        else:
            # Return JSON
            return jsonify({
                'status': 'success',
                'statistics': stats,
                'customers': customers_data,
                'export_info': {
                    'format': format_type,
                    'include_duplicates': include_duplicates,
                    'exported_at': datetime.now().isoformat(),
                    'total_records': len(customers_data)
                }
            })
    
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__
        }), 500

@app.route('/admin/customer-stats', methods=['GET'])
def admin_customer_stats():
    """Get customer statistics without full export"""
    try:
        bookings = Booking.query.all()
        
        # Quick stats
        total_bookings = len(bookings)
        unique_phones = set()
        phone_booking_counts = defaultdict(int)
        
        for booking in bookings:
            if booking.customer_phone:
                cleaned_phone = clean_phone_number(booking.customer_phone)
                if cleaned_phone:
                    unique_phones.add(cleaned_phone)
                    phone_booking_counts[cleaned_phone] += 1
        
        total_customers = len(unique_phones)
        repeat_customers = sum(1 for count in phone_booking_counts.values() if count > 1)
        
        # Service popularity
        service_counts = defaultdict(int)
        for booking in bookings:
            if booking.service_type:
                service_counts[booking.service_type] += 1
        
        top_services = sorted(service_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Recent activity
        recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(10).all()
        recent_activity = []
        for booking in recent_bookings:
            recent_activity.append({
                'id': booking.id,
                'customer_phone': booking.customer_phone,
                'customer_name': getattr(booking, 'customer_name', 'Unknown'),
                'service_type': booking.service_type,
                'status': booking.status,
                'created_at': booking.created_at.isoformat() if booking.created_at else None
            })
        
        return jsonify({
            'status': 'success',
            'statistics': {
                'total_customers': total_customers,
                'total_bookings': total_bookings,
                'repeat_customers': repeat_customers,
                'one_time_customers': total_customers - repeat_customers,
                'repeat_rate': (repeat_customers / total_customers * 100) if total_customers > 0 else 0,
                'avg_bookings_per_customer': (total_bookings / total_customers) if total_customers > 0 else 0
            },
            'top_services': top_services,
            'recent_activity': recent_activity
        })
    
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# Usage instructions:
print("""
📝 ADD THESE ENDPOINTS TO YOUR app.py:

1. Copy the functions above into your app.py file
2. Deploy your updated app
3. Access the endpoints:

📊 Get customer statistics:
GET https://your-app.onrender.com/admin/customer-stats

📋 Export customer data (JSON):
GET https://your-app.onrender.com/admin/export-customers

📋 Export customer data (CSV download):
GET https://your-app.onrender.com/admin/export-customers?format=csv

📋 Include duplicate bookings:
GET https://your-app.onrender.com/admin/export-customers?duplicates=true

🔒 SECURITY NOTE: Add authentication to these endpoints in production!
""")
