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
            # Récupérer toutes les vidéos en cours de processing OU en attente (si ID Bunny existe)
            processing_videos = Video.query.filter(
                Video.processing_status.in_(['uploading', 'processing', 'pending']),
                Video.bunny_video_id.isnot(None)
            ).all()
            
            if not processing_videos:
                return
            
            logger.debug(f"🔍 Vérification de {len(processing_videos)} vidéos en processing")
            
            for video in processing_videos:
                try:
                    self._sync_video_status(video, db)
                except Exception as e:
                    logger.error(f"❌ Erreur vérification vidéo {video.id}: {e}")
                time.sleep(0.5)

            # 🆕 Vérifier les clips utilisateur
            from src.models.user import UserClip
            processing_clips = UserClip.query.filter(
                UserClip.status.in_(['processing', 'pending', 'uploading']),
                UserClip.bunny_video_id.isnot(None)
            ).all()

            for clip in processing_clips:
                try:
                    self._sync_clip_status(clip, db)
                except Exception as e:
                    logger.error(f"❌ Erreur vérification clip {clip.id}: {e}")
                time.sleep(0.5)

            # 🆕 Vérifier les highlights
            from src.models.user import HighlightVideo
            processing_highlights = HighlightVideo.query.filter(
                HighlightVideo.generation_status.in_(['processing', 'pending', 'uploading']),
                HighlightVideo.bunny_video_id.isnot(None)
            ).all()

            for highlight in processing_highlights:
                try:
                    self._sync_highlight_status(highlight, db)
                except Exception as e:
                    logger.error(f"❌ Erreur vérification highlight {highlight.id}: {e}")
                time.sleep(0.5)

    def _sync_video_status(self, video, db):
        """Synchronise le statut d'une vidéo avec Bunny CDN"""
        check_url = f"{self.api_base_url}/videos/{video.bunny_video_id}"
        response = requests.get(check_url, headers=self.headers, timeout=10)
        
        if response.status_code == 200:
            video_info = response.json()
            status = video_info.get("status")
            
            if status == 4:  # Finished
                if video.processing_status != 'ready':
                    video.processing_status = 'ready'
                    real_duration = video_info.get("length")
                    if real_duration and real_duration > 0:
                        video.duration = real_duration
                    
                    try:
                        from src.models.notification import Notification, NotificationType
                        Notification.create_notification(
                            user_id=video.user_id,
                            notification_type=NotificationType.VIDEO,
                            title="🎬 Votre vidéo est prête !",
                            message=f"La vidéo '{video.title}' a été traitée avec succès.",
                            link="/dashboard"
                        )
                    except: pass
                    db.session.commit()
            elif status == 5:  # Failed
                video.processing_status = 'failed'
                db.session.commit()
            elif status in [0, 1, 2, 3] and video.processing_status != 'processing':
                video.processing_status = 'processing'
                db.session.commit()
        elif response.status_code == 404:
            video.processing_status = 'failed'
            db.session.commit()

    def _sync_clip_status(self, clip, db):
        """Synchronise le statut d'un clip utilisateur avec Bunny CDN"""
        check_url = f"{self.api_base_url}/videos/{clip.bunny_video_id}"
        response = requests.get(check_url, headers=self.headers, timeout=10)
        
        if response.status_code == 200:
            video_info = response.json()
            status = video_info.get("status")
            
            if status == 4:  # Finished
                if clip.status != 'completed':
                    clip.status = 'completed'
                    clip.completed_at = datetime.utcnow()
                    try:
                        from src.models.notification import Notification, NotificationType
                        Notification.create_notification(
                            user_id=clip.user_id,
                            notification_type=NotificationType.VIDEO_READY,
                            title="🎬 Votre clip est prêt !",
                            message=f"Le clip '{clip.title}' est prêt.",
                            link="/dashboard?tab=clips"
                        )
                    except: pass
                    db.session.commit()
            elif status == 5:
                clip.status = 'failed'
                db.session.commit()
            elif status in [0, 1, 2, 3] and clip.status != 'processing':
                clip.status = 'processing'
                db.session.commit()
        elif response.status_code == 404:
            clip.status = 'failed'
            db.session.commit()

    def _sync_highlight_status(self, highlight, db):
        """Synchronise le statut d'un highlight avec Bunny CDN"""
        check_url = f"{self.api_base_url}/videos/{highlight.bunny_video_id}"
        response = requests.get(check_url, headers=self.headers, timeout=10)
        
        if response.status_code == 200:
            video_info = response.json()
            status = video_info.get("status")
            
            if status == 4:  # Finished
                if highlight.generation_status != 'completed':
                    highlight.generation_status = 'completed'
                    highlight.completed_at = datetime.utcnow()
                    db.session.commit()
            elif status == 5:
                highlight.generation_status = 'failed'
                db.session.commit()
            elif status in [0, 1, 2, 3] and highlight.generation_status != 'processing':
                highlight.generation_status = 'processing'
                db.session.commit()
        elif response.status_code == 404:
            highlight.generation_status = 'failed'
            db.session.commit()


# Instance globale
_bunny_status_updater = None


def get_bunny_status_updater() -> BunnyStatusUpdater:
    """Récupère l'instance du service de mise à jour"""
    global _bunny_status_updater
    
    if _bunny_status_updater is None:
        import os
        api_key = os.environ.get('BUNNY_API_KEY', 'ac7bcccc-69bc-47aa-ae8fed1c3364-5693-4e1b')
        library_id = os.environ.get('BUNNY_LIBRARY_ID', '589708')
        _bunny_status_updater = BunnyStatusUpdater(api_key, library_id)
    
    return _bunny_status_updater
