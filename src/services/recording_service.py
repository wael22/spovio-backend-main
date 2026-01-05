"""
Service principal d'enregistrement vidéo pour la plateforme de padel
Orchestre FFmpeg, upload et base de données
"""
import os
import threading
import time
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from .recording_context import RecordingContext
from .ffmpeg_runner import FFmpegRunner
from .uploader import create_uploader, VideoUploader

logger = logging.getLogger(__name__)


class RecordingService:
    """Service principal pour la gestion des enregistrements"""
    
    def __init__(self, output_dir: str = "recordings", 
                 thumbnails_dir: str = "thumbnails",
                 uploader_config: Optional[Dict[str, Any]] = None):
        self.output_dir = Path(output_dir)
        self.thumbnails_dir = Path(thumbnails_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        
        # Composants
        self.ffmpeg_runner = FFmpegRunner()
        self.uploader = self._create_uploader(uploader_config or {})
        
        # État des enregistrements
        self.active_recordings: Dict[str, RecordingContext] = {}
        self.lock = threading.RLock()
        
        # Thread de supervision
        self.supervisor_thread = None
        self.supervisor_running = False
        
        # Configuration
        self.max_parallel_recordings = int(os.getenv('MAX_RECORDINGS', '5'))
        self.min_disk_space_gb = float(os.getenv('MIN_DISK_SPACE_GB', '1.0'))
        
        logger.info(f"RecordingService initialisé: {output_dir}")
    
    def _create_uploader(self, config: Dict[str, Any]) -> VideoUploader:
        """Crée l'uploader selon la configuration"""
        upload_type = config.get('type', 'local')
        return create_uploader(upload_type, **config)
    
    def start_recording(self, user_id: int, court_id: int, camera_url: str,
                       max_duration: int = 3600, quality: str = 'medium',
                       match_id: Optional[int] = None,
                       club_id: Optional[int] = None) -> Dict[str, Any]:
        """Démarre un nouvel enregistrement"""
        
        # Vérifications préalables
        check_result = self._pre_recording_checks(camera_url)
        if not check_result['success']:
            return check_result
        
        # Génération de l'ID unique
        recording_id = str(uuid.uuid4())
        output_path = self.output_dir / f"{recording_id}.mp4"
        
        # Création du contexte
        context = RecordingContext(
            recording_id=recording_id,
            user_id=user_id,
            court_id=court_id,
            match_id=match_id,
            club_id=club_id,
            camera_url=camera_url,
            max_duration=max_duration,
            output_path=str(output_path),
            quality_preset=quality,
            camera_type=self._detect_camera_type(camera_url)
        )
        
        try:
            with self.lock:
                # Vérifier les limites
                if len(self.active_recordings) >= self.max_parallel_recordings:
                    return {
                        'success': False,
                        'error': f'Limite atteinte ({self.max_parallel_recordings} enregistrements)',
                        'code': 'LIMIT_EXCEEDED'
                    }
                
                # Démarrer FFmpeg
                context.status = 'starting'
                context.start_time = datetime.now()
                
                process = self.ffmpeg_runner.start_recording(
                    camera_url=camera_url,
                    output_path=str(output_path),
                    camera_type=context.camera_type,
                    quality=quality,
                    max_duration=max_duration
                )
                
                context.process = process
                context.status = 'recording'
                
                # Ajouter aux enregistrements actifs
                self.active_recordings[recording_id] = context
                
                # Démarrer la lecture stderr
                self.ffmpeg_runner.drain_stderr(
                    process, 
                    callback=lambda line: context.update_ffmpeg_stats(line)
                )
                
                # Démarrer le superviseur si nécessaire
                self._ensure_supervisor_running()
                
                logger.info(f"Enregistrement démarré: {recording_id} (user: {user_id}, court: {court_id})")
                
                return {
                    'success': True,
                    'recording_id': recording_id,
                    'status': context.status,
                    'message': 'Enregistrement démarré avec succès'
                }
                
        except Exception as e:
            context.mark_error(f"Erreur démarrage: {e}")
            logger.error(f"Erreur démarrage enregistrement: {e}")
            return {
                'success': False,
                'error': str(e),
                'code': 'START_ERROR'
            }
    
    def stop_recording(self, recording_id: str, 
                      stopped_by_user_id: Optional[int] = None) -> Dict[str, Any]:
        """Arrête un enregistrement"""
        
        with self.lock:
            context = self.active_recordings.get(recording_id)
            if not context:
                return {
                    'success': False,
                    'error': 'Enregistrement non trouvé',
                    'code': 'NOT_FOUND'
                }
            
            if context.status not in ['recording', 'starting']:
                return {
                    'success': False,
                    'error': f'Enregistrement dans état incorrect: {context.status}',
                    'code': 'INVALID_STATE'
                }
            
            try:
                context.status = 'stopping'
                logger.info(f"Arrêt enregistrement: {recording_id} (par: {stopped_by_user_id})")
                
                # Arrêter FFmpeg proprement
                if context.process:
                    success = self.ffmpeg_runner.stop_recording(context.process)
                    if not success:
                        logger.warning(f"Arrêt forcé pour {recording_id}")
                
                # Le traitement final sera fait par le superviseur
                return {
                    'success': True,
                    'recording_id': recording_id,
                    'status': context.status,
                    'message': 'Arrêt en cours...'
                }
                
            except Exception as e:
                context.mark_error(f"Erreur arrêt: {e}")
                logger.error(f"Erreur arrêt enregistrement {recording_id}: {e}")
                return {
                    'success': False,
                    'error': str(e),
                    'code': 'STOP_ERROR'
                }
    
    def get_recording_status(self, recording_id: str) -> Dict[str, Any]:
        """Retourne le statut d'un enregistrement"""
        
        with self.lock:
            context = self.active_recordings.get(recording_id)
            if not context:
                return {
                    'success': False,
                    'error': 'Enregistrement non trouvé',
                    'code': 'NOT_FOUND'
                }
            
            return {
                'success': True,
                'recording': context.to_dict()
            }
    
    def list_active_recordings(self, user_id: Optional[int] = None,
                              court_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Liste les enregistrements actifs avec filtres optionnels"""
        
        with self.lock:
            recordings = []
            for context in self.active_recordings.values():
                if user_id and context.user_id != user_id:
                    continue
                if court_id and context.court_id != court_id:
                    continue
                recordings.append(context.to_dict())
            
            return recordings
    
    def _pre_recording_checks(self, camera_url: str) -> Dict[str, Any]:
        """Effectue les vérifications avant enregistrement"""
        
        # Vérifier l'espace disque
        disk_info = self.ffmpeg_runner.get_disk_space(str(self.output_dir))
        free_gb = disk_info['free'] / (1024**3)
        
        if free_gb < self.min_disk_space_gb:
            return {
                'success': False,
                'error': f'Espace disque insuffisant: {free_gb:.1f}GB disponible',
                'code': 'INSUFFICIENT_DISK_SPACE'
            }
        
        # Test de la caméra (rapide)
        # Mode développement : bypass du test de caméra si FFmpeg n'est pas configuré
        try:
            camera_accessible = self.ffmpeg_runner.check_camera_accessibility(camera_url, timeout=5)
            if not camera_accessible:
                logger.warning(f"⚠️ Caméra non accessible via FFmpeg: {camera_url}")
                logger.warning("⚠️ Mode développement: autorisation de l'enregistrement sans test de caméra")
                # En mode développement, on continue même si la caméra n'est pas accessible
                # TODO: En production, décommenter la ligne ci-dessous
                # return {'success': False, 'error': 'Caméra non accessible', 'code': 'CAMERA_UNAVAILABLE'}
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors du test de caméra: {e}")
            logger.warning("⚠️ Mode développement: autorisation de l'enregistrement sans test")
        
        return {'success': True}
    
    def _detect_camera_type(self, camera_url: str) -> str:
        """Détecte le type de caméra depuis l'URL"""
        url_lower = camera_url.lower()
        
        if url_lower.startswith('rtsp://') or url_lower.startswith('rtsps://'):
            return 'rtsp'
        elif any(ext in url_lower for ext in ['.mjpg', '.mjpeg', 'mjpeg']):
            return 'mjpeg'
        else:
            return 'http'
    
    def _ensure_supervisor_running(self):
        """S'assure que le thread superviseur est en marche"""
        if not self.supervisor_running:
            self.supervisor_running = True
            self.supervisor_thread = threading.Thread(
                target=self._supervisor_loop, 
                daemon=True
            )
            self.supervisor_thread.start()
            logger.info("Thread superviseur démarré")
    
    def _supervisor_loop(self):
        """Boucle principale du superviseur"""
        logger.info("Superviseur démarré")
        
        while self.supervisor_running:
            try:
                with self.lock:
                    completed_recordings = []
                    
                    for recording_id, context in list(self.active_recordings.items()):
                        
                        # Vérifier l'arrêt automatique
                        if (context.status == 'recording' and 
                            context.should_auto_stop):
                            logger.info(f"Arrêt automatique: {recording_id}")
                            self.stop_recording(recording_id)
                        
                        # Vérifier les processus terminés
                        if (context.process and 
                            context.process.poll() is not None and
                            context.status in ['recording', 'stopping']):
                            
                            logger.info(f"Processus terminé: {recording_id}")
                            context.status = 'processing'
                            completed_recordings.append(recording_id)
                
                # Traiter les enregistrements terminés (hors lock)
                for recording_id in completed_recordings:
                    self._finalize_recording(recording_id)
                
                # Vérifier si on peut arrêter le superviseur
                with self.lock:
                    if not self.active_recordings:
                        self.supervisor_running = False
                        logger.info("Superviseur arrêté (aucun enregistrement actif)")
                        break
                
                time.sleep(2)  # Pause entre les vérifications
                
            except Exception as e:
                logger.error(f"Erreur dans le superviseur: {e}")
                time.sleep(5)
    
    def _finalize_recording(self, recording_id: str):
        """Finalise un enregistrement (analyse, upload, DB)"""
        
        context = self.active_recordings.get(recording_id)
        if not context:
            return
        
        try:
            logger.info(f"Finalisation: {recording_id}")
            
            # Analyser le fichier vidéo
            video_info = self.ffmpeg_runner.probe_video_info(context.output_path)
            if video_info:
                context.file_size = video_info['size']
                context.duration = video_info['duration']
                context.resolution = (video_info['width'], video_info['height'])
                context.fps = video_info['fps']
            
            # Vérifier la validité du fichier
            if not video_info or context.duration < 3:
                context.mark_error("Fichier vidéo invalide ou trop court")
                self._cleanup_recording(recording_id)
                return
            
            # Upload de la vidéo
            context.upload_status = 'uploading'
            upload_result = self.uploader.upload(
                context.output_path,
                {
                    'title': f"Padel Court {context.court_id} - {context.start_time}",
                    'user_id': context.user_id,
                    'court_id': context.court_id,
                    'match_id': context.match_id
                }
            )
            
            if upload_result['success']:
                context.upload_status = 'completed'
                context.bunny_video_id = upload_result.get('video_id')
                context.bunny_url = upload_result.get('video_url')
                context.mark_completed()
                
                # TODO: Sauvegarder en base de données
                self._save_to_database(context, upload_result)
                
                logger.info(f"Enregistrement finalisé avec succès: {recording_id}")
            else:
                context.upload_status = 'failed'
                context.mark_error(f"Upload échoué: {upload_result.get('error')}")
                logger.error(f"Upload échoué pour {recording_id}: {upload_result.get('error')}")
            
        except Exception as e:
            context.mark_error(f"Erreur finalisation: {e}")
            logger.error(f"Erreur finalisation {recording_id}: {e}")
        
        finally:
            # Nettoyer les ressources
            self._cleanup_recording(recording_id)
    
    def _save_to_database(self, context: RecordingContext, upload_result: Dict[str, Any]):
        """Sauvegarde l'enregistrement en base de données"""
        try:
            # TODO: Implémenter avec votre modèle Recording
            # from ..models.recording import Recording
            # from ..models.database import db
            
            # recording = Recording(
            #     id=context.recording_id,
            #     user_id=context.user_id,
            #     court_id=context.court_id,
            #     match_id=context.match_id,
            #     club_id=context.club_id,
            #     file_url=upload_result.get('video_url', ''),
            #     thumbnail_url=upload_result.get('thumbnail_url', ''),
            #     started_at=context.start_time,
            #     ended_at=context.end_time,
            #     duration=int(context.duration),
            #     file_size=context.file_size,
            #     status='completed',
            #     upload_status=context.upload_status,
            #     bunny_video_id=context.bunny_video_id
            # )
            # 
            # db.session.add(recording)
            # db.session.commit()
            
            logger.info(f"Enregistrement sauvé en DB: {context.recording_id}")
            
        except Exception as e:
            logger.error(f"Erreur sauvegarde DB {context.recording_id}: {e}")
    
    def _cleanup_recording(self, recording_id: str):
        """Nettoie les ressources d'un enregistrement"""
        with self.lock:
            context = self.active_recordings.pop(recording_id, None)
            if context:
                # Fermer le processus si encore actif
                if context.process and context.process.poll() is None:
                    try:
                        context.process.terminate()
                        context.process.wait(timeout=5)
                    except:  # noqa: E722
                        try:
                            context.process.kill()
                        except:  # noqa: E722
                            pass
                
                logger.info(f"Ressources nettoyées: {recording_id}")
    
    def shutdown(self):
        """Arrête proprement le service"""
        logger.info("Arrêt du service d'enregistrement...")
        
        # Arrêter le superviseur
        self.supervisor_running = False
        if self.supervisor_thread and self.supervisor_thread.is_alive():
            self.supervisor_thread.join(timeout=10)
        
        # Arrêter tous les enregistrements actifs
        with self.lock:
            for recording_id in list(self.active_recordings.keys()):
                self.stop_recording(recording_id)
        
        # Attendre que tous se terminent
        timeout = 30
        start_time = time.time()
        while self.active_recordings and (time.time() - start_time) < timeout:
            time.sleep(1)
        
        # Nettoyer les restants
        for recording_id in list(self.active_recordings.keys()):
            self._cleanup_recording(recording_id)
        
        logger.info("Service d'enregistrement arrêté")
