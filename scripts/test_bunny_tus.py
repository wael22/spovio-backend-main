"""
Test Bunny CDN TUS Protocol Support

Ce script vérifie si Bunny Stream API supporte le protocole TUS
pour les uploads resumable.
"""

import requests
import os
from dotenv import load_dotenv

# Charger variables d'environnement
load_dotenv()

def test_tus_support():
    """Teste le support TUS de Bunny CDN"""
    
    api_key = os.environ.get('BUNNY_API_KEY')
    library_id = os.environ.get('BUNNY_LIBRARY_ID')
    
    if not api_key or not library_id:
        print("❌ BUNNY_API_KEY ou BUNNY_LIBRARY_ID manquant dans .env")
        return False
    
    print("🔍 Test support TUS sur Bunny Stream API...")
    print(f"📚 Library ID: {library_id}")
    print()
    
    # Test 1: OPTIONS sur endpoint videos
    print("📡 Test 1: OPTIONS /videos")
    try:
        response = requests.options(
            f"https://video.bunnycdn.com/library/{library_id}/videos",
            headers={'AccessKey': api_key},
            timeout=10
        )
        
        print(f"   Status: {response.status_code}")
        print(f"   Headers:")
        for key, value in response.headers.items():
            if 'tus' in key.lower() or 'upload' in key.lower():
                print(f"      {key}: {value}")
        
        if 'Tus-Resumable' in response.headers:
            print()
            print("✅ TUS SUPPORTÉ!")
            print(f"   Version TUS: {response.headers['Tus-Resumable']}")
            if 'Tus-Extension' in response.headers:
                print(f"   Extensions: {response.headers['Tus-Extension']}")
            return True
        else:
            print("   ⚠️ Pas de header Tus-Resumable trouvé")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print()
    
    # Test 2: HEAD sur endpoint racine (alternative)
    print("📡 Test 2: HEAD /library/{id}")
    try:
        response = requests.head(
            f"https://video.bunnycdn.com/library/{library_id}",
            headers={'AccessKey': api_key},
            timeout=10
        )
        
        print(f"   Status: {response.status_code}")
        if 'Tus-Resumable' in response.headers:
            print("✅ TUS SUPPORTÉ (via HEAD)!")
            return True
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print()
    
    # Test 3: Lire documentation via GET (check response body)
    print("📡 Test 3: GET /library/{id} (check capabilities)")
    try:
        response = requests.get(
            f"https://video.bunnycdn.com/library/{library_id}",
            headers={'AccessKey': api_key},
            timeout=10
        )
        
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Library Name: {data.get('Name', 'N/A')}")
            print(f"   Storage Used: {data.get('StorageUsed', 0) / (1024**3):.2f} GB")
            
            # Chercher indices de TUS dans la réponse
            if 'tus' in str(data).lower():
                print("   ℹ️ Mention de TUS trouvée dans réponse")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print()
    print("=" * 60)
    print("❌ RÉSULTAT: TUS NON SUPPORTÉ par Bunny Stream API")
    print()
    print("📋 ALTERNATIVES RECOMMANDÉES:")
    print("   1. Chunked Upload Manuel (10MB chunks)")
    print("   2. Pre-signed URLs avec upload direct frontend")
    print("   3. Augmenter timeout httpx (quick fix)")
    print()
    return False

if __name__ == "__main__":
    is_supported = test_tus_support()
    exit(0 if is_supported else 1)
