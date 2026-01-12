"""
Script pour nettoyer les fichiers vidéo orphelins
(fichiers présents sur le disque mais plus dans la base de données)

Usage:
    python cleanup_orphan_videos.py

Options:
    --dry-run : Afficher les fichiers à supprimer sans les supprimer
    --court-id : Nettoyer uniquement un court spécifique (ex: --court-id 3)
"""

import os
import sys
import argparse
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__))
from src.models.user import db, Video


def find_orphan_videos(court_id=None, dry_run=False):
    """
    Trouve et optionnellement supprime les vidéos orphelines
    
    Args:
        court_id: ID du court à nettoyer (None = tous les courts)
        dry_run: Si True, affiche sans supprimer
    """
    
    videos_dir = "static/videos"
    
    if not os.path.exists(videos_dir):
        print(f"❌ Dossier {videos_dir} introuvable")
        return
    
    orphan_count = 0
    total_size = 0
    
    # Parcourir tous les courts OU un court spécifique
    if court_id:
        court_dirs = [str(court_id)]
    else:
        court_dirs = [d for d in os.listdir(videos_dir) if os.path.isdir(os.path.join(videos_dir, d))]
    
    print(f"\n🔍 Recherche de vidéos orphelines...")
    print(f"   Courts à analyser: {len(court_dirs)}")
    
    for court_dir in court_dirs:
        court_path = os.path.join(videos_dir, court_dir)
        
        if not os.path.isdir(court_path):
            continue
        
        # Parcourir récursivement tous les fichiers .mp4
        for root, dirs, files in os.walk(court_path):
            for filename in files:
                if not filename.endswith('.mp4'):
                    continue
                
                file_path = os.path.join(root, filename)
                
                # Extraire le titre de la vidéo depuis le chemin
                # Format: static/videos/{court_id}/{date}/{club}/{session}.mp4
                # Le titre est: {date}/{club}/{session}
                rel_path = os.path.relpath(file_path, court_path)
                video_title = rel_path.replace('.mp4', '').replace('\\', '/')
                
                # Vérifier si la vidéo existe en base
                video_exists = Video.query.filter(
                    Video.court_id == int(court_dir),
                    Video.title == video_title
                ).first()
                
                if not video_exists:
                    # Vidéo orpheline trouvée !
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    orphan_count += 1
                    
                    size_mb = file_size / (1024 * 1024)
                    print(f"\n📹 Orphelin trouvé:")
                    print(f"   Fichier: {file_path}")
                    print(f"   Taille: {size_mb:.2f} MB")
                    print(f"   Titre recherché: {video_title}")
                    
                    if not dry_run:
                        try:
                            os.remove(file_path)
                            print(f"   ✅ SUPPRIMÉ")
                        except Exception as e:
                            print(f"   ❌ Erreur: {e}")
                    else:
                        print(f"   ⚠️ [DRY-RUN] Serait supprimé")
    
    total_size_mb = total_size / (1024 * 1024)
    print(f"\n{'='*60}")
    print(f"📊 Résumé:")
    print(f"   Vidéos orphelines: {orphan_count}")
    print(f"   Espace total: {total_size_mb:.2f} MB")
    
    if dry_run:
        print(f"\n⚠️ Mode DRY-RUN: Aucun fichier n'a été supprimé")
        print(f"   Relancez sans --dry-run pour supprimer")
    else:
        print(f"\n✅ Nettoyage terminé")
    
    return orphan_count, total_size_mb


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nettoyer les vidéos orphelines")
    parser.add_argument('--dry-run', action='store_true', help='Afficher sans supprimer')
    parser.add_argument('--court-id', type=int, help='Court ID spécifique à nettoyer')
    
    args = parser.parse_args()
    
    # Importer create_app
    from app import create_app
    app = create_app()
    
    with app.app_context():
        print(f"\n{'='*60}")
        print(f"🧹 NETTOYAGE DES VIDÉOS ORPHELINES")
        print(f"{'='*60}")
        print(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Mode: {'DRY-RUN (simulation)' if args.dry_run else 'SUPPRESSION RÉELLE'}")
        
        if args.court_id:
            print(f"   Court: #{args.court_id}")
        else:
            print(f"   Court: TOUS")
        
        if not args.dry_run:
            confirm = input("\n⚠️ Confirmer la suppression réelle ? (oui/non): ")
            if confirm.lower() not in ['oui', 'yes', 'o', 'y']:
                print("\n❌ Opération annulée")
                sys.exit(0)
        
        count, size_mb = find_orphan_videos(
            court_id=args.court_id,
            dry_run=args.dry_run
        )
        
        print(f"\n{'='*60}\n")
