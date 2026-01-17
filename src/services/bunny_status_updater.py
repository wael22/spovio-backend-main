"""
Service de mise à jour automatique du statut des vidéos Bunny CDN
Vérifie périodiquement les vidéos en cours de processing et met à jour leur statut
"""

import logging
import time
import threading
import requests
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)


class BunnyStatusUpdater:
    """Service qui met à jour le statut des vidéos Bunny en background"""
    
    def __init__(self, api_key: str, library_id: str, app=None):
        self.api_key = api_key
        self.library_id = library_id
        self.api_base_url = f"https://video.bunnycdn.com/library/{library_id}"
        self.headers = {
            "AccessKey": api_key,
            "Accept": "application/json"
        }
        
        self.is_running = False
        self._thread = None
        self.check_interval = 30  # Vérifier toutes les 30 secondes
        self.app = app  # 🆕 Stocker l'instance Flask
    
    def start(self):
        """Démarre le service de mise à jour"""
        if self.is_running:
            logger.warning("Le service de mise à jour Bunny est déjà démarré")
            return
        
        self.is_running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        logger.info("✅ Service de mise à jour Bunny CDN démarré")
    
    def stop(self):
        """Arrête le service"""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("🛑 Service de mise à jour Bunny CDN arrêté")
    
    def _update_loop(self):
        """Boucle principale de mise à jour"""
        while self.is_running:
            try:
                self._check_and_update_videos()
            except Exception as e:
                logger.error(f"❌ Erreur dans la boucle de mise à jour: {e}")
            
            # Attendre avant la prochaine vérification
            time.sleep(self.check_interval)
    
    def _check_and_update_videos(self):
        """Vérifie et met à jour les vidéos en cours de processing"""
        from src.models.database import db
        from src.models.user import Video
        
        # 🆕 Utiliser le contexte d'application Flask stocké
        if not self.app:
            logger.warning("⚠️ Pas d'instance Flask - impossible de mettre à jour les vidéos")
            return
        
        with self.app.app_context():
            # Récupérer toutes les vidéos en cours de processing
            processing_videos = Video.query.filter(
                Video.processing_status.in_(['uploading', 'processing']),
                Video.bunny_video_id.isnot(None)
            ).all()
            
            if not processing_videos:
                return
            
            logger.debug(f"🔍 Vérification de {len(processing_videos)} vidéos en processing")
            
            for video in processing_videos:
                try:
                    # Récupérer le statut de la vidéo depuis Bunny
                    check_url = f"{self.api_base_url}/videos/{video.bunny_video_id}"
                    response = requests.get(check_url, headers=self.headers, timeout=10)
                    
                    if response.status_code == 200:
                        video_info = response.json()
                        status = video_info.get("status")
                        
                        # Statuts Bunny: 0=Created, 1=Uploaded, 2=Processing, 3=Encoding, 4=Finished, 5=Failed
                        if status == 4:  # Finished
                            video.processing_status = 'ready'
                            db.session.commit()
                            logger.info(f"✅ Vidéo {video.id} prête: {video.title}")
                        elif status == 5:  # Failed
                            video.processing_status = 'failed'
                            db.session.commit()
                            logger.error(f"❌ Vidéo {video.id} échec encodage: {video.title}")
                        elif status in [2, 3]:  # Processing, Encoding
                            video.processing_status = 'processing'
                            db.session.commit()
                    else:
                        logger.warning(f"⚠️ Impossible de vérifier vidéo {video.id}: HTTP {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"❌ Erreur vérification vidéo {video.id}: {e}")
                
                # Petit délai entre chaque requête pour ne pas surcharger l'API
                time.sleep(0.5)


# Instance globale
_bunny_status_updater = None


def get_bunny_status_updater() -> BunnyStatusUpdater:
    """Récupère l'instance du service de mise à jour"""
    global _bunny_status_updater
    
    if _bunny_status_updater is None:
        import os
        api_key = os.environ.get('BUNNY_API_KEY', '4771e914-172d-4abf-aac6e0518b34-44f2-48cd')
        library_id = os.environ.get('BUNNY_LIBRARY_ID', '579861')
        _bunny_status_updater = BunnyStatusUpdater(api_key, library_id)
    
    return _bunny_status_updater
