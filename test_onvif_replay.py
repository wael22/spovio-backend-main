import requests
import uuid
import datetime
import base64
import hashlib
from urllib.parse import urlparse

# Configuration
IP = "192.168.100.208"
PORT = 80
USERNAME = "admin"
PASSWORD = "password" # Start with default, user might need to change to Sgs_2025_ if using script manually

def create_auth_header(username, password):
    # ONVIF UsernameToken Digest Authentication
    created = datetime.datetime.utcnow().isoformat() + "Z"
    nonce = uuid.uuid4().bytes
    nonce_b64 = base64.b64encode(nonce).decode()
    
    # Password Digest = Base64(SHA1(nonce + created + password))
    # Correct concatenation involves raw nonce bytes
    import hashlib
    digest = hashlib.sha1(nonce + created.encode('utf-8') + password.encode('utf-8')).digest()
    digest_b64 = base64.b64encode(digest).decode()
    
    return f'''
    <s:Header>
        <Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
            <UsernameToken>
                <Username>{username}</Username>
                <Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest_b64}</Password>
                <Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{nonce_b64}</Nonce>
                <Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>
            </UsernameToken>
        </Security>
    </s:Header>
    '''

def get_replay_uri(service_url, profile_token):
    print(f"Requesting Replay URI for profile {profile_token} from {service_url}...")
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    
    body = f'''<?xml version="1.0" encoding="utf-8"?>
        <s:Body>
            <trp:GetReplayUri>
                <trp:StreamSetup>
                    <tt:Stream xmlns:tt="http://www.onvif.org/ver10/schema">RTP-Unicast</tt:Stream>
                    <tt:Transport xmlns:tt="http://www.onvif.org/ver10/schema">
                        <tt:Protocol>RTSP</tt:Protocol>
                    </tt:Transport>
                </trp:StreamSetup>
                <trp:RecordingToken>recording_token_placeholder</trp:RecordingToken>
                <trp:ProfileToken>{profile_token}</trp:ProfileToken>
            </trp:GetReplayUri>
        </s:Body>
    </s:Envelope>'''
    
    # WAIT! GetReplayUri usually takes a RecordingToken OR a ProfileToken?
    # Spec says: StreamSetup, RecordingToken.
    # But usually for RTSP Replay we use GetReplayUri with a RecordingToken.
    # Let's try to get RECORDINGS first using FindRecordings?
    # But Uniview often uses ProfileToken for "live" replay if you don't specify recording.
    # Let's try REMOVING RecordingToken and keeping ProfileToken if the WSDL allows.
    # Actually, Uniview might require FindRecordings.
    # Let's try minimal request first.
    
    body = f'''<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trp="http://www.onvif.org/ver10/replay/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
        {create_auth_header(USERNAME, PASSWORD)}
        <s:Body>
            <trp:GetReplayUri>
                <trp:StreamSetup>
                    <tt:Stream>RTP-Unicast</tt:Stream>
                    <tt:Transport>
                        <tt:Protocol>RTSP</tt:Protocol>
                    </tt:Transport>
                </trp:StreamSetup>
                <trp:ProfileToken>{profile_token}</trp:ProfileToken>
            </trp:GetReplayUri>
        </s:Body>
    </s:Envelope>'''

    try:
        resp = requests.post(service_url, data=body, headers=headers, timeout=5)
        if resp.status_code == 200:
            print("✅ Success!")
            # Extract URI manually or with regex to avoid XML parsing issues
            import re
            match = re.search(r'<(?:\w+:)?Uri>(.*?)</(?:\w+:)?Uri>', resp.text)
            if match:
                return match.group(1)
            else:
                print("Uri tag not found in response")
                print(resp.text)
        else:
            print(f"❌ Failed: {resp.status_code}")
            print(resp.text) # Print FULL error
    except Exception as e:
        print(f"❌ Connection Error: {e}")

def get_profiles(device_service_url):
    print(f"Getting Profiles from {device_service_url}...")
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    
    body = f'''<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
        {create_auth_header(USERNAME, PASSWORD)}
        <s:Body>
            <trt:GetProfiles/>
        </s:Body>
    </s:Envelope>'''
    
    try:
        resp = requests.post(device_service_url, data=body, headers=headers, timeout=5)
        if resp.status_code == 200:
            import re
            # Find tokens: token="Profile_1"
            tokens = re.findall(r'token="([^"]+)"', resp.text)
            # Filter distinct
            return list(set(tokens))
        else:
            print(f"❌ GetProfiles Failed: {resp.status_code}")
            print(resp.text[:300])
            return []
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return []

