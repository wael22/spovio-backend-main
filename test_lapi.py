import requests
from requests.auth import HTTPDigestAuth
import json
from datetime import datetime, timedelta

# Configuration
IP = "192.168.100.208"
PORT = 80
USERNAME = "admin"
PASSWORD = "password" # Will start with default, if fails, user might need to change

# Construct Base URL
base_url = f"http://{IP}:{PORT}/LAPI/V1.0"

def test_lapi():
    print(f"Testing LAPI connection to {base_url}...")
    
    # Session for persistence
    session = requests.Session()
    session.auth = HTTPDigestAuth(USERNAME, PASSWORD)
    session.headers.update({"Content-Type": "application/json"})
    
    # 1. Test Device Info (Basic Auth Check)
    try:
        url = f"{base_url}/System/Device/Info"
        print(f"GET {url}")
        resp = session.get(url, timeout=5)
        
        if resp.status_code == 200:
            print("✅ Device Info Success!")
            print(json.dumps(resp.json(), indent=2))
        elif resp.status_code == 401:
            print("❌ Authentication Failed (401). Check password.")
            return
        else:
            print(f"⚠️ Device Info Failed: {resp.status_code} - {resp.text}")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return

    # 2. Test Recording Query (The critical part)
    print("\nTesting Recording Query...")
    try:
        url = f"{base_url}/Recording/Query"
        
        # Query for the last 24 hours
        now = datetime.now()
        start_time = now - timedelta(hours=24)
        
        payload = {
            "BeginTime": int(start_time.timestamp()),
            "EndTime": int(now.timestamp()),
            "Type": 1, # Record Type (1=All?)
            "Offset": 0,
            "Limit": 10
        }
        
        print(f"POST {url} with payload: {payload}")
        resp = session.post(url, json=payload, timeout=5)
        
        if resp.status_code == 200:
            print("✅ Recording Query Success!")
            data = resp.json()
            print(json.dumps(data, indent=2))
            
            if "Response" in data and "Data" in data["Response"] and "Num" in data["Response"]["Data"]:
                count = data["Response"]["Data"]["Num"]
                print(f"Found {count} recordings.")
        else:
            print(f"❌ Recording Query Failed: {resp.status_code} - {resp.text}")
            
    except Exception as e:
        print(f"❌ Query Error: {e}")

if __name__ == "__main__":
    # We need the real password. I will use the one from the script if I can find it, 
    # but for now I'll ask the user to edit it if 'password' fails, 
    # OR I can try to import it from the app context if I'm clever.
    # Let's try to use the hardcoded one from previous steps "Sgs_2025_"
    PASSWORD = "Sgs_2025_"
    test_lapi()
