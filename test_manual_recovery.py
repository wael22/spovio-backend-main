import requests
import json
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

BASE_URL = "http://localhost:5000"

def login(email, password, is_superadmin=False):
    endpoint = "/api/auth/super-admin-login" if is_superadmin else "/api/auth/login"
    response = requests.post(f"{BASE_URL}{endpoint}", json={
        "email": email,
        "password": password
    })
    if response.status_code != 200:
        print(f"Login failed for {email}: {response.text}")
        return None
    return response.json().get('token') or response.json().get('access_token')

def test_recovery_flow():
    print("=== Testing Video Recovery Flow ===")
    
    # 1. Login as Player (to report)
    # Assuming 'test@test.com' exists, or we use a known user
    # If not, we might need to create one or use admin credential for reporting too (if allowed? No, recovery report checks user?)
    # code: user_id = current_user.id
    
    # Use superadmin for both reporting and verifying
    # Email: superadmin@spovio.net, Password: Spovio2024!
    admin_email = "superadmin@spovio.net"
    admin_pass = "Spovio2024!"

    player_token = login(admin_email, admin_pass, is_superadmin=True)
    
    if not player_token:
        print("CRITICAL: Cannot authenticate as superadmin.")
        return

    admin_token = player_token

    # 3. Report Missing Video
    print("\n[Step 1] Reporting Missing Video...")
    headers = {"Authorization": f"Bearer {player_token}"}
    
    # We need a valid court_id. Let's fetch courts first or use ID 1
    # If we don't have a valid court, we might fail on constraint?
    # recovery_service just uses court_id to get camera url.
    
    report_data = {
        "court_id": 1, 
        "match_start": "2024-01-01T10:00:00Z",
        "match_end": "2024-01-01T11:30:00Z",
        "description": "Test recovery request from script"
    }
    
    response = requests.post(f"{BASE_URL}/api/recovery/report", json=report_data, headers=headers)
    
    if response.status_code == 201:
        data = response.json()
        request_id = data['request_id']
        print(f"SUCCESS: Request created. ID: {request_id}, Status: {data.get('status')}")
    else:
        print(f"FAILED: {response.text}")
        # If it failed because of "Court not found" or similar, we should stop
        if "Foreign key constraint" in response.text or "court" in response.text.lower():
             print("Please ensure court_id 1 exists.")
        return

    # 4. Verify Admin sees it
    print("\n[Step 2] Verifying Admin Visibility...")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    
    response = requests.get(f"{BASE_URL}/api/recovery/requests", headers=admin_headers)
    
    if response.status_code == 200:
        data = response.json()
        requests_list = data.get('requests', [])
        # Find our request
        found = next((r for r in requests_list if r['id'] == request_id), None)
        if found:
            print(f"SUCCESS: Admin found request #{request_id}")
            print(f"Status: {found['status']}")
            print(f"Type: {found['request_type']}")
        else:
            print(f"FAILED: Request #{request_id} not found in admin list.")
    else:
        print(f"FAILED to list requests: {response.text}")

if __name__ == "__main__":
    test_recovery_flow()
