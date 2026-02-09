"""
Service d'enregistrement MJPEG vers Bunny Stream pour PadelVar.
Capture les flux MJPEG des caméras de terrains et les upload automatiquement.
"""

import os
import subprocess
import time
import logging
import threading
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

class MJPEGRecordingConfig:
    """Configuration pour l'enregistrement MJPEG"""
    
    def __init__(self):
        # Configuration Bunny Stream
        self.bunny_api_key = os.getenv('BUNNY_API_KEY', 'ac7bcccc-69bc-47aa-ae8fed1c3364-5693-4e1b')  # Updated 2026-02-01
        self.bunny_library_id = os.getenv('BUNNY_LIBRARY_ID', '589708')  # Updated 2026-02-01
        self.bunny_base_url = 'https://video.bunnycdn.com'
        
        # Configuration FFmpeg
        self.ffmpeg_path = self._find_ffmpeg()
        self.video_quality = 23  # CRF value (18-28 recommandé)
        self.preset = 'fast'
        self.segment_duration = 300  # 5 minutes par défaut
        
        # Configuration des fichiers temporaires
        self.temp_dir = tempfile.gettempdir()
        self.cleanup_temp_files = True
        
        # Configuration de retry
        self.max_retries = 3
        self.retry_delay = 5
        
        # Configuration monitoring
        self.upload_timeout = 300  # 5 minutes
    
    def _find_ffmpeg(self) -> str:
        """Trouve l'exécutable FFmpeg"""
        # Chercher dans les chemins courants (ordre prioritaire)
        for path in [
            r'C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe',
            'ffmpeg',
            './ffmpeg/bin/ffmpeg.exe',
            r'C:\ffmpeg\bin\ffmpeg.exe',
            '/usr/bin/ffmpeg',
            '/usr/local/bin/ffmpeg'
        ]:
            if os.path.exists(path) or self._test_ffmpeg_command(path):
                return path
        
        # Si pas trouvé, utiliser le nom par défaut et espérer qu'il soit dans PATH
        return 'ffmpeg'
    
    def _test_ffmpeg_command(self, path: str) -> bool:
        """Test si FFmpeg est accessible"""
        try:
            subprocess.run([path, '-version'], 
                         capture_output=True, 
                         timeout=5, 
                         check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

class MJPEGToBunnyRecorder:
    """
    Classe principale pour l'enregistrement MJPEG vers Bunny Stream.
    Gère la capture, segmentation et upload automatique.
    """
    
    def __init__(self, mjpeg_url: str, config: Optional[MJPEGRecordingConfig] = None):
        self.mjpeg_url = mjpeg_url
        self.config = config or MJPEGRecordingConfig()
        
        # État de l'enregistrement
        self.is_recording = False
        self.recording_session_id = None
        self.recording_thread = None
        self.ffmpeg_process = None
        
        # Statistiques
        self.stats = {
            'start_time': None,
            'segments_created': 0,
            'successful_uploads': 0,
            'failed_uploads': 0,
            'total_size_mb': 0,
            'last_segment_time': None
        }
        
        # Callbacks pour les événements
        self.on_segment_created = None
        self.on_upload_success = None
        self.on_upload_failure = None
        self.on_recording_error = None
        
        logger.info(f"🎬 MJPEGToBunnyRecorder initialisé pour {mjpeg_url}")
    
    def test_mjpeg_connection(self) -> bool:
        """Test la connexion au flux MJPEG"""
        try:
            response = requests.get(self.mjpeg_url, 
                                  stream=True, 
                                  timeout=10)
            response.raise_for_status()
            
            # Vérifier le content-type
            content_type = response.headers.get('content-type', '').lower()
            if 'multipart' in content_type or 'mjpeg' in content_type:
                logger.info("✅ Connexion MJPEG réussie")
                return True
            else:
                logger.warning(f"⚠️ Content-type inattendu: {content_type}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erreur de connexion MJPEG: {e}")
            return False
    
    def start_recording(self, session_name: str, segment_duration: Optional[int] = None) -> Dict[str, Any]:
        """
        Démarre l'enregistrement MJPEG avec segmentation automatique.
        
        Args:
            session_name: Nom de la session d'enregistrement
            segment_duration: Durée des segments en secondes
            
        Returns:
            Informations sur la session démarrée
        """
        if self.is_recording:
            raise ValueError("Un enregistrement est déjà en cours")
        
        # Configuration de la session
        self.recording_session_id = str(uuid.uuid4())
        segment_duration = segment_duration or self.config.segment_duration
        
        # Initialiser les statistiques
        self.stats = {
            'start_time': datetime.now(),
            'segments_created': 0,
            'successful_uploads': 0,
            'failed_uploads': 0,
            'total_size_mb': 0,
            'last_segment_time': None,
            'session_name': session_name,
            'segment_duration': segment_duration
        }
        
        # Test de connexion
        if not self.test_mjpeg_connection():
            raise ConnectionError("Impossible de se connecter au flux MJPEG")
        
        # Démarrer l'enregistrement en arrière-plan
        self.is_recording = True
        self.recording_thread = threading.Thread(
            target=self._recording_loop,
            args=(session_name, segment_duration),
            daemon=True
        )
        self.recording_thread.start()
        
        logger.info(f"🎬 Enregistrement démarré: {session_name} (session: {self.recording_session_id})")
        
        return {
            'session_id': self.recording_session_id,
            'session_name': session_name,
            'mjpeg_url': self.mjpeg_url,
            'segment_duration': segment_duration,
            'start_time': self.stats['start_time'].isoformat(),
            'status': 'recording'
        }
    
    def stop_recording(self) -> Dict[str, Any]:
        """
        Arrête l'enregistrement en cours.
        
        Returns:
            Statistiques finales de l'enregistrement
        """
        if not self.is_recording:
            return {'error': 'Aucun enregistrement en cours'}
        
        logger.info(f"⏹️ Arrêt de l'enregistrement {self.recording_session_id}")
        
        # Arrêter l'enregistrement
        self.is_recording = False
        
        # Arrêter le processus FFmpeg s'il existe
        if self.ffmpeg_process:
            try:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.ffmpeg_process.kill()
            except Exception as e:
                logger.error(f"Erreur lors de l'arrêt de FFmpeg: {e}")
        
        # Attendre que le thread se termine
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=10)
        
        # Calculer les statistiques finales
        duration = None
        if self.stats['start_time']:
            duration = (datetime.now() - self.stats['start_time']).total_seconds()
        
        success_rate = 0
        if self.stats['segments_created'] > 0:
            success_rate = (self.stats['successful_uploads'] / self.stats['segments_created']) * 100
        
        final_stats = {
            'session_id': self.recording_session_id,
            'duration_seconds': duration,
            'segments_created': self.stats['segments_created'],
            'successful_uploads': self.stats['successful_uploads'],
            'failed_uploads': self.stats['failed_uploads'],
            'total_size_mb': round(self.stats['total_size_mb'], 2),
            'success_rate_percent': round(success_rate, 2),
            'status': 'stopped'
        }
        
        logger.info(f"📊 Enregistrement terminé: {final_stats}")
        return final_stats
    
    def get_recording_status(self) -> Dict[str, Any]:
        """Retourne le statut actuel de l'enregistrement"""
        if not self.is_recording:
            return {'status': 'stopped', 'is_recording': False}
        
        current_time = datetime.now()
        duration = None
        if self.stats['start_time']:
            duration = (current_time - self.stats['start_time']).total_seconds()
        
        return {
            'status': 'recording',
            'is_recording': True,
            'session_id': self.recording_session_id,
            'session_name': self.stats.get('session_name'),
            'duration_seconds': duration,
            'segments_created': self.stats['segments_created'],
            'successful_uploads': self.stats['successful_uploads'],
            'failed_uploads': self.stats['failed_uploads'],
            'total_size_mb': round(self.stats['total_size_mb'], 2),
            'last_segment_time': self.stats['last_segment_time'].isoformat() if self.stats['last_segment_time'] else None
        }
    
    def _recording_loop(self, session_name: str, segment_duration: int):
        """Boucle principale d'enregistrement avec segmentation"""
        try:
            logger.info(f"🔄 Démarrage de la boucle d'enregistrement (segments de {segment_duration}s)")
            
            # Créer le répertoire temporaire pour cette session
            session_temp_dir = os.path.join(self.config.temp_dir, f"mjpeg_recording_{self.recording_session_id}")
            os.makedirs(session_temp_dir, exist_ok=True)
            
            segment_counter = 0
            
            while self.is_recording:
                segment_counter += 1
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                segment_filename = f"{session_name}_{timestamp}_segment_{segment_counter:03d}.mp4"
                segment_path = os.path.join(session_temp_dir, segment_filename)
                
                # Enregistrer le segment avec FFmpeg
                if self._record_segment(segment_path, segment_duration):
                    self.stats['segments_created'] += 1
                    self.stats['last_segment_time'] = datetime.now()
                    
                    # Callback pour segment créé
                    if self.on_segment_created:
                        self.on_segment_created(segment_path, segment_counter)
                    
                    # Upload vers Bunny Stream
                    upload_success = self._upload_segment_to_bunny(
                        segment_path, 
                        f"{session_name} - Segment {segment_counter}",
                        segment_counter
                    )
                    
                    if upload_success:
                        self.stats['successful_uploads'] += 1
                        if self.on_upload_success:
                            self.on_upload_success(segment_path, segment_counter)
                    else:
                        self.stats['failed_uploads'] += 1
                        if self.on_upload_failure:
                            self.on_upload_failure(segment_path, segment_counter)
                    
                    # Nettoyer le fichier temporaire
                    if self.config.cleanup_temp_files:
                        try:
                            os.remove(segment_path)
                        except Exception as e:
                            logger.warning(f"Impossible de supprimer {segment_path}: {e}")
                else:
                    logger.error(f"❌ Échec de l'enregistrement du segment {segment_counter}")
                    if not self.is_recording:
                        break
            
            # Nettoyer le répertoire temporaire
            if self.config.cleanup_temp_files:
                try:
                    os.rmdir(session_temp_dir)
                except Exception as e:
                    logger.warning(f"Impossible de supprimer le répertoire temporaire: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Erreur dans la boucle d'enregistrement: {e}")
            if self.on_recording_error:
                self.on_recording_error(e)
        finally:
            self.is_recording = False
            logger.info("🏁 Boucle d'enregistrement terminée")
    
    def _record_segment(self, output_path: str, duration: int) -> bool:
        """
        Enregistre un segment vidéo avec FFmpeg.
        
        Args:
            output_path: Chemin de sortie du segment
            duration: Durée du segment en secondes
            
        Returns:
            True si l'enregistrement a réussi
        """
        try:
            # Commande FFmpeg pour capturer MJPEG et convertir en MP4
            ffmpeg_cmd = [
                self.config.ffmpeg_path,
                '-f', 'mjpeg',
                '-i', self.mjpeg_url,
                '-t', str(duration),
                '-c:v', 'libx264',
                '-preset', self.config.preset,
                '-crf', str(self.config.video_quality),
                '-movflags', '+faststart',
                '-y',  # Écraser le fichier s'il existe
                output_path
            ]
            
            logger.debug(f"🎬 FFmpeg cmd: {' '.join(ffmpeg_cmd)}")
            
            # Exécuter FFmpeg
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Attendre la fin du processus
            stdout, stderr = self.ffmpeg_process.communicate()
            
            if self.ffmpeg_process.returncode == 0:
                # Vérifier que le fichier a été créé et a une taille raisonnable
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    self.stats['total_size_mb'] += file_size_mb
                    logger.info(f"✅ Segment enregistré: {os.path.basename(output_path)} ({file_size_mb:.2f} MB)")
                    return True
                else:
                    logger.error(f"❌ Fichier segment invalide: {output_path}")
                    return False
            else:
                logger.error(f"❌ Erreur FFmpeg (code {self.ffmpeg_process.returncode}): {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'enregistrement du segment: {e}")
            return False
        finally:
            self.ffmpeg_process = None
    
    def _upload_segment_to_bunny(self, video_path: str, title: str, segment_number: int) -> bool:
        """
        Upload un segment vers Bunny Stream avec retry automatique.
        
        Args:
            video_path: Chemin du fichier vidéo
            title: Titre de la vidéo
            segment_number: Numéro du segment
            
        Returns:
            True si l'upload a réussi
        """
        for attempt in range(self.config.max_retries):
            try:
                # 1. Créer la vidéo dans Bunny Stream
                create_data = {
                    'title': title,
                    'description': f"Enregistrement automatique MJPEG - Session {self.recording_session_id} - Segment {segment_number}",
                    'tags': ['padelvar', 'mjpeg', 'auto-recording', f'session-{self.recording_session_id}']
                }
                
                response = requests.post(
                    f"{self.config.bunny_base_url}/library/{self.config.bunny_library_id}/videos",
                    headers={'AccessKey': self.config.bunny_api_key},
                    json=create_data,
                    timeout=30
                )
                response.raise_for_status()
                
                video_data = response.json()
                video_guid = video_data['guid']
                
                logger.debug(f"📝 Vidéo créée dans Bunny Stream: {video_guid}")
                
                # 2. Uploader le fichier vidéo
                with open(video_path, 'rb') as video_file:
                    upload_response = requests.put(
                        f"{self.config.bunny_base_url}/library/{self.config.bunny_library_id}/videos/{video_guid}",
                        headers={'AccessKey': self.config.bunny_api_key},
                        data=video_file,
                        timeout=self.config.upload_timeout
                    )
                    upload_response.raise_for_status()
                
                file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
                logger.info(f"☁️ Upload réussi vers Bunny Stream: {title} ({file_size_mb:.2f} MB) - GUID: {video_guid}")
                
                return True
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ Tentative {attempt + 1}/{self.config.max_retries} échouée pour {title}: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    logger.error(f"❌ Échec définitif de l'upload pour {title}")
                    
            except Exception as e:
                logger.error(f"❌ Erreur inattendue lors de l'upload {title}: {e}")
                break
        
        return False

