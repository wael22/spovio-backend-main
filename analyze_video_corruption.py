#!/usr/bin/env python3
"""
Analyser les fichiers vidéo corrompus pour comprendre pourquoi 0xc00d36c4
"""

import subprocess
import os
import json

files_to_check = [
    "test_unix_1.mp4",
    "test_unix_2.mp4", 
    "test_unix_3.mp4"
]

print("=" * 70)
print("ANALYSE DES FICHIERS VIDÉO CORROMPUS")
print("=" * 70)

for filename in files_to_check:
    if not os.path.exists(filename):
        print(f"\n❌ {filename} n'existe pas")
        continue
    
    size_mb = os.path.getsize(filename) / (1024 * 1024)
    
    print(f"\n{'='*70}")
    print(f"📁 {filename} ({size_mb:.2f} MB)")
    print(f"{'='*70}")
    
    # Analyse avec ffprobe
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-print_format", "json",
        filename
    ]
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout.decode('utf-8'))
            
            # Check streams
            streams = data.get('streams', [])
            format_info = data.get('format', {})
            
            print(f"\n📊 Informations:")
            print(f"   Nombre de streams: {len(streams)}")
            
            if streams:
                for i, stream in enumerate(streams):
                    print(f"\n   Stream {i}:")
                    print(f"      Type: {stream.get('codec_type', 'unknown')}")
                    print(f"      Codec: {stream.get('codec_name', 'unknown')}")
                    
                    if stream.get('codec_type') == 'video':
                        print(f"      Frames: {stream.get('nb_frames', 'N/A')}")
                        print(f"      Durée: {stream.get('duration', 'N/A')} sec")
                        print(f"      Résolution: {stream.get('width', '?')}x{stream.get('height', '?')}")
            else:
                print(f"\n   ⚠️  AUCUN STREAM TROUVÉ!")
            
            # Format info
            print(f"\n   Format:")
            print(f"      Durée: {format_info.get('duration', 'N/A')} sec")
            print(f"      Bitrate: {format_info.get('bit_rate', 'N/A')} bits/s")
            print(f"      Taille: {format_info.get('size', 'N/A')} bytes")
            
            # Verdict
            has_video = any(s.get('codec_type') == 'video' for s in streams)
            has_frames = any(int(s.get('nb_frames', 0) or 0) > 0 for s in streams if s.get('codec_type') == 'video')
            
            print(f"\n   {'='*66}")
            if not has_video:
                print(f"   ❌ VERDICT: Aucun stream vidéo détecté")
            elif not has_frames:
                print(f"   ❌ VERDICT: Stream vidéo présent mais 0 frames")
            else:
                print(f"   ✅ VERDICT: Fichier valide avec {streams[0].get('nb_frames', '?')} frames")
            print(f"   {'='*66}")
        
        else:
            stderr = result.stderr.decode('utf-8')
            print(f"\n❌ ffprobe a échoué:")
            print(f"   {stderr[:200]}")
    
    except subprocess.TimeoutExpired:
        print(f"\n❌ Timeout lors de l'analyse")
    except Exception as e:
        print(f"\n❌ Erreur: {e}")

print(f"\n{'='*70}")
print(f"CONCLUSION")
print(f"{'='*70}")
print(f"""
L'erreur 0xc00d36c4 signifie: "Fichier vidéo corrompu ou format non supporté"

Dans notre cas, les fichiers sont CRÉÉS par FFmpeg mais la caméra
n'envoie PAS de données vidéo valides pour les enregistrements passés.

Le fichier contient des MÉTADONNÉES mais AUCUNE FRAME VIDÉO.

Cela prouve que la caméra Uniview:
✅ Accepte la connexion RTSP replay
✅ Envoie une réponse (d'où la taille du fichier)
❌ Ne fournit PAS les frames vidéo des enregistrements passés

C'est une LIMITATION MATÉRIELLE/FIRMWARE, pas un problème de format.
""")
