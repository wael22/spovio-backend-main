#!/usr/bin/env python3
"""
Vérifier si la carte SD contient des enregistrements
Utilise ONVIF et HTTP pour interroger la caméra
"""

import requests
from requests.auth import HTTPDigestAuth
from onvif import ONVIFCamera
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Credentials
IP = "192.168.100.208"
HTTP_PORT = 80
ONVIF_PORT = 8000
USER = "admin"
PASS = "Sgs_2025_"

print("=" * 70)
print("VÉRIFICATION DE LA CARTE SD")
print("=" * 70)

# Test 1: Vérifier via HTTP si la SD est montée
print("\n📋 Test 1: Statut de la carte SD via HTTP")
print("-" * 70)

sd_endpoints = [
    "/LAPI/V1.0/System/Storage",
    "/ISAPI/System/Storage",
    "/cgi-bin/magicBox.cgi?action=getSystemInfo",
    "/onvifsnapshot/storage_status"
]

for endpoint in sd_endpoints:
    url = f"http://{IP}:{HTTP_PORT}{endpoint}"
    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(USER, PASS),
            timeout=5
        )
        
        if response.status_code == 200:
            print(f"✅ {endpoint}")
            print(f"   Réponse ({len(response.text)} bytes):")
            print(f"   {response.text[:300]}")
            print()
        else:
            print(f"❌ {endpoint} → {response.status_code}")
    
    except Exception as e:
        print(f"❌ {endpoint} → {str(e)[:50]}")

# Test 2: ONVIF GetRecordingSummary
print("\n📋 Test 2: Résumé des enregistrements via ONVIF")
print("-" * 70)

try:
    camera = ONVIFCamera(IP, ONVIF_PORT, USER, PASS)
    
    # Create recording service
    recording_service = camera.create_recording_service()
    
    # Get recording summary
    print("🔍 Appel de GetRecordingSummary()...")
    summary = recording_service.GetRecordingSummary()
    
    print(f"✅ Résumé des enregistrements:")
    print(f"   Données: {summary}")
    
    # Si le résumé indique des enregistrements
    if hasattr(summary, 'SummaryParameters'):
        print(f"\n   Paramètres du résumé:")
        for key, value in summary.SummaryParameters.__dict__.items():
            print(f"      {key}: {value}")

except Exception as e:
    print(f"❌ Erreur ONVIF: {e}")

# Test 3: ONVIF FindRecordings (détaillé)
print("\n📋 Test 3: Liste des enregistrements via ONVIF FindRecordings")
print("-" * 70)

try:
    camera = ONVIFCamera(IP, ONVIF_PORT, USER, PASS)
    search_service = camera.create_search_service()
    
    # Search for recordings (last 24 hours)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=24)
    
    print(f"🔍 Recherche des enregistrements entre:")
    print(f"   Début: {start_time}")
    print(f"   Fin: {end_time}")
    
    search_token = search_service.FindRecordings({
        'Scope': {
            'IncludedSources': [],
            'IncludedRecordings': None,
            'RecordingInformationFilter': None
        },
        'MaxMatches': 100,
        'KeepAliveTime': 'PT60S'
    })
    
    print(f"✅ Token de recherche: {search_token}")
    
    # Get results
    results = search_service.GetRecordingSearchResults({
        'SearchToken': search_token,
        'MinResults': 1,
        'MaxResults': 100,
        'WaitTime': 'PT5S'
    })
    
    print(f"\n📊 Résultats:")
    if hasattr(results, 'RecordingInformation'):
        recordings = results.RecordingInformation
        if recordings:
            print(f"   ✅ {len(recordings)} enregistrement(s) trouvé(s)!")
            for i, rec in enumerate(recordings[:5], 1):  # Show first 5
                print(f"\n   Enregistrement {i}:")
                print(f"      RecordingToken: {rec.RecordingToken}")
                if hasattr(rec, 'EarliestRecording'):
                    print(f"      Premier: {rec.EarliestRecording}")
                if hasattr(rec, 'LatestRecording'):
                    print(f"      Dernier: {rec.LatestRecording}")
        else:
            print(f"   ⚠️  Aucun enregistrement trouvé")
    else:
        print(f"   ⚠️  Pas de RecordingInformation dans la réponse")
        print(f"   Réponse brute: {results}")

except Exception as e:
    print(f"❌ Erreur: {e}")

# Test 4: Check via web interface endpoint
print("\n📋 Test 4: Vérification capacité SD via endpoints connus")
print("-" * 70)

storage_endpoints = [
    "/LAPI/V1.0/System/Storage/SD/Capability",
    "/LAPI/V1.0/System/Storage/SD/Status",
    "/ISAPI/ContentMgmt/Storage",
    "/cgi-bin/recordFinder.cgi?action=getCount"
]

for endpoint in storage_endpoints:
    url = f"http://{IP}:{HTTP_PORT}{endpoint}"
    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(USER, PASS),
            timeout=5
        )
        
        if response.status_code == 200:
            print(f"✅ {endpoint}")
            print(f"   {response.text[:200]}")
        else:
            print(f"❌ {endpoint} → {response.status_code}")
    
    except Exception as e:
        print(f"❌ {endpoint} → Erreur")

print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)
print("""
Si aucun enregistrement n'est trouvé:
→ La SD n'enregistre peut-être pas (vérifiez config web)
→ Expliquerait pourquoi RTSP replay ne fonctionne pas

Si des enregistrements SONT trouvés:
→ Confirme que RTSP replay ne permet pas d'y accéder
→ Limitation firmware/matérielle confirmée
""")