class MJPEGRecordingManager:
    """
    Gestionnaire pour plusieurs enregistrements MJPEG simultanés.
    Permet de gérer plusieurs caméras en parallèle.
    """
    
    def __init__(self, config: Optional[MJPEGRecordingConfig] = None):
        self.config = config or MJPEGRecordingConfig()
        self.active_recordings: Dict[str, MJPEGToBunnyRecorder] = {}
        self.lock = threading.Lock()
        
        logger.info("🎮 MJPEGRecordingManager initialisé")
    
    def start_recording(self, recording_id: str, mjpeg_url: str, session_name: str, segment_duration: Optional[int] = None) -> Dict[str, Any]:
        """
        Démarre un nouvel enregistrement.
        
        Args:
            recording_id: Identifiant unique de l'enregistrement
            mjpeg_url: URL du flux MJPEG
            session_name: Nom de la session
            segment_duration: Durée des segments en secondes
            
        Returns:
            Informations sur la session démarrée
        """
        with self.lock:
            if recording_id in self.active_recordings:
                raise ValueError(f"Un enregistrement avec l'ID {recording_id} est déjà actif")
            
            # Créer le recorder
            recorder = MJPEGToBunnyRecorder(mjpeg_url, self.config)
            
            # Configurer les callbacks
            recorder.on_segment_created = lambda path, num: self._on_segment_created(recording_id, path, num)
            recorder.on_upload_success = lambda path, num: self._on_upload_success(recording_id, path, num)
            recorder.on_upload_failure = lambda path, num: self._on_upload_failure(recording_id, path, num)
            recorder.on_recording_error = lambda error: self._on_recording_error(recording_id, error)
            
            # Démarrer l'enregistrement
            result = recorder.start_recording(session_name, segment_duration)
            
            # Stocker le recorder
            self.active_recordings[recording_id] = recorder
            
            logger.info(f"🎬 Enregistrement {recording_id} démarré")
            return result
    
    def stop_recording(self, recording_id: str) -> Dict[str, Any]:
        """Arrête un enregistrement spécifique"""
        with self.lock:
            if recording_id not in self.active_recordings:
                return {'error': f'Enregistrement {recording_id} non trouvé'}
            
            recorder = self.active_recordings[recording_id]
            result = recorder.stop_recording()
            
            # Supprimer de la liste des enregistrements actifs
            del self.active_recordings[recording_id]
            
            logger.info(f"⏹️ Enregistrement {recording_id} arrêté")
            return result
    
    def get_recording_status(self, recording_id: str) -> Dict[str, Any]:
        """Retourne le statut d'un enregistrement"""
        with self.lock:
            if recording_id not in self.active_recordings:
                return {'error': f'Enregistrement {recording_id} non trouvé'}
            
            return self.active_recordings[recording_id].get_recording_status()
    
    def get_all_recordings_status(self) -> Dict[str, Dict[str, Any]]:
        """Retourne le statut de tous les enregistrements actifs"""
        with self.lock:
            return {
                recording_id: recorder.get_recording_status()
                for recording_id, recorder in self.active_recordings.items()
            }
    
    def stop_all_recordings(self) -> Dict[str, Dict[str, Any]]:
        """Arrête tous les enregistrements actifs"""
        results = {}
        recording_ids = list(self.active_recordings.keys())
        
        for recording_id in recording_ids:
            results[recording_id] = self.stop_recording(recording_id)
        
        return results
    
    def _on_segment_created(self, recording_id: str, path: str, segment_number: int):
        """Callback appelé quand un segment est créé"""
        logger.debug(f"📹 Segment {segment_number} créé pour {recording_id}: {os.path.basename(path)}")
    
    def _on_upload_success(self, recording_id: str, path: str, segment_number: int):
        """Callback appelé quand un upload réussit"""
        logger.debug(f"☁️ Upload réussi pour {recording_id}, segment {segment_number}")
    
    def _on_upload_failure(self, recording_id: str, path: str, segment_number: int):
        """Callback appelé quand un upload échoue"""
        logger.warning(f"❌ Échec upload pour {recording_id}, segment {segment_number}")
    
    def _on_recording_error(self, recording_id: str, error: Exception):
        """Callback appelé en cas d'erreur d'enregistrement"""
        logger.error(f"❌ Erreur enregistrement {recording_id}: {error}")