def get_services(device_url):
    print(f"Getting Services from {device_url}...")
    # This is usually usually http://ip/onvif/device_service
    # But GetServices is newer. Let's assume standard Media and Replay paths if Getting Services fails.
    # Actually, Uniview often has Replay service at /onvif/replay_service or similar.
    # Let's try GetCapabilities first.
    
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    body = f'''<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
        {create_auth_header(USERNAME, PASSWORD)}
        <s:Body>
            <tds:GetCapabilities>
                <tds:Category>All</tds:Category>
            </tds:GetCapabilities>
        </s:Body>
    </s:Envelope>'''
    
    try:
        resp = requests.post(device_url, data=body, headers=headers, timeout=5)
        if resp.status_code == 200:
            import re
            media_url = None
            replay_url = None
            
            # Simple regex search for XAddr
            # We look for namespaces to identify services
            
            # Media Service
            media_match = re.search(r'<(\w+:)?Media>.*?<(\w+:)?XAddr>(.*?)</\2?XAddr>', resp.text, re.DOTALL)
            if media_match:
                media_url = media_match.group(3)
                print(f"Found Media Service: {media_url}")
            
            # Search Service
            search_match = re.search(r'<(\w+:)?Search>.*?<(\w+:)?XAddr>(.*?)</\2?XAddr>', resp.text, re.DOTALL)
            if search_match:
                search_url = search_match.group(3)
                print(f"Found Search Service: {search_url}")
            else:
                # Guess
                search_url = f"http://{IP}:{PORT}/onvif/search_service"
                print(f"Guessed Search Service: {search_url}")
            
            # Replay Service (search for namespace http://www.onvif.org/ver10/replay/wsdl)
            # This is harder with regex on full XML.
            # Let's just look for any XAddr that contains 'replay' or is in a Replay section
            
            # Look for Replay capabilities
            if 'http://www.onvif.org/ver10/replay/wsdl' in resp.text:
                print("Device reports Replay capabilities.")
                
            # Try to find all XAddrs and guess
            xaddrs = re.findall(r'<(?:\w+:)?XAddr>(.*?)</(?:\w+:)?XAddr>', resp.text)
            for xaddr in xaddrs:
                if 'replay' in xaddr.lower():
                    replay_url = xaddr
                    print(f"Found Replay Service (guessed): {replay_url}")
            
            # If not found explicitly, guess standard path
            if not replay_url:
                replay_url = f"http://{IP}:{PORT}/onvif/replay_service"
            if not media_url:
                media_url = f"http://{IP}:{PORT}/onvif/media_service"
                
            return media_url, replay_url, search_url
        else:
            print(f"❌ GetCapabilities Failed: {resp.status_code}")
            return None, None, None
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return None, None, None

