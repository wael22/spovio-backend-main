"""
Service d'enregistrement vidéo modernisé basé sur MJPEG et Bunny Stream
Remplace complètement l'ancien système d'enregistrement
"""

import logging
import threading
from typing import Dict, Any, Optional
from datetime import datetime

from .mjpeg_recorder import MJPEGToBunnyRecorder
from ..mjpeg_config.mjpeg_config import MJPEGRecorderConfig

logger = logging.getLogger(__name__)


class VideoRecordingService:
    """Service principal pour la gestion des enregistrements vidéo"""
    
    def __init__(self, config: Optional[MJPEGRecorderConfig] = None):
        """Initialise le service d'enregistrement"""
        self.config = config or MJPEGRecorderConfig.from_env()
        self.active_recordings: Dict[str, MJPEGToBunnyRecorder] = {}
        self.recording_lock = threading.Lock()
        
        logger.info("🔧 Service d'enregistrement vidéo initialisé")
    
    def start_recording(self, recording_id: str, duration: int = None) -> Dict[str, Any]:
        """Démarre un nouvel enregistrement
        
        Args:
            recording_id: Identifiant unique de l'enregistrement
            duration: Durée des segments en secondes (optionnel)
            
        Returns:
            Dict contenant le statut de l'opération
        """
        with self.recording_lock:
            # Vérifier si l'enregistrement existe déjà
            if recording_id in self.active_recordings:
                return {
                    'success': False,
                    'error': 'Enregistrement déjà en cours',
                    'recording_id': recording_id
                }
            
            try:
                # Créer une nouvelle instance du recorder
                recorder = MJPEGToBunnyRecorder(self.config)
                
                # Démarrer l'enregistrement
                if recorder.start_recording(duration):
                    self.active_recordings[recording_id] = recorder
                    
                    logger.info(f"✅ Enregistrement démarré: {recording_id}")
                    
                    return {
                        'success': True,
                        'message': 'Enregistrement démarré avec succès',
                        'recording_id': recording_id,
                        'start_time': datetime.now().isoformat(),
                        'config': self.config.to_dict()
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Impossible de démarrer l\'enregistrement',
                        'recording_id': recording_id
                    }
                    
            except Exception as e:
                logger.error(f"Erreur lors du démarrage de l'enregistrement {recording_id}: {e}")
                return {
                    'success': False,
                    'error': f'Erreur interne: {str(e)}',
                    'recording_id': recording_id
                }
    
    def stop_recording(self, recording_id: str) -> Dict[str, Any]:
        """Arrête un enregistrement
        
        Args:
            recording_id: Identifiant de l'enregistrement à arrêter
            
        Returns:
            Dict contenant le statut de l'opération
        """
        with self.recording_lock:
            if recording_id not in self.active_recordings:
                return {
                    'success': False,
                    'error': 'Enregistrement non trouvé',
                    'recording_id': recording_id
                }
            
            try:
                recorder = self.active_recordings[recording_id]
                
                # Récupérer les statistiques finales
                final_stats = recorder.get_recording_stats()
                
                # Arrêter l'enregistrement
                if recorder.stop_recording():
                    # Supprimer de la liste des enregistrements actifs
                    del self.active_recordings[recording_id]
                    
                    logger.info(f"⏹️ Enregistrement arrêté: {recording_id}")
                    
                    return {
                        'success': True,
                        'message': 'Enregistrement arrêté avec succès',
                        'recording_id': recording_id,
                        'final_stats': final_stats
                    }
                else:
                    return {
                        'success': False,
                        'error': 'Erreur lors de l\'arrêt',
                        'recording_id': recording_id
                    }
                    
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt de l'enregistrement {recording_id}: {e}")
                return {
                    'success': False,
                    'error': f'Erreur interne: {str(e)}',
                    'recording_id': recording_id
                }
    
    def get_recording_status(self, recording_id: str) -> Dict[str, Any]:
        """Récupère le statut d'un enregistrement
        
        Args:
            recording_id: Identifiant de l'enregistrement
            
        Returns:
            Dict contenant les informations de statut
        """
        with self.recording_lock:
            if recording_id not in self.active_recordings:
                return {
                    'exists': False,
                    'recording_id': recording_id,
                    'message': 'Enregistrement non trouvé'
                }
            
            try:
                recorder = self.active_recordings[recording_id]
                stats = recorder.get_recording_stats()
                
                return {
                    'exists': True,
                    'recording_id': recording_id,
                    'is_recording': recorder.is_recording,
                    'stats': stats,
                    'config': self.config.to_dict()
                }
                
            except Exception as e:
                logger.error(f"Erreur lors de la récupération du statut {recording_id}: {e}")
                return {
                    'exists': True,
                    'recording_id': recording_id,
                    'error': f'Erreur interne: {str(e)}'
                }
    
    def get_active_recordings(self) -> Dict[str, Any]:
        """Récupère la liste de tous les enregistrements actifs
        
        Returns:
            Dict contenant la liste des enregistrements actifs
        """
        with self.recording_lock:
            active_list = []
            
            for recording_id, recorder in self.active_recordings.items():
                try:
                    stats = recorder.get_recording_stats()
                    active_list.append({
                        'recording_id': recording_id,
                        'is_recording': recorder.is_recording,
                        'start_time': stats.get('start_time').isoformat() if stats.get('start_time') else None,
                        'segments_created': stats.get('segments_created', 0),
                        'segments_uploaded': stats.get('segments_uploaded', 0),
                        'duration_seconds': stats.get('duration_seconds', 0)
                    })
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération des stats pour {recording_id}: {e}")
                    active_list.append({
                        'recording_id': recording_id,
                        'error': 'Erreur de récupération des statistiques'
                    })
            
            return {
                'count': len(active_list),
                'active_recordings': active_list,
                'service_config': self.config.to_dict()
            }
    
    def stop_all_recordings(self) -> Dict[str, Any]:
        """Arrête tous les enregistrements actifs
        
        Returns:
            Dict contenant le résumé des opérations
        """
        with self.recording_lock:
            stopped_count = 0
            errors = []
            
            # Copier la liste des IDs pour éviter les modifications concurrentes
            recording_ids = list(self.active_recordings.keys())
            
            for recording_id in recording_ids:
                try:
                    result = self.stop_recording(recording_id)
                    if result['success']:
                        stopped_count += 1
                    else:
                        errors.append(f"{recording_id}: {result['error']}")
                except Exception as e:
                    errors.append(f"{recording_id}: {str(e)}")
            
            logger.info(f"🛑 Arrêt de tous les enregistrements: {stopped_count} arrêtés, {len(errors)} erreurs")
            
            return {
                'success': len(errors) == 0,
                'stopped_count': stopped_count,
                'total_count': len(recording_ids),
                'errors': errors
            }
    
    def get_service_status(self) -> Dict[str, Any]:
        """Récupère le statut général du service
        
        Returns:
            Dict contenant le statut du service
        """
        with self.recording_lock:
            return {
                'service_name': 'VideoRecordingService',
                'version': '2.0.0-mjpeg',
                'active_recordings_count': len(self.active_recordings),
                'config': self.config.to_dict(),
                'timestamp': datetime.now().isoformat()
            }


# Instance globale du service
video_recording_service = VideoRecordingService()

logger.info("🎥 Service d'enregistrement vidéo MJPEG initialisé")
