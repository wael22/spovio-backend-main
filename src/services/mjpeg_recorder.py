"""
Système d'enregistrement MJPEG vers Bunny Stream
Basé sur FFmpeg pour la capture et l'API Bunny Stream pour l'upload
"""

import os
import time
import uuid
import requests
import subprocess
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps

from ..mjpeg_config.mjpeg_config import MJPEGRecorderConfig

logger = logging.getLogger(__name__)


def retry_on_failure(max_retries=3, delay=5):
    """Décorateur pour retry automatique"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    logger.warning(f"Tentative {attempt + 1} échouée: {e}")
                    time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator


class UploadMonitor:
    """Monitoring des uploads vers Bunny Stream"""
    
    def __init__(self):
        self.upload_stats = {
            'total_uploads': 0,
            'successful_uploads': 0,
            'failed_uploads': 0,
            'total_size_mb': 0
        }
    
    def log_upload(self, success: bool, file_size_mb: float):
        """Enregistre les statistiques d'upload"""
        self.upload_stats['total_uploads'] += 1
        self.upload_stats['total_size_mb'] += file_size_mb
        
        if success:
            self.upload_stats['successful_uploads'] += 1
        else:
            self.upload_stats['failed_uploads'] += 1
    
    def get_success_rate(self) -> float:
        """Calcule le taux de succès des uploads"""
        if self.upload_stats['total_uploads'] == 0:
            return 0
        return (self.upload_stats['successful_uploads'] / 
                self.upload_stats['total_uploads']) * 100
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques complètes"""
        return {
            **self.upload_stats,
            'success_rate': self.get_success_rate()
        }


class MJPEGToBunnyRecorder:
    """Classe principale pour l'enregistrement MJPEG vers Bunny Stream"""
    
    def __init__(self, config: MJPEGRecorderConfig):
        self.config = config
        self.is_recording = False
        self.recording_process = None
        self.recording_thread = None
        self.upload_monitor = UploadMonitor()
        self.recording_stats = {
            'start_time': None,
            'segments_created': 0,
            'segments_uploaded': 0,
            'current_segment': None
        }
        
        # Créer le répertoire temporaire
        os.makedirs(self.config.temp_dir, exist_ok=True)
        
        # Valider la configuration
        if not self.config.validate():
            raise ValueError("Configuration invalide")
    
    def test_mjpeg_connection(self) -> bool:
        """Test de connexion au flux MJPEG"""
        try:
            response = requests.get(
                self.config.mjpeg_url, 
                timeout=10,
                stream=True
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Échec de connexion MJPEG: {e}")
            return False
    
    def test_ffmpeg_availability(self) -> bool:
        """Test de disponibilité de FFmpeg"""
        try:
            result = subprocess.run(
                [self.config.ffmpeg_path, '-version'],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"FFmpeg non disponible: {e}")
            return False
    
    @retry_on_failure(max_retries=3)
    def upload_video_segment(self, video_path: str, title: str) -> bool:
        """Upload un segment vidéo vers Bunny Stream"""
        try:
            # 1. Créer la vidéo dans Bunny Stream
            create_data = {
                'title': title,
                'description': f"Enregistrement automatique {datetime.now()}",
                'tags': ['auto-recording', 'mjpeg']
            }
            
            response = requests.post(
                f"{self.config.base_url}/library/{self.config.library_id}/videos",
                headers={'AccessKey': self.config.bunny_api_key},
                json=create_data,
                timeout=30
            )
            response.raise_for_status()
            
            video_guid = response.json()['guid']
            logger.info(f"Vidéo créée dans Bunny Stream: {video_guid}")
            
            # 2. Uploader le fichier
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            
            with open(video_path, 'rb') as video_file:
                upload_response = requests.put(
                    f"{self.config.base_url}/library/{self.config.library_id}/videos/{video_guid}",
                    headers={'AccessKey': self.config.bunny_api_key},
                    data=video_file,
                    timeout=self.config.upload_timeout
                )
                upload_response.raise_for_status()
            
            logger.info(f"Upload réussi: {title} ({file_size_mb:.1f} MB)")
            self.upload_monitor.log_upload(True, file_size_mb)
            self.recording_stats['segments_uploaded'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Échec d'upload pour {title}: {e}")
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0
            self.upload_monitor.log_upload(False, file_size_mb)
            return False
    
    def _cleanup_old_files(self):
        """Nettoie les fichiers temporaires anciens"""
        try:
            current_time = time.time()
            max_age_seconds = self.config.max_age_hours * 3600
            
            for filename in os.listdir(self.config.temp_dir):
                file_path = os.path.join(self.config.temp_dir, filename)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > max_age_seconds:
                        os.remove(file_path)
                        logger.info(f"Fichier temporaire supprimé: {filename}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage: {e}")
    
    def _recording_worker(self, segment_duration: int = None):
        """Worker pour l'enregistrement en arrière-plan"""
        if segment_duration is None:
            segment_duration = self.config.segment_duration
        
        segment_number = 0
        
        while self.is_recording:
            try:
                segment_number += 1
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                segment_filename = f"segment_{timestamp}_{segment_number:04d}.mp4"
                segment_path = os.path.join(self.config.temp_dir, segment_filename)
                
                self.recording_stats['current_segment'] = segment_filename
                
                # Commande FFmpeg pour capturer un segment
                cmd = [
                    self.config.ffmpeg_path,
                    '-i', self.config.mjpeg_url,
                    '-t', str(segment_duration),
                    '-c:v', 'libx264',
                    '-preset', self.config.preset,
                    '-crf', str(self.config.video_quality),
                    '-y',  # Overwrite output files
                    segment_path
                ]
                
                logger.info(f"Démarrage capture segment {segment_number}")
                
                # Exécuter FFmpeg
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=segment_duration + 30  # Timeout avec marge
                )
                
                if result.returncode == 0 and os.path.exists(segment_path):
                    self.recording_stats['segments_created'] += 1
                    
                    # Upload vers Bunny Stream
                    video_title = f"Segment {segment_number} - {timestamp}"
                    upload_success = self.upload_video_segment(segment_path, video_title)
                    
                    # Nettoyer le fichier local après upload
                    if upload_success:
                        os.remove(segment_path)
                    
                else:
                    logger.error(f"Échec de capture segment {segment_number}: {result.stderr}")
                
            except subprocess.TimeoutExpired:
                logger.error(f"Timeout lors de la capture du segment {segment_number}")
            except Exception as e:
                logger.error(f"Erreur lors de l'enregistrement du segment {segment_number}: {e}")
            
            # Nettoyage périodique
            if segment_number % 10 == 0:
                self._cleanup_old_files()
    
    def start_recording(self, segment_duration: int = None) -> bool:
        """Démarre l'enregistrement"""
        if self.is_recording:
            logger.warning("Enregistrement déjà en cours")
            return False
        
        # Tests préliminaires
        if not self.test_mjpeg_connection():
            logger.error("Impossible de se connecter au flux MJPEG")
            return False
        
        if not self.test_ffmpeg_availability():
            logger.error("FFmpeg non disponible")
            return False
        
        # Initialiser les statistiques
        self.recording_stats = {
            'start_time': datetime.now(),
            'segments_created': 0,
            'segments_uploaded': 0,
            'current_segment': None
        }
        
        # Démarrer l'enregistrement
        self.is_recording = True
        self.recording_thread = threading.Thread(
            target=self._recording_worker,
            args=(segment_duration,),
            daemon=True
        )
        self.recording_thread.start()
        
        logger.info("Enregistrement MJPEG démarré")
        return True
    
    def stop_recording(self) -> bool:
        """Arrête l'enregistrement"""
        if not self.is_recording:
            logger.warning("Aucun enregistrement en cours")
            return False
        
        self.is_recording = False
        
        # Attendre la fin du thread d'enregistrement
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=10)
        
        logger.info("Enregistrement MJPEG arrêté")
        return True
    
    def get_recording_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de l'enregistrement"""
        stats = {
            **self.recording_stats,
            'is_recording': self.is_recording,
            'upload_stats': self.upload_monitor.get_stats()
        }
        
        if stats['start_time']:
            stats['duration_seconds'] = (datetime.now() - stats['start_time']).total_seconds()
        
        return stats
    
    def get_status(self) -> Dict[str, Any]:
        """Retourne le statut complet du recorder"""
        return {
            'is_recording': self.is_recording,
            'config': self.config.to_dict(),
            'stats': self.get_recording_stats()
        }
