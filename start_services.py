#!/usr/bin/env python3
"""
Service startup script for Lead Unlock SMS system
Starts both Flask app and Node.js Stripe service with proper coordination
"""

import subprocess
import time
import requests
import os
import sys
from pathlib import Path

# Configuration
FLASK_PORT = 5000
NODEJS_PORT = 3000
STRIPE_SERVICE_PATH = Path("../stripe-payment-service")
STARTUP_TIMEOUT = 30  # seconds

def check_port_available(port):
    """Check if a port is available"""
    try:
        response = requests.get(f"http://localhost:{port}/health", timeout=2)
        return False  # Port is in use
    except:
        return True  # Port is available

def wait_for_service(url, service_name, timeout=30):
    """Wait for a service to become healthy"""
    print(f"⏳ Waiting for {service_name} to start...")
    
    for i in range(timeout):
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                print(f"✅ {service_name} is healthy!")
                return True
        except:
            pass
        
        time.sleep(1)
        if i % 5 == 0 and i > 0:
            print(f"   Still waiting... ({i}/{timeout}s)")
    
    print(f"❌ {service_name} failed to start within {timeout} seconds")
    return False

def start_nodejs_service():
    """Start the Node.js Stripe service"""
    print("🚀 Starting Node.js Stripe Service...")
    
    if not STRIPE_SERVICE_PATH.exists():
        print(f"❌ Stripe service directory not found: {STRIPE_SERVICE_PATH}")
        print("   Please ensure the stripe-payment-service directory exists")
        return None
    
    # Check if port is available
    if not check_port_available(NODEJS_PORT):
        print(f"⚠️ Port {NODEJS_PORT} is already in use")
        print("   Assuming Node.js service is already running")
        return None
    
    try:
        # Start Node.js service
        process = subprocess.Popen(
            ["npm", "start"],
            cwd=STRIPE_SERVICE_PATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
        )
        
        # Wait for service to be healthy
        if wait_for_service(f"http://localhost:{NODEJS_PORT}/health", "Node.js Service"):
            return process
        else:
            process.terminate()
            return None
            
    except FileNotFoundError:
        print("❌ npm not found. Please install Node.js and npm")
        return None
    except Exception as e:
        print(f"❌ Failed to start Node.js service: {str(e)}")
        return None

def start_flask_app():
    """Start the Flask application"""
    print("🚀 Starting Flask Application...")
    
    # Check if port is available
    if not check_port_available(FLASK_PORT):
        print(f"⚠️ Port {FLASK_PORT} is already in use")
        print("   Assuming Flask app is already running")
        return None
    
    try:
        # Start Flask app
        process = subprocess.Popen(
            [sys.executable, "app.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
        )
        
        # Wait for service to be healthy
        if wait_for_service(f"http://localhost:{FLASK_PORT}/health", "Flask App"):
            return process
        else:
            process.terminate()
            return None
            
    except Exception as e:
        print(f"❌ Failed to start Flask app: {str(e)}")
        return None

def test_integration():
    """Test the integration between services"""
    print("🔧 Testing Service Integration...")
    
    try:
        # Test Flask app health
        response = requests.get(f"http://localhost:{FLASK_PORT}/health", timeout=5)
        if response.status_code != 200:
            print("❌ Flask app health check failed")
            return False
        
        # Test Node.js service health via Flask proxy
        response = requests.get(f"http://localhost:{FLASK_PORT}/api/stripe-service/health", timeout=5)
        if response.status_code != 200:
            print("❌ Node.js service health check via Flask proxy failed")
            return False
        
        result = response.json()
        if not result.get('stripe_service_healthy'):
            print(f"❌ Node.js service reports unhealthy: {result}")
            return False
        
        print("✅ Integration test passed!")
        return True
        
    except Exception as e:
        print(f"❌ Integration test failed: {str(e)}")
        return False

def main():
    """Main startup sequence"""
    print("🎯 Lead Unlock SMS System Startup")
    print("=" * 50)
    
    processes = []
    
    try:
        # Step 1: Start Node.js service first (Flask depends on it)
        nodejs_process = start_nodejs_service()
        if nodejs_process:
            processes.append(("Node.js Service", nodejs_process))
        
        # Step 2: Start Flask app
        flask_process = start_flask_app()
        if flask_process:
            processes.append(("Flask App", flask_process))
        
        # Step 3: Test integration
        if not test_integration():
            print("❌ Integration test failed. Check service logs.")
            return
        
        print("\n" + "=" * 50)
        print("🎉 All services started successfully!")
        print()
        print("📋 Service URLs:")
        print(f"   Flask App: http://localhost:{FLASK_PORT}")
        print(f"   Node.js Service: http://localhost:{NODEJS_PORT}")
        print()
        print("🧪 Test the system:")
        print("   python test_lead_unlock.py")
        print()
        print("🛑 To stop services:")
        print("   Press Ctrl+C or close the console windows")
        
        # Keep script running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Shutting down services...")
            
    except KeyboardInterrupt:
        print("\n🛑 Startup interrupted")
    
    finally:
        # Clean up processes
        for name, process in processes:
            try:
                print(f"   Stopping {name}...")
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass

if __name__ == "__main__":
    main()
