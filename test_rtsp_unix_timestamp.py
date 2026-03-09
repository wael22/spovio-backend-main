#!/usr/bin/env python3
"""
Test RTSP Replay with CORRECT Unix Timestamps
Based on official Uniview documentation found online

Format: rtsp://user:pass@ip:port/c{channel}/b{unix_start}/e{unix_end}/replay
Source: visiotechsecurity.com / Uniview official docs
"""

import subprocess
import time
from datetime import datetime, timedelta

# Camera credentials
IP = "192.168.100.208"
USER = "admin"
PASS = "Sgs_2025_"
PORT = 554
CHANNEL = 1  # Channel 1

print("=" * 70)
print("RTSP REPLAY TEST - UNIX TIMESTAMP FORMAT")
print("=" * 70)
print("\nFormat officiel Uniview trouvé:")
print("rtsp://user:pass@ip:port/c{channel}/b{unix_start}/e{unix_end}/replay\n")

# Get current Unix timestamp
now_unix = int(time.time())
now_dt = datetime.fromtimestamp(now_unix)

print(f"Heure actuelle: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Unix timestamp actuel: {now_unix}\n")

# Test différentes périodes dans le passé
tests = [
    {
        "name": "Il y a 1 heure (30 min de durée)",
        "start_offset": 3600,  # 1 hour ago
        "duration": 1800      # 30 minutes
    },
    {
        "name": "Il y a 2 heures (15 min de durée)",
        "start_offset": 7200,  # 2 hours ago
        "duration": 900       # 15 minutes
    },
    {
        "name": "Il y a 30 minutes (10 min de durée)",
        "start_offset": 1800,  # 30 min ago
        "duration": 600       # 10 minutes
    }
]

for i, test in enumerate(tests, 1):
    print(f"\n{'='*70}")
    print(f"TEST {i}: {test['name']}")
    print(f"{'='*70}")
    
    # Calculate timestamps
    start_unix = now_unix - test['start_offset']
    end_unix = start_unix + test['duration']
    
    start_dt = datetime.fromtimestamp(start_unix)
    end_dt = datetime.fromtimestamp(end_unix)
    
    print(f"Période demandée:")
    print(f"  Début: {start_dt.strftime('%Y-%m-%d %H:%M:%S')} (Unix: {start_unix})")
    print(f"  Fin:   {end_dt.strftime('%Y-%m-%d %H:%M:%S')} (Unix: {end_unix})")
    print(f"  Durée: {test['duration']} secondes ({test['duration']//60} min)")
    
    # Build RTSP URL with CORRECT format
    rtsp_url = f"rtsp://{USER}:{PASS}@{IP}:{PORT}/c{CHANNEL}/b{start_unix}/e{end_unix}/replay"
    
    output_file = f"test_unix_{i}.mp4"
    
    print(f"\nURL RTSP:")
    print(f"  {rtsp_url.replace(PASS, '***')}")
    print(f"\nFichier de sortie: {output_file}")
    
    # FFmpeg command
    cmd = [
        "ffmpeg",
        "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-c", "copy",
        "-t", str(test['duration'] + 10),  # Safety buffer
        output_file
    ]
    
    print(f"\n⏳ Tentative de téléchargement...")
    print(f"   (Timeout: 60 secondes)")
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"✅ SUCCÈS! Fichier créé: {output_file}")
            print(f"\n⚠️  IMPORTANT: Ouvrez {output_file} et vérifiez:")
            print(f"   - Le timestamp de la caméra montre-t-il {start_dt.strftime('%H:%M')}?")
            print(f"   - Ou montre-t-il l'heure actuelle (~{now_dt.strftime('%H:%M')})?")
            
            # Check file size
            import os
            if os.path.exists(output_file):
                size_mb = os.path.getsize(output_file) / (1024 * 1024)
                print(f"\n   Taille du fichier: {size_mb:.2f} MB")
                if size_mb < 0.1:
                    print(f"   ⚠️  Fichier très petit - probablement vide ou erreur")
        else:
            stderr = result.stderr.decode('utf-8', errors='ignore')
            print(f"❌ ÉCHEC (code: {result.returncode})")
            
            # Show relevant error lines
            error_lines = [line for line in stderr.split('\n') if 'error' in line.lower() or 'failed' in line.lower()]
            if error_lines:
                print(f"\nErreur:")
                for line in error_lines[:3]:  # First 3 error lines
                    print(f"   {line.strip()}")
    
    except subprocess.TimeoutExpired:
        print(f"❌ TIMEOUT après 60 secondes")
        print(f"   La caméra ne répond pas ou cherche la vidéo...")
    
    except Exception as e:
        print(f"❌ ERREUR: {e}")
    
    # Don't spam the camera - wait between tests
    if i < len(tests):
        print(f"\n⏸️  Pause 3 secondes avant le test suivant...")
        time.sleep(3)

print(f"\n{'='*70}")
print(f"TESTS TERMINÉS")
print(f"{'='*70}")
print(f"\n📋 Résumé:")
print(f"   - Si des fichiers .mp4 ont été créés, vérifiez leur contenu")
print(f"   - Comparez le timestamp de la caméra avec l'heure demandée")
print(f"   - Si le timestamp correspond au passé → ✅ FORMAT FONCTIONNE!")
print(f"   - Si le timestamp montre maintenant → ❌ Toujours le direct")
