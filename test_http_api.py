import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from datetime import datetime, timedelta

IP = "192.168.100.208"
USERNAME = "admin"
PASSWORD = "Sgs_2025_"
PORT = 80

def test_auth_methods(url, method='GET', data=None):
    """Essayer différentes méthodes d'authentification"""
    auth_methods = [
        ("HTTPBasicAuth", HTTPBasicAuth(USERNAME, PASSWORD)),
        ("HTTPDigestAuth", HTTPDigestAuth(USERNAME, PASSWORD)),
    ]
    
    for auth_name, auth in auth_methods:
        try:
            if method == 'GET':
                response = requests.get(url, auth=auth, timeout=5)
            else:
                response = requests.post(url, auth=auth, data=data, timeout=5)
            
            if response.status_code in [200, 206]:
                print(f"✅ {auth_name} fonctionne!")
                print(f"   Status: {response.status_code}")
                print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
                print(f"   Taille: {len(response.content)} bytes")
                return response
            else:
                print(f"❌ {auth_name}: {response.status_code}")
        except Exception as e:
            print(f"❌ {auth_name}: {e}")
    
    return None

print("="*60)
print("🔍 TEST DES APIs HTTP POUR CAMÉRA UNIVIEW")
print("="*60)

# Période de test: 1 heure il y a environ 1 heure
now = datetime.now()
start_time = now - timedelta(hours=2)
end_time = now - timedelta(hours=1)

start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
end_iso = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

print(f"\n📅 Période de test: {start_time.strftime('%H:%M')} → {end_time.strftime('%H:%M')}")
print(f"   ISO Format: {start_iso} → {end_iso}\n")

# Test 1: Device Info (pour détecter le type de caméra)
print("\n" + "="*60)
print("Test 1: Détection du type de caméra")
print("="*60)

device_endpoints = [
    ("ISAPI Device Info", f"http://{IP}:{PORT}/ISAPI/System/deviceInfo"),
    ("CGI Device Type", f"http://{IP}:{PORT}/cgi-bin/magicBox.cgi?action=getDeviceType"),
    ("API Device Info", f"http://{IP}:{PORT}/api/system/deviceinfo"),
]

for name, url in device_endpoints:
    print(f"\n🔄 {name}")
    print(f"   URL: {url}")
    response = test_auth_methods(url)
    if response:
        print(f"   Réponse (100 premiers chars):")
        print(f"   {response.text[:100]}...")
        print()

# Test 2: Search/Query Recordings
print("\n" + "="*60)
print("Test 2: Recherche d'enregistrements")
print("="*60)

search_endpoints = [
    ("ISAPI Search", f"http://{IP}:{PORT}/ISAPI/ContentMgmt/record/tracks/1/search", "POST", 
     f'''<?xml version="1.0" encoding="UTF-8"?>
     <CMSearchDescription>
         <searchID>C{start_time.strftime("%Y%m%d%H%M%S")}</searchID>
         <trackList><trackID>1</trackID></trackList>
         <timeSpanList>
             <timeSpan>
                 <startTime>{start_iso}</startTime>
                 <endTime>{end_iso}</endTime>
             </timeSpan>
         </timeSpanList>
         <maxResults>100</maxResults>
     </CMSearchDescription>'''),
    
    ("CGI Search", f"http://{IP}:{PORT}/cgi-bin/api.cgi?cmd=Search&channel=1&startTime={start_iso}&endTime={end_iso}", "GET", None),
    
    ("Dahua MediaFileFind", f"http://{IP}:{PORT}/cgi-bin/mediaFileFind.cgi?action=factory.create", "GET", None),
]

for name, url, method, data in search_endpoints:
    print(f"\n🔄 {name}")
    print(f"   URL: {url.split('?')[0]}")
    response = test_auth_methods(url, method, data)
    if response:
        print(f"   Contenu (200 premiers chars):")
        print(f"   {response.text[:200]}...")
        print()

# Test 3: Download Endpoints
print("\n" + "="*60)
print("Test 3: Endpoints de téléchargement")
print("="*60)

download_endpoints = [
    ("ISAPI Download", f"http://{IP}:{PORT}/ISAPI/ContentMgmt/download?playbackURI=rtsp://{IP}/Streaming/tracks/101&startTime={start_iso}&endTime={end_iso}"),
    
    ("CGI Download", f"http://{IP}:{PORT}/cgi-bin/RPC_Loadfile/test.mp4?action=download&channel=1&StartTime={start_iso}&EndTime={end_iso}"),
    
    ("API Download", f"http://{IP}:{PORT}/api/video/download?channel=1&start={start_iso}&end={end_iso}"),
]

for name, url in download_endpoints:
    print(f"\n🔄 {name}")
    print(f"   URL: {url.split('?')[0]}")
    response = test_auth_methods(url)
    if response:
        content_type = response.headers.get('content-type', '')
        if 'video' in content_type or 'octet-stream' in content_type:
            print(f"   ✅ POTENTIELLEMENT UN TÉLÉCHARGEMENT VIDÉO!")
            print(f"   Content-Type: {content_type}")
        else:
            print(f"   ⚠️  Pas un fichier vidéo")
            print(f"   Réponse: {response.text[:100]}...")
        print()

print("\n" + "="*60)
print("📊 RÉSUMÉ")
print("="*60)
print("\nSi aucune API HTTP ne fonctionne, nous devrons continuer avec RTSP.")
print("Si une API fonctionne, ce sera beaucoup plus simple pour la récupération!")
