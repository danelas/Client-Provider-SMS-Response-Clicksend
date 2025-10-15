"""
Functions to add to your main app.py for automatic Stripe provider syncing
"""

import requests
import os

def sync_provider_to_stripe_system(provider):
    """Auto-sync provider to Stripe system when added/updated"""
    try:
        stripe_payload = {
            'providerId': provider.id,
            'name': provider.name,
            'phone': provider.phone
        }
        
        # Try to register/update provider in Stripe system
        response = requests.post(
            'https://stripe-45lh.onrender.com/provider/register',
            json=stripe_payload,
            timeout=5
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Auto-synced {provider.name} to Stripe system")
            return True
        else:
            print(f"⚠️ Failed to auto-sync {provider.name} to Stripe: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"⚠️ Error auto-syncing {provider.name} to Stripe: {e}")
        return False

# Add this endpoint to your Stripe service (stripe system)
stripe_service_endpoint_code = '''
// Add this to your Stripe service index.js or routes file

app.post('/provider/register', async (req, res) => {
  try {
    const { providerId, name, phone } = req.body;
    
    if (!providerId || !name || !phone) {
      return res.status(400).json({ 
        error: 'Missing required fields: providerId, name, phone' 
      });
    }
    
    // Check if provider already exists
    let provider = await Provider.findOne({ where: { id: providerId } });
    
    if (provider) {
      // Update existing provider
      await provider.update({ name, phone });
      console.log(`Updated provider: ${providerId} - ${name}`);
      
      return res.status(200).json({
        message: 'Provider updated successfully',
        provider: { id: providerId, name, phone }
      });
    } else {
      // Create new provider
      provider = await Provider.create({
        id: providerId,
        name: name,
        phone: phone
      });
      
      console.log(`Created provider: ${providerId} - ${name}`);
      
      return res.status(201).json({
        message: 'Provider created successfully',
        provider: { id: providerId, name, phone }
      });
    }
    
  } catch (error) {
    console.error('Error registering provider:', error);
    res.status(500).json({ 
      error: 'Failed to register provider',
      details: error.message 
    });
  }
});
'''

print("📝 SETUP INSTRUCTIONS:")
print("=" * 50)
print("\n1. ADD TO YOUR STRIPE SERVICE:")
print("   Add this endpoint to your Stripe service:")
print(stripe_service_endpoint_code)

print("\n2. ADD TO YOUR MAIN APP.PY:")
print("   Import and use the sync function:")
print("""
from stripe_sync_functions import sync_provider_to_stripe_system

# Then call this after adding/updating providers:
# Example in your provider add/edit routes:

@app.route('/providers/add', methods=['POST'])
def add_provider():
    # ... your existing code to create provider ...
    new_provider = Provider(...)
    db.session.add(new_provider)
    db.session.commit()
    
    # Auto-sync to Stripe system
    sync_provider_to_stripe_system(new_provider)
    
    return redirect('/providers/manage')
""")
