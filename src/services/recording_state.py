"""
Gestionnaire d'état partagé pour les enregistrements actifs
Permet de partager l'état entre différents modules
"""

from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# État global partagé des enregistrements
_active_recordings: Dict[int, Dict] = {}  # court_id -> recording_session
_recording_sessions: Dict[str, Dict] = {}  # recording_id -> recording_session

class RecordingStateManager:
    """Gestionnaire centralisé de l'état des enregistrements"""
    
    @staticmethod
    def add_recording(court_id: int, recording_session: Dict) -> None:
        """Ajouter un enregistrement actif"""
        global _active_recordings, _recording_sessions
        
        recording_id = recording_session.get('recording_id')
        _active_recordings[court_id] = recording_session
        _recording_sessions[recording_id] = recording_session
        
        logger.info(f"📝 Recording added: {recording_id} on court {court_id}")
        logger.info(f"📊 Total active recordings: {len(_active_recordings)}")
    
    @staticmethod
    def remove_recording(court_id: int = None, recording_id: str = None) -> Optional[Dict]:
        """Supprimer un enregistrement actif"""
        global _active_recordings, _recording_sessions
        
        session = None
        
        # Chercher par court_id ou recording_id
        if court_id and court_id in _active_recordings:
            session = _active_recordings.pop(court_id)
            recording_id = session.get('recording_id')
        elif recording_id and recording_id in _recording_sessions:
            session = _recording_sessions[recording_id]
            court_id = session.get('court_id')
            if court_id in _active_recordings:
                _active_recordings.pop(court_id)
        
        # Supprimer de recording_sessions
        if recording_id and recording_id in _recording_sessions:
            _recording_sessions.pop(recording_id)
        
        if session:
            logger.info(f"🗑️ Recording removed: {recording_id} from court {court_id}")
            logger.info(f"📊 Total active recordings: {len(_active_recordings)}")
        
        return session
    
    @staticmethod
    def is_court_recording(court_id: int) -> bool:
        """Vérifier si un terrain est en cours d'enregistrement"""
        return court_id in _active_recordings
    
    @staticmethod
    def get_court_recording(court_id: int) -> Optional[Dict]:
        """Récupérer l'enregistrement actif d'un terrain"""
        return _active_recordings.get(court_id)
    
    @staticmethod
    def get_recording_by_id(recording_id: str) -> Optional[Dict]:
        """Récupérer un enregistrement par son ID"""
        return _recording_sessions.get(recording_id)
    
    @staticmethod
    def get_all_active_recordings() -> Dict[int, Dict]:
        """Récupérer tous les enregistrements actifs"""
        return _active_recordings.copy()
    
    @staticmethod
    def get_all_recording_sessions() -> Dict[str, Dict]:
        """Récupérer toutes les sessions d'enregistrement"""
        return _recording_sessions.copy()
    
    @staticmethod
    def cleanup_expired_recordings(max_age_hours: int = 24) -> int:
        """Nettoyer les enregistrements expirés"""
        global _recording_sessions
        
        cutoff_time = datetime.utcnow().timestamp() - (max_age_hours * 3600)
        expired_sessions = []
        
        for recording_id, session in _recording_sessions.items():
            if session.get('status') == 'stopped':
                try:
                    end_time_str = session.get('end_time')
                    if end_time_str:
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        if end_time.timestamp() < cutoff_time:
                            expired_sessions.append(recording_id)
                except Exception:
                    pass
        
        # Supprimer les sessions expirées
        for recording_id in expired_sessions:
            if recording_id in _recording_sessions:
                session = _recording_sessions.pop(recording_id)
                court_id = session.get('court_id')
                if court_id in _active_recordings:
                    _active_recordings.pop(court_id)
        
        if expired_sessions:
            logger.info(f"🧹 Cleaned up {len(expired_sessions)} expired recordings")
        
        return len(expired_sessions)
    
    @staticmethod
    def get_stats() -> Dict:
        """Obtenir les statistiques des enregistrements"""
        total_sessions = len(_recording_sessions)
        active_count = len(_active_recordings)
        stopped_count = len([s for s in _recording_sessions.values() if s.get('status') == 'stopped'])
        
        return {
            'total_sessions': total_sessions,
            'active_recordings': active_count,
            'stopped_recordings': stopped_count
        }

# Instance globale du gestionnaire
recording_state = RecordingStateManager()