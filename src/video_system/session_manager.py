"""
Session Manager - Gestion des Sessions Caméra
==============================================

Responsabilités:
- Créer/fermer sessions caméra
- Valider caméras (MJPEG/RTSP)
- Gérer URLs proxy locales
- Cleanup sessions orphelines
"""

import logging
import re
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from pathlib import Path
import subprocess

from .config import VideoConfig
from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


@dataclass
class VideoSession:
    """Session vidéo pour un enregistrement"""
    session_id: str
    terrain_id: int
    club_id: int
    user_id: int
    
    # Camera source
    source_url: str
    camera_type: str  # 'mjpeg' | 'rtsp' | 'http'
    
    # Proxy local
    local_url: str
    proxy_port: int
    proxy_process: Optional[subprocess.Popen] = None
    
    # Recording
    recording_process: Optional[subprocess.Popen] = None
    recording_active: bool = False
    recording_path: Optional[Path] = None
    
    # Status
    verified: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    
    # Errors
    errors: list = field(default_factory=list)
    
    def is_expired(self) -> bool:
        """Vérifier si la session est expirée"""
        timeout = timedelta(seconds=VideoConfig.SESSION_TIMEOUT_SECONDS)
        return datetime.now() - self.last_activity > timeout
    
    def touch(self):
        """Mettre à jour l'activité de la session"""
        self.last_activity = datetime.now()
    
    def to_dict(self) -> dict:
        """Convertir en dictionnaire pour JSON"""
        return {
            'session_id': self.session_id,
            'terrain_id': self.terrain_id,
            'club_id': self.club_id,
            'user_id': self.user_id,
            'source_url': self.source_url,
            'camera_type': self.camera_type,
            'local_url': self.local_url,
            'proxy_port': self.proxy_port,
            'recording_active': self.recording_active,
            'recording_path': str(self.recording_path) if self.recording_path else None,
            'verified': self.verified,
            'created_at': self.created_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'errors': self.errors
        }


class SessionManager:
    """Gestionnaire de sessions vidéo"""
    
    def __init__(self):
        self.sessions: Dict[str, VideoSession] = {}
        self.proxy_manager = ProxyManager()
        logger.info("🎬 SessionManager initialisé")
    
    def create_session(
        self,
        terrain_id: int,
        camera_url: str,
        club_id: int,
        user_id: int
    ) -> VideoSession:
        """
        Créer une nouvelle session caméra
        
        Args:
            terrain_id: ID du terrain
            camera_url: URL de la caméra source
            club_id: ID du club
            user_id: ID de l'utilisateur
            
        Returns:
            VideoSession créée
        """
        # Générer session ID
        timestamp = int(datetime.now().timestamp())
        session_id = f"sess_{club_id}_{terrain_id}_{timestamp}"
        
        logger.info(f"📹 Création session {session_id}")
        logger.info(f"   Club: {club_id}, Terrain: {terrain_id}, User: {user_id}")
        
        # Valider la caméra
        is_valid, camera_type = self.validate_camera(camera_url)
        if not is_valid:
            raise ValueError(f"Caméra invalide: {camera_url}")
        
        logger.info(f"✅ Caméra validée: type={camera_type}")
        
        # Démarrer proxy universel (supporte tous les types)
        try:
            local_url, proxy_port, proxy_process = self.proxy_manager.start_proxy(
                session_id=session_id,
                camera_url=camera_url
            )
            
            logger.info(f"✅ Proxy démarré: {local_url}")
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage proxy: {e}")
            raise
        
        # Créer session
        session = VideoSession(
            session_id=session_id,
            terrain_id=terrain_id,
            club_id=club_id,
            user_id=user_id,
            source_url=camera_url,
            camera_type=camera_type,
            local_url=local_url,
            proxy_port=proxy_port,
            proxy_process=proxy_process,
            verified=True
        )
        
        self.sessions[session_id] = session
        logger.info(f"✅ Session {session_id} créée avec succès")
        
        return session
    
    def validate_camera(self, camera_url: str) -> Tuple[bool, str]:
        """
        Valider une caméra et détecter son type
        
        Args:
            camera_url: URL de la caméra
            
        Returns:
            (is_valid, camera_type)
        """
        logger.info(f"🔍 Validation caméra: {camera_url}")
        
        # Détecter le type basé sur l'URL
        if camera_url.startswith('rtsp://'):
            camera_type = 'rtsp'
            # Pour RTSP, on fait confiance (validation coûteuse avec OpenCV)
            logger.info(f"✅ RTSP détecté, validation rapide")
            return True, camera_type
        
        elif 'mjpg' in camera_url.lower() or 'mjpeg' in camera_url.lower():
            camera_type = 'mjpeg'
            # Tester la connexion HTTP
            try:
                response = requests.get(camera_url, timeout=5, stream=True)
                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')
                    logger.info(f"   Content-Type: {content_type}")
                    return True, camera_type
            except Exception as e:
                logger.error(f"❌ Erreur validation MJPEG: {e}")
                return False, camera_type
        
        else:
            # Type inconnu, essayer HTTP générique
            camera_type = 'http'
            try:
                response = requests.head(camera_url, timeout=5)
                if response.status_code < 400:
                    logger.info(f"✅ HTTP générique validé")
                    return True, camera_type
            except Exception as e:
                logger.error(f"❌ Erreur validation HTTP: {e}")
        
        return False, 'unknown'
    
    def get_session(self, session_id: str) -> Optional[VideoSession]:
        """Obtenir une session par ID"""
        session = self.sessions.get(session_id)
        if session:
            session.touch()  # Mettre à jour activité
        return session
    
    def close_session(self, session_id: str):
        """
        Fermer une session et nettoyer les ressources
        
        Args:
            session_id: ID de la session à fermer
        """
        session = self.sessions.get(session_id)
        if not session:
            logger.warning(f"⚠️ Session {session_id} introuvable")
            return
        
        logger.info(f"🛑 Fermeture session {session_id}")
        
        # Vérifier que l'enregistrement est arrêté
        if session.recording_active:
            logger.error(f"❌ Enregistrement encore actif! Impossible de fermer la session.")
            raise RuntimeError("Recording still active")
        
        # Arrêter le proxy
        if session.proxy_port:
            try:
                self.proxy_manager.stop_proxy(session.proxy_port)
                logger.info(f"✅ Proxy arrêté (port {session.proxy_port})")
            except Exception as e:
                logger.error(f"❌ Erreur arrêt proxy: {e}")
        
        # Supprimer de la liste
        del self.sessions[session_id]
        logger.info(f"✅ Session {session_id} fermée")
    
    def list_sessions(self) -> list:
        """Lister toutes les sessions actives"""
        return [s.to_dict() for s in self.sessions.values()]
    
    def cleanup_orphan_sessions(self):
        """Nettoyer les sessions orphelines (expirées sans enregistrement actif)"""
        orphans = []
        
        for session_id, session in self.sessions.items():
            if session.is_expired() and not session.recording_active:
                orphans.append(session_id)
        
        for session_id in orphans:
            logger.info(f"🧹 Nettoyage session orpheline: {session_id}")
            try:
                self.close_session(session_id)
            except:
                pass
        
        if orphans:
            logger.info(f"✅ {len(orphans)} session(s) orpheline(s) nettoyée(s)")
        
        return len(orphans)


# Instance globale (singleton)
session_manager = SessionManager()
