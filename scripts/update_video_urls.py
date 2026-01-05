
#!/usr/bin/env python3
"""
Script de monitoring et mise à jour des URLs vidéo Bunny CDN
Met à jour automatiquement les URLs des vidéos une fois l'upload terminé
"""

import os
import sys
import logging
import time
from datetime import datetime, timedelta

# Ajout du path pour importer les modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.models.database import db
from src.models.recording import Video
from src.services.bunny_storage_service import bunny_storage_service
from src import create_app

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def update_video_urls():
    """Met à jour les URLs des vidéos uploadées sur Bunny CDN"""
    
    logger.info("🔄 Démarrage mise à jour URLs vidéo Bunny CDN...")
    
    # Trouver les vidéos avec bunny_video_id mais sans file_url CDN
    videos_to_update = Video.query.filter(
        Video.bunny_video_id.isnot(None),
        Video.cdn_migrated_at.isnot(None),
        ~Video.file_url.like('https://vz-%')  # Pas déjà une URL CDN
    ).all()
    
    logger.info(f"📋 {len(videos_to_update)} vidéos à vérifier pour mise à jour URL")
    
    updated_count = 0
    
    for video in videos_to_update:
        try:
            # Vérifier le statut de l'upload
            upload_status = bunny_storage_service.get_upload_status(video.bunny_video_id)
            
            if upload_status and upload_status.status.value == 'completed':
                # Upload terminé, générer l'URL CDN
                cdn_video_url = bunny_storage_service.get_video_url(video.bunny_video_id)
                cdn_thumbnail_url = bunny_storage_service.get_thumbnail_url(video.bunny_video_id)
                
                # Mettre à jour la vidéo
                video.file_url = cdn_video_url
                video.thumbnail_url = cdn_thumbnail_url
                
                db.session.commit()
                
                logger.info(f"✅ Vidéo {video.id} mise à jour: {cdn_video_url}")
                updated_count += 1
                
            elif upload_status and upload_status.status.value == 'failed':
                logger.warning(f"❌ Upload échoué pour vidéo {video.id} (Bunny ID: {video.bunny_video_id})")
                
            else:
                logger.debug(f"⏳ Upload en cours pour vidéo {video.id}")
                
        except Exception as e:
            logger.error(f"💥 Erreur mise à jour vidéo {video.id}: {e}")
    
    logger.info(f"🎯 Mise à jour terminée: {updated_count} vidéos mises à jour")
    return updated_count

def monitor_uploads():
    """Monitore en continu les uploads et met à jour les URLs"""
    
    logger.info("🚀 Démarrage monitoring uploads Bunny CDN...")
    
    while True:
        try:
            updated = update_video_urls()
            
            if updated > 0:
                logger.info(f"🔄 {updated} URLs mises à jour")
            
            # Attendre 30 secondes avant la prochaine vérification
            time.sleep(30)
            
        except KeyboardInterrupt:
            logger.info("⏹️ Arrêt du monitoring demandé")
            break
        except Exception as e:
            logger.error(f"💥 Erreur monitoring: {e}")
            time.sleep(10)  # Attendre un peu en cas d'erreur

if __name__ == '__main__':
    # Créer l'app Flask pour le contexte de DB
    app = create_app()
    
    with app.app_context():
        if len(sys.argv) > 1 and sys.argv[1] == '--monitor':
            # Mode monitoring continu
            monitor_uploads()
        else:
            # Mode une seule fois
            updated = update_video_urls()
            print(f"✅ {updated} vidéos mises à jour")