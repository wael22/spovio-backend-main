"""
Script de synchronisation des chemins de fichiers locaux
Met à jour local_file_path pour les vidéos qui existent physiquement sur le disque
"""

import os
import sys

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.main import create_app
from src.models.database import db
from src.models.user import Video

def sync_local_file_paths():
    """Synchronise les chemins de fichiers locaux avec les vidéos en BDD"""
    
    app = create_app('development')
    
    with app.app_context():
        # Récupérer toutes les vidéos
        videos = Video.query.all()
        
        print(f"🔍 Vérification de {len(videos)} vidéos...")
        
        updated_count = 0
        not_found_count = 0
        already_set_count = 0
        
        for video in videos:
            # Si local_file_path est déjà défini, on skip
            if video.local_file_path and video.local_file_deleted_at is None:
                already_set_count += 1
                continue
            
            # Récupérer le club_id depuis le court
            if not video.court_id:
                continue
                
            from src.models.user import Court
            court = Court.query.get(video.court_id)
            if not court:
                continue
            
            club_id = court.club_id
            
            # Chercher le fichier dans les emplacements possibles
            possible_paths = [
                f"static/videos/{club_id}/sess_{club_id}_{video.court_id}_{video.id}.mp4",
                f"static/videos/{club_id}/rec_{video.id}.mp4",
                f"static/videos/rec_{video.id}.mp4"
            ]
            
            # Vérifier aussi avec title si c'est un chemin
            if video.title and '/' in video.title:
                # Essayer de reconstituer le nom de fichier depuis le titre
                # Format: "date/club/terrain" -> chercher tous les .mp4 dans le dossier du club
                video_dir = f"static/videos/{club_id}"
                if os.path.isdir(video_dir):
                    # Lister tous les fichiers .mp4 du club
                    for filename in os.listdir(video_dir):
                        if filename.endswith('.mp4'):
                            possible_paths.append(f"{video_dir}/{filename}")
            
            # Chercher le fichier
            found_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    found_path = path
                    break
            
            if found_path:
                # Mettre à jour la BDD
                video.local_file_path = found_path
                
                # Calculer la taille si pas déjà fait
                if not video.file_size:
                    try:
                        video.file_size = os.path.getsize(found_path)
                    except:
                        pass
                
                updated_count += 1
                print(f"✅ Vidéo {video.id}: {found_path}")
            else:
                not_found_count += 1
                # print(f"⚠️  Vidéo {video.id}: fichier introuvable")
        
        # Commit les modifications
        db.session.commit()
        
        print(f"\n📊 Résumé:")
        print(f"   ✅ Chemins mis à jour: {updated_count}")
        print(f"   ✓  Déjà configurés: {already_set_count}")
        print(f"   ⚠️  Fichiers introuvables: {not_found_count}")
        print(f"\n🎉 Synchronisation terminée!")

if __name__ == "__main__":
    sync_local_file_paths()