def find_recordings(search_service_url, profile_token):
    print(f"Searching for recordings via {search_service_url}...")
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    
    # Simple FindRecordings (Search)
    # We search for ALL recordings to get a token
    body = f'''<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tse="http://www.onvif.org/ver10/search/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
        {create_auth_header(USERNAME, PASSWORD)}
        <s:Body>
            <tse:FindRecordings>
                <tse:Scope>
                    <tt:IncludedSources>
                        <tt:Token>{profile_token}</tt:Token>
                    </tt:IncludedSources>
                </tse:Scope>
                <tse:MaxMatches>10</tse:MaxMatches>
                <tse:KeepAliveTime>PT10S</tse:KeepAliveTime>
            </tse:FindRecordings>
        </s:Body>
    </s:Envelope>'''
    
    try:
        resp = requests.post(search_service_url, data=body, headers=headers, timeout=5)
        if resp.status_code == 200:
            import re
            # Extract SearchToken
            match = re.search(r'<(?:\w+:)?SearchToken>(.*?)</(?:\w+:)?SearchToken>', resp.text)
            if match:
                search_token = match.group(1)
                print(f"Found SearchToken: {search_token}")
                return search_token
            else:
                print("SearchToken not found in response")
                print(resp.text)
        else:
            print(f"❌ FindRecordings Failed: {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"❌ Connection Error: {e}")
    return None

def get_recording_search_results(search_service_url, search_token):
    print(f"Getting Search Results for token {search_token}...")
    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
    
    body = f'''<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tse="http://www.onvif.org/ver10/search/wsdl">
        {create_auth_header(USERNAME, PASSWORD)}
        <s:Body>
            <tse:GetRecordingSearchResults>
                <tse:SearchToken>{search_token}</tse:SearchToken>
                <tse:MinResults>1</tse:MinResults>
                <tse:MaxResults>10</tse:MaxResults>
                <tse:WaitTime>PT5S</tse:WaitTime>
            </tse:GetRecordingSearchResults>
        </s:Body>
    </s:Envelope>'''
    
    try:
        resp = requests.post(search_service_url, data=body, headers=headers, timeout=5)
        if resp.status_code == 200:
            import re
            # Extract RecordingToken
            # <tt:RecordingToken>token</tt:RecordingToken>
            tokens = re.findall(r'<(?:\w+:)?RecordingToken>(.*?)</(?:\w+:)?RecordingToken>', resp.text)
            if tokens:
                # Return distinct tokens
                return list(set(tokens))
            else:
                print("No RecordingTokens found in search results")
                print(resp.text)
        else:
            print(f"❌ GetRecordingSearchResults Failed: {resp.status_code}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")
    return []

if __name__ == "__main__":
    # USER CONFIG
    PASSWORD = "Sgs_2025_" 
    
    device_service = f"http://{IP}:{PORT}/onvif/device_service"
    
    print("--- 1. Discover Services ---")
    media_url, replay_url, search_url = get_services(device_service)
    
    if media_url and replay_url and search_url:
        print("\n--- 2. Get Profiles ---")
        profiles = get_profiles(media_url)
        print(f"Found Profiles: {profiles}")
        
        target_profile = next((p for p in profiles if "media_profile" in p), profiles[0]) if profiles else None
        
        if target_profile:
            print(f"\n--- 3. Find Recordings via Search Service ---")
            search_token = find_recordings(search_url, target_profile)
            
            if search_token:
                recording_tokens = get_recording_search_results(search_url, search_token)
                print(f"Found Recording Tokens: {recording_tokens}")
                
                if recording_tokens:
                    target_recording = recording_tokens[0]
                    print(f"\n--- 4. Get Replay URI for Recording {target_recording} ---")
                    
                    # Update get_replay_uri to support RecordingToken
                    # (Quick hack: we define a new function or update the call manually here)
                    # Let's verify if we need to update the function
                    pass 
                    # ... The original function didn't take RecordingToken. 
                    # I should rely on the previous edit or make a new one. 
                    # The previous edit REMOVED RecordingToken. I need to put it back or make a new version.
                    # Since I can't edit the function definition easily in this block without being contiguous...
                    # I will just write a new request here.
            
                    headers = {'Content-Type': 'application/soap+xml; charset=utf-8'}
                    body = f'''<?xml version="1.0" encoding="utf-8"?>
                    <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:trp="http://www.onvif.org/ver10/replay/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
                        {create_auth_header(USERNAME, PASSWORD)}
                        <s:Body>
                            <trp:GetReplayUri>
                                <trp:StreamSetup>
                                    <tt:Stream>RTP-Unicast</tt:Stream>
                                    <tt:Transport>
                                        <tt:Protocol>RTSP</tt:Protocol>
                                    </tt:Transport>
                                </trp:StreamSetup>
                                <trp:RecordingToken>{target_recording}</trp:RecordingToken>
                            </trp:GetReplayUri>
                        </s:Body>
                    </s:Envelope>'''
                    
                    try:
                        resp = requests.post(replay_url, data=body, headers=headers, timeout=5)
                        if resp.status_code == 200:
                            import re
                            match = re.search(r'<(?:\w+:)?Uri>(.*?)</(?:\w+:)?Uri>', resp.text)
                            if match:
                                uri = match.group(1)
                                print(f"\n🎯 DISCOVERED REPLAY URI: {uri}")
                            else:
                                print("Uri tag not found")
                        else:
                            print(f"❌ Failed to get Replay URI: {resp.status_code}")
                            print(resp.text)
                    except Exception as e:
                        print(e)

    else:
        print("Could not find necessary services.")
