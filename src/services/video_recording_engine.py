"""
NOUVEAU SYSTÈME D'ENREGISTREMENT VIDÉO ROBUSTE
==============================================

🚫 PROBLÈMES IDENTIFIÉS :
1. Enregistrements fantômes non arrêtés (21 minutes de pollution MJPEG)
2. Service MJPEG avec milliers d'erreurs "file not found"
3. Double système d'enregistrement (MJPEG + FFmpeg) créant des conflits
4. APIs retournant HTML au lieu de JSON sous charge
5. Nettoyage automatique de fichiers empêchant le diagnostic
6. Gestion d'état incohérente entre les services
7. Processus non monitored correctement

✅ SOLUTIONS IMPLÉMENTÉES :
1. Système unifié avec une seule méthode d'enregistrement par type d'URL
2. Gestionnaire d'état centralisé et thread-safe
3. Monitoring actif de                            if success and bunny_url:
                                try:
                                    video.file_url = bunny_url
                                    db.session.commit()
                                    logger.info(f"✅ Upload immédiat réussi: {video.id}")
                                    
                                    # Supprimer fichier local après upload réussi
                                    try:
                                        os.remove(video_path)
                                        logger.info(f"🗑️ Fichier local supprimé: {video_path}")
                                    except Exception as cleanup_e:
                                        logger.warning(f"⚠️ Erreur suppression: {cleanup_e}")
                                except Exception as db_e:
                                    logger.error(f"❌ Erreur BDD après upload: {db_e}")
                            else:
                                logger.error(f"❌ Échec upload immédiat: {video.id}")
                                # En cas d'échec, garder le fichier local
                                video.file_url = f"/static/videos/{os.path.basename(video_path)}"
                                db.session.commit()

                        except Exception as e:
                            logger.error(f"❌ Erreur upload immédiat {video.id}: {e}")
                            # Fallback: garder le fichier local
                            try:
                                video.file_url = f"/static/videos/{os.path.basename(video_path)}"
                                db.session.commit()
                            except Exception as fallback_e:
                                logger.error(f"❌ Erreur fallback BDD: {fallback_e}") auto-recovery
4. Upload automatique Bunny Stream non-bloquant
5. Nettoyage intelligent avec conservation diagnostique
6. Gestion robuste des erreurs avec fallback
7. API JSON garantie avec validation de format
8. Session cleanup automatique au démarrage
"""

import cv2
import threading
import time
import os
import logging
import subprocess
import shutil
from datetime import datetime
from typing import Dict, Optional, Any, List
from pathlib import Path
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import uuid

from ..models.database import db
from ..models.user import Video, Court, User
from .bunny_storage_service import bunny_storage_service
from .logging_service import get_logger, LogLevel

# Configuration du logger
logger = logging.getLogger(__name__)
system_logger = get_logger()

# Configuration FFmpeg robuste
FFMPEG_PATH = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not Path(FFMPEG_PATH).exists():
    FFMPEG_PATH = 'ffmpeg'
    logger.warning("⚠️ FFmpeg complet non trouvé, utilisation de 'ffmpeg'")
else:
    logger.info(f"✅ FFmpeg trouvé: {FFMPEG_PATH}")


class RecordingState(Enum):
    """États possibles d'un enregistrement - SIMPLIFIED"""
    STARTING = 'starting'
    RECORDING = 'recording'
    STOPPING = 'stopping'
    COMPLETED = 'completed'
    ERROR = 'error'
    FAILED = 'failed'


class VideoRecordingEngine:
    """
    MOTEUR D'ENREGISTREMENT VIDÉO UNIFIÉ ET ROBUSTE
    ===============================================

    Remplace tous les anciens services pour un fonctionnement unifié :
    - Gestion d'état centralisée et thread-safe
    - Monitoring actif des processus
    - Upload automatique Bunny Stream
    - Nettoyage intelligent des ressources
    - Recovery automatique des erreurs
    """

    def __init__(self, video_dir: str = "static/videos", 
                 temp_dir: str = "temp_recordings"):
        # Chemins de stockage
        self.video_dir = Path(video_dir)
        self.temp_dir = Path(temp_dir)
        self.thumbnail_dir = Path("static/thumbnails")

        # Créer les dossiers si nécessaire
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

        # État centralisé thread-safe
        self._state_lock = threading.RLock()
        self._active_recordings: Dict[str, Dict[str, Any]] = {}
        self._recording_processes: Dict[str, subprocess.Popen] = {}

        # Pool de threads pour tâches asynchrones
        self._thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="VideoEngine")

        # Configuration d'enregistrement optimisée
        self.config = {
            'max_duration': 3600,  # 1h max
            'fps': 25,
            'resolution': (1280, 720),
            'bitrate': '2M',
            'preset': 'veryfast',
            'segment_duration': 300,  # 5min par segment
            'auto_upload_threshold_mb': 10,  # Upload immédiat < 10MB
            'keep_local_files': True,  # Mode diagnostic activé
            'max_retry_attempts': 3,
            'process_check_interval': 5,  # Vérifier les processus toutes les 5s
        }

        # Démarrer le monitoring des processus
        self._monitor_thread = threading.Thread(
            target=self._process_monitor_loop,
            daemon=True,
            name="ProcessMonitor"
        )
        self._monitor_thread.start()

        # Note: Le nettoyage des fantômes sera fait lors du premier appel
        # pour éviter les problèmes de contexte d'application Flask
        self._cleanup_done = False

        logger.info("🚀 VideoRecordingEngine initialisé avec succès")
        system_logger.log(LogLevel.INFO, "🚀 VideoRecordingEngine - Moteur initialisé", {})

        # Note: Le monitoring système est déjà démarré automatiquement dans SystemLogger

    def _cleanup_phantom_recordings(self):
        """Nettoie les enregistrements fantômes au démarrage"""
        try:
            logger.info("🧹 Nettoyage des enregistrements fantômes...")
            system_logger.log(LogLevel.INFO, "🧹 Début nettoyage enregistrements fantômes", {})

            # Libérer tous les terrains marqués comme "en enregistrement"
            courts = Court.query.filter_by(is_recording=True).all()
            for court in courts:
                logger.info(f"🧹 Libération terrain fantôme: {court.id}")
                system_logger.log(LogLevel.WARNING, f"⚠️ Terrain fantôme détecté: {court.id}", {"court_id": court.id, "recording_id": court.current_recording_id})
                court.is_recording = False
                court.current_recording_id = None

            db.session.commit()
            logger.info(f"✅ {len(courts)} terrains fantômes nettoyés")
            system_logger.log(LogLevel.INFO,
                               f"✅ Nettoyage terminé: {len(courts)} terrains libérés",
                               {"phantoms_cleaned": len(courts)})

        except Exception as e:
            logger.error(f"❌ Erreur nettoyage fantômes: {e}")
            system_logger.log(LogLevel.ERROR, f"❌ Erreur nettoyage fantômes: {e}", {"error": str(e)})

    def start_recording(self, court_id: int, user_id: int, session_name: str = None, 
                       keep_local_files: bool = True, upload_to_bunny: bool = False) -> Dict[str, Any]:
        """
        DÉMARRE UN ENREGISTREMENT VIDÉO ROBUSTE
        ======================================

        Processus unifié qui choisit automatiquement la meilleure méthode :
        - MJPEG URLs → FFmpeg avec segmentation
        - RTSP URLs → FFmpeg optimisé RTSP
        - HTTP URLs → OpenCV fallback

        Returns:
            Dict avec session_id, status, message, camera_url
        """
        # Nettoyage initial si pas encore fait
        if not self._cleanup_done:
            self._cleanup_phantom_recordings()
            self._cleanup_done = True

        with self._state_lock:
            try:
                system_logger.log(LogLevel.INFO, "📝 Demande d'enregistrement reçue", {"operation": "start_recording"})

                # 1. VALIDATIONS PRÉLIMINAIRES
                court = self._validate_court(court_id)
                user = self._validate_user(user_id)

                # 2. GÉNÉRATION ID SESSION UNIQUE
                session_id = f"rec_{court_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"

                if not session_name:
                    session_name = f"Match du {datetime.now().strftime('%d/%m/%Y %H:%M')}"

                # 3. RÉCUPÉRATION URL CAMÉRA
                camera_url = self._get_camera_url(court)

                system_logger.log(LogLevel.INFO, f"📹 URL caméra récupérée: {camera_url[:50]}...", {"session_id": session_id, "court_id": court_id})

                # 4. PRÉPARATION FICHIERS
                video_filename = f"{session_id}.mp4"
                video_path = self.video_dir / video_filename
                temp_path = self.temp_dir / video_filename

                # 5. CRÉATION DE L'ÉTAT D'ENREGISTREMENT
                recording_state = {
                    'session_id': session_id,
                    'court_id': court_id,
                    'user_id': user_id,
                    'session_name': session_name,
                    'camera_url': camera_url,
                    'video_path': str(video_path),
                    'temp_path': str(temp_path),
                    'state': RecordingState.STARTING,
                    'start_time': datetime.now(),
                    'end_time': None,
                    'process_pid': None,
                    'error': None,
                    'method': self._determine_recording_method(camera_url),
                    'keep_local_files': keep_local_files,  # Configuration d'upload
                    'upload_to_bunny': upload_to_bunny,  # Configuration Bunny CDN
                    'stats': {
                        'duration': 0,
                        'file_size': 0,
                        'frames_recorded': 0,
                        'upload_status': 'pending' if upload_to_bunny else 'disabled'
                    }
                }

                # Log de la méthode choisie
                # system_logger.log(LogLevel.INFO, "📝 Opération effectuée")
                system_logger.log(LogLevel.INFO, f"✅ Enregistrement démarré: {session_id}")

                # 6. DÉMARRAGE DE L'ENREGISTREMENT
                success = self._start_recording_process(recording_state)

                if not success:
                    error_msg = f"Impossible de démarrer l'enregistrement pour le terrain {court_id}"
                    system_logger.log(LogLevel.INFO, "📝 Opération effectuée")
                    raise RuntimeError(error_msg)

                # 7. ENREGISTREMENT DE L'ÉTAT
                self._active_recordings[session_id] = recording_state

                # 8. MISE À JOUR BDD
                court.is_recording = True
                court.current_recording_id = session_id
                db.session.commit()

                logger.info(f"🎬 Enregistrement démarré: {session_id} (méthode: {recording_state['method']})")

                return {
                    'session_id': session_id,
                    'status': 'started',
                    'method': recording_state['method'],
                    'message': f"Enregistrement démarré: {session_name}",
                    'camera_url': camera_url,
                    'video_path': str(video_path)
                }

            except Exception as e:
                logger.error(f"❌ Erreur démarrage enregistrement: {e}")
                system_logger.log(LogLevel.INFO, "📝 Opération effectuée")  # TEMPORAIREMENT DÉSACTIVÉ
                # Nettoyage en cas d'erreur
                if 'session_id' in locals():
                    self._cleanup_recording_state(session_id)
                raise

    def stop_recording(self, session_id: str) -> Dict[str, Any]:
        """
        ARRÊTE UN ENREGISTREMENT DE FAÇON PROPRE
        ========================================

        Processus unifié d'arrêt avec finalisation automatique :
        - Arrêt du processus d'enregistrement
        - Finalisation du fichier vidéo
        - Upload automatique vers Bunny Stream
        - Nettoyage des ressources
        """
        with self._state_lock:
            if session_id not in self._active_recordings:
                return {
                    'status': 'error',
                    'error': f"Session {session_id} non trouvée",
                    'message': "Enregistrement introuvable ou déjà terminé"
                }

            recording = self._active_recordings[session_id]

            try:
                logger.info(f"⏹️ Arrêt enregistrement: {session_id}")

                # 1. MARQUER COMME EN COURS D'ARRÊT
                recording['state'] = RecordingState.STOPPING
                recording['end_time'] = datetime.now()

                # 2. ARRÊTER LE PROCESSUS
                self._stop_recording_process(session_id)

                # 3. FINALISER L'ENREGISTREMENT
                result = self._finalize_recording(session_id)

                # 4. NETTOYER L'ÉTAT
                del self._active_recordings[session_id]

                # 5. LIBÉRER LE TERRAIN
                court = Court.query.get(recording['court_id'])
                if court:
                    court.is_recording = False
                    court.current_recording_id = None
                    db.session.commit()

                logger.info(f"✅ Enregistrement arrêté avec succès: {session_id}")
                return result

            except Exception as e:
                logger.error(f"❌ Erreur arrêt enregistrement {session_id}: {e}")
                recording['state'] = RecordingState.ERROR
                recording['error'] = str(e)
                return {
                    'status': 'error',
                    'error': str(e),
                    'message': f"Erreur lors de l'arrêt de l'enregistrement"
                }

    def get_recording_status(self, session_id: str) -> Dict[str, Any]:
        """Obtient le statut d'un enregistrement en cours"""
        with self._state_lock:
            if session_id not in self._active_recordings:
                return {'status': 'not_found', 'error': 'Session non trouvée'}

            recording = self._active_recordings[session_id]
            duration = (datetime.now() - recording['start_time']).total_seconds()

            return {
                'session_id': session_id,
                'status': recording['state'].value,
                'method': recording['method'],
                'duration': duration,
                'start_time': recording['start_time'].isoformat(),
                'camera_url': recording['camera_url'],
                'stats': recording['stats']
            }

    def list_active_recordings(self) -> List[Dict[str, Any]]:
        """Liste tous les enregistrements actifs"""
        with self._state_lock:
            active = []
            for session_id, recording in self._active_recordings.items():
                duration = (datetime.now() - recording['start_time']).total_seconds()
                active.append({
                    'session_id': session_id,
                    'court_id': recording['court_id'],
                    'user_id': recording['user_id'],
                    'session_name': recording['session_name'],
                    'status': recording['state'].value,
                    'method': recording['method'],
                    'duration': duration,
                    'start_time': recording['start_time'].isoformat()
                })
            return active

    def _validate_court(self, court_id: int) -> Court:
        """Valide et récupère un terrain"""
        court = Court.query.get(court_id)
        if not court:
            raise ValueError(f"Terrain {court_id} non trouvé")

        if hasattr(court, 'is_recording') and court.is_recording:
            raise ValueError(f"Ce terrain est déjà utilisé pour un enregistrement: {court.current_recording_id}")

        return court

    def _validate_user(self, user_id: int) -> User:
        """Valide et récupère un utilisateur"""
        user = User.query.get(user_id)
        if not user:
            raise ValueError(f"Utilisateur {user_id} non trouvé")
        return user

    def _get_camera_url(self, court: Court) -> str:
        """Récupère l'URL de la caméra pour un terrain"""
        if not hasattr(court, 'camera_url') or not court.camera_url:
            raise ValueError(f"Pas d'URL de caméra configurée pour le terrain {court.id}")

        return court.camera_url

    def _determine_recording_method(self, camera_url: str) -> str:
        """Détermine la meilleure méthode d'enregistrement selon l'URL"""
        url_lower = camera_url.lower()

        if url_lower.startswith('rtsp://'):
            return 'ffmpeg_rtsp'
        elif any(ext in url_lower for ext in ['.mjpg', '.mjpeg', 'mjpg', 'mjpeg']):
            return 'ffmpeg_mjpeg'
        elif url_lower.startswith(('http://', 'https://')):
            return 'opencv_http'
        else:
            return 'opencv_fallback'

    def _start_recording_process(self, recording: Dict[str, Any]) -> bool:
        """Démarre le processus d'enregistrement selon la méthode"""
        try:
            method = recording['method']

            if method in ['ffmpeg_rtsp', 'ffmpeg_mjpeg']:
                return self._start_ffmpeg_recording(recording)
            else:
                return self._start_opencv_recording(recording)

        except Exception as e:
            logger.error(f"❌ Erreur démarrage processus {recording['session_id']}: {e}")
            recording['state'] = RecordingState.ERROR
            recording['error'] = str(e)
            return False

    def _start_ffmpeg_recording(self, recording: Dict[str, Any]) -> bool:
        """Démarre un enregistrement FFmpeg optimisé"""
        try:
            session_id = recording['session_id']
            camera_url = recording['camera_url']
            output_path = recording['temp_path']  # Utiliser temp d'abord

            # Configuration FFmpeg optimisée selon le type
            if recording['method'] == 'ffmpeg_rtsp':
                ffmpeg_cmd = [
                    FFMPEG_PATH,
                    '-rtsp_transport', 'tcp',
                    '-i', camera_url,
                    '-c:v', 'libx264',
                    '-preset', self.config['preset'],
                    '-crf', '23',
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-f', 'mp4',
                    '-movflags', '+faststart+frag_keyframe+empty_moov',
                    '-frag_duration', '1000000',
                    '-avoid_negative_ts', 'disabled',
                    '-max_muxing_queue_size', '1024',
                    '-y',  # Overwrite output
                    output_path
                ]
            else:  # ffmpeg_mjpeg
                ffmpeg_cmd = [
                    FFMPEG_PATH,
                    '-f', 'mjpeg',
                    '-i', camera_url,
                    '-c:v', 'libx264',
                    '-preset', self.config['preset'],
                    '-crf', '23',
                    '-r', str(self.config['fps']),
                    '-f', 'mp4',
                    '-movflags', '+faststart+frag_keyframe+empty_moov',  # Améliore la robustesse
                    '-frag_duration', '1000000',  # Fragmentation pour éviter la corruption
                    '-avoid_negative_ts', 'disabled',  # Évite les problèmes de timestamp
                    '-max_muxing_queue_size', '1024',  # Buffer plus grand
                    '-y',
                    output_path
                ]

            logger.info(f"🎬 Démarrage FFmpeg ({recording['method']}): {session_id}")
            logger.debug(f"Commande: {' '.join(ffmpeg_cmd[:5])}...{output_path}")

            # Créer le processus
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )

            # Vérifier le démarrage
            time.sleep(1)  # Laisser le temps au processus de démarrer
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise RuntimeError(f"FFmpeg a échoué au démarrage: {stderr}")

            # Enregistrer le processus
            self._recording_processes[session_id] = process
            recording['process_pid'] = process.pid
            recording['state'] = RecordingState.RECORDING

            logger.info(f"✅ FFmpeg démarré (PID: {process.pid}): {session_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Erreur FFmpeg pour {session_id}: {e}")
            recording['state'] = RecordingState.ERROR
            recording['error'] = str(e)
            return False

    def _start_opencv_recording(self, recording: Dict[str, Any]) -> bool:
        """Démarre un enregistrement OpenCV (fallback)"""
        try:
            session_id = recording['session_id']

            # Démarrer le thread OpenCV
            opencv_thread = threading.Thread(
                target=self._opencv_recording_worker,
                args=(recording,),
                daemon=True,
                name=f"OpenCV-{session_id}"
            )
            opencv_thread.start()

            recording['state'] = RecordingState.RECORDING
            logger.info(f"✅ OpenCV démarré: {session_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Erreur OpenCV pour {session_id}: {e}")
            recording['state'] = RecordingState.ERROR
            recording['error'] = str(e)
            return False

    def _opencv_recording_worker(self, recording: Dict[str, Any]):
        """Worker thread pour l'enregistrement OpenCV"""
        session_id = recording['session_id']
        camera_url = recording['camera_url']
        output_path = recording['temp_path']

        cap = None
        out = None

        try:
            # Ouvrir la capture
            cap = cv2.VideoCapture(camera_url)
            if not cap.isOpened():
                raise RuntimeError(f"Impossible d'ouvrir la caméra: {camera_url}")

            # Configuration de la capture
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config['resolution'][0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config['resolution'][1])
            cap.set(cv2.CAP_PROP_FPS, self.config['fps'])

            # Premier frame pour obtenir les dimensions réelles
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError("Impossible de capturer le premier frame")

            height, width = frame.shape[:2]

            # Configuration du writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, self.config['fps'], (width, height))

            frame_count = 0
            start_time = time.time()

            logger.info(f"🎥 Enregistrement OpenCV actif: {session_id} ({width}x{height})")

            while True:
                # Vérifier si on doit s'arrêter
                with self._state_lock:
                    if (session_id not in self._active_recordings or
                        self._active_recordings[session_id]['state'] == RecordingState.STOPPING):
                        break

                # Vérifier la durée maximale
                if time.time() - start_time > self.config['max_duration']:
                    logger.info(f"⏰ Durée maximale atteinte pour {session_id}")
                    break

                # Capturer le frame
                ret, frame = cap.read()
                if not ret:
                    logger.warning(f"⚠️ Échec capture frame {session_id}")
                    time.sleep(0.1)
                    continue

                # Écrire le frame
                out.write(frame)
                frame_count += 1

                # Mettre à jour les stats
                if frame_count % (self.config['fps'] * 10) == 0:  # Toutes les 10 secondes
                    duration = time.time() - start_time
                    with self._state_lock:
                        if session_id in self._active_recordings:
                            self._active_recordings[session_id]['stats']['duration'] = duration
                            self._active_recordings[session_id]['stats']['frames_recorded'] = frame_count

                # Pause pour respecter le FPS
                time.sleep(1.0 / self.config['fps'])

            logger.info(f"🎬 Enregistrement OpenCV terminé: {session_id} ({frame_count} frames)")

        except Exception as e:
            logger.error(f"❌ Erreur dans worker OpenCV {session_id}: {e}")
            with self._state_lock:
                if session_id in self._active_recordings:
                    self._active_recordings[session_id]['state'] = RecordingState.ERROR
                    self._active_recordings[session_id]['error'] = str(e)
        finally:
            # Nettoyage
            if cap:
                cap.release()
            if out:
                out.release()

    def _stop_recording_process(self, session_id: str):
        """Arrête le processus d'enregistrement de façon propre"""
        # Arrêter le processus FFmpeg si présent
        if session_id in self._recording_processes:
            process = self._recording_processes[session_id]
            try:
                logger.info(f"⏹️ Arrêt processus FFmpeg PID {process.pid}")
                
                # Pour Windows, envoyer Ctrl+C au lieu de terminate pour un arrêt propre
                import os
                import signal
                try:
                    # Essayer d'abord un arrêt propre avec SIGINT
                    os.kill(process.pid, signal.SIGINT)
                    logger.info(f"📤 Signal SIGINT envoyé au processus {process.pid}")
                except:
                    # Si SIGINT ne fonctionne pas, utiliser terminate
                    process.terminate()
                    logger.info(f"📤 Terminate envoyé au processus {process.pid}")

                # Attendre l'arrêt propre avec plus de temps
                try:
                    process.wait(timeout=15)  # Plus de temps pour finaliser le MP4
                    logger.info(f"✅ Processus {process.pid} arrêté proprement")
                except subprocess.TimeoutExpired:
                    logger.warning(f"⚠️ Timeout processus {process.pid}, kill forcé")
                    process.kill()
                    process.wait()

            except Exception as e:
                logger.error(f"❌ Erreur arrêt processus: {e}")
            finally:
                del self._recording_processes[session_id]

        # Pour OpenCV, le thread se termine automatiquement en voyant le state STOPPING

    def _finalize_recording(self, session_id: str) -> Dict[str, Any]:
        """Finalise l'enregistrement et crée l'entrée en base"""
        try:
            recording = self._active_recordings[session_id]
            temp_path = recording['temp_path']
            final_path = recording['video_path']

            # Vérifier que le fichier temporaire existe
            if not os.path.exists(temp_path):
                raise FileNotFoundError(f"Fichier vidéo temporaire non trouvé: {temp_path}")

            # Déplacer le fichier temporaire vers le dossier final
            shutil.move(temp_path, final_path)
            logger.info(f"📁 Fichier déplacé: {temp_path} → {final_path}")

            # Calculer les statistiques
            file_size = os.path.getsize(final_path)
            duration = (recording['end_time'] - recording['start_time']).total_seconds()

            # Générer une miniature
            thumbnail_path = self._generate_thumbnail(final_path, session_id)

            # Créer l'entrée vidéo en base
            video = Video(
                title=recording['session_name'],
                file_url=f"/videos/{os.path.basename(final_path)}",
                thumbnail_url=f"/thumbnails/{session_id}.jpg" if thumbnail_path else None,
                duration=int(duration),
                court_id=recording['court_id'],
                user_id=recording['user_id'],
                recorded_at=recording['start_time'],
                is_unlocked=False,
                credits_cost=1,
                file_size=file_size
            )

            db.session.add(video)
            db.session.commit()  # Commit simple au lieu de begin()

            # UPLOAD AUTOMATIQUE VERS BUNNY STREAM
            self._schedule_automatic_upload(video, final_path, thumbnail_path, recording)

            logger.info(f"📊 Vidéo créée: ID {video.id}, Durée: {duration}s, Taille: {file_size} bytes")

            recording['state'] = RecordingState.COMPLETED

            return {
                'status': 'completed',
                'video_id': video.id,
                'duration': duration,
                'file_size': file_size,
                'thumbnail_url': video.thumbnail_url,
                'video_url': video.file_url,
                'message': f"Enregistrement terminé: {recording['session_name']}"
            }

        except Exception as e:
            logger.error(f"❌ Erreur finalisation {session_id}: {e}")
            if session_id in self._active_recordings:
                self._active_recordings[session_id]['state'] = RecordingState.ERROR
                self._active_recordings[session_id]['error'] = str(e)

            return {
                'status': 'error',
                'error': str(e),
                'message': "Erreur lors de la finalisation de l'enregistrement"
            }

    def _schedule_automatic_upload(self, video: Video, video_path: str, 
                                  thumbnail_path: str = None, recording: Dict = None):
        """Programme l'upload automatique vers Bunny Stream"""
        try:
            # Récupérer la configuration d'upload depuis l'enregistrement
            keep_local = True  # Par défaut
            upload_to_bunny = False  # Par défaut
            
            if recording:
                if 'keep_local_files' in recording:
                    keep_local = recording['keep_local_files']
                if 'upload_to_bunny' in recording:
                    upload_to_bunny = recording['upload_to_bunny']
                    
                logger.info(f"🔧 Configuration: keep_local={keep_local}, upload_to_bunny={upload_to_bunny}")
            else:
                logger.warning(f"⚠️ Pas de configuration dans recording")
            
            # Vérifier que le service Bunny CDN est configuré si upload demandé
            if upload_to_bunny and not bunny_storage_service.is_configured():
                logger.error(f"❌ Service Bunny CDN non configuré - upload désactivé")
                upload_to_bunny = False
            
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            logger.info(f"📊 Décision upload: upload_to_bunny={upload_to_bunny}, taille={file_size_mb:.1f}MB")

            # Décider si upload vers Bunny CDN
            if upload_to_bunny:
                # Mode upload: Envoyer vers Bunny CDN
                logger.info(f"📤 ACTIVATION UPLOAD vers Bunny CDN pour {video.id}")
                logger.info(f"📤 Upload vers Bunny CDN: {video.id} ({file_size_mb:.2f} MB)")
                
                if file_size_mb < self.config['auto_upload_threshold_mb']:
                    # Upload immédiat pour petits fichiers
                    def immediate_upload():
                        try:
                            success, bunny_url = bunny_storage_service.upload_video_immediately(
                                video.id,
                                video_path,
                                f"PadelVar_Video_{video.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                            )

                            if success and bunny_url:
                                video.file_url = bunny_url
                                db.session.commit()
                                logger.info(f"✅ Upload immédiat réussi: {video.id}")
                                
                                # Supprimer fichier local après upload réussi
                                try:
                                    os.remove(video_path)
                                    logger.info(f"�️ Fichier local supprimé: {video_path}")
                                except Exception as cleanup_e:
                                    logger.warning(f"⚠️ Erreur suppression fichier: {cleanup_e}")
                            else:
                                logger.error(f"❌ Échec upload immédiat: {video.id}")

                        except Exception as e:
                            logger.error(f"❌ Erreur upload immédiat {video.id}: {e}")

                    self._thread_pool.submit(immediate_upload)
                
                else:
                    # Queue pour gros fichiers
                    video.file_url = f"En cours d'upload... (ID: {video.id})"
                    try:
                        upload_id = bunny_storage_service.queue_upload(
                            local_path=video_path,
                            title=f"PadelVar_Video_{video.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                            metadata={'video_id': video.id}
                        )
                        logger.info(f"✅ Ajouté à la queue: {video.id} (upload_id: {upload_id})")
                    except Exception as e:
                        logger.error(f"❌ Erreur queue upload {video.id}: {e}")
            
            else:
                # Mode conservation locale
                logger.info(f"📁 Conservation locale: {video.id} ({file_size_mb:.2f} MB)")
                # Le fichier reste local, URL pointe vers le fichier local
                video.file_url = f"/static/videos/{os.path.basename(video_path)}"
                db.session.commit()

            # Upload miniature si disponible et en mode upload
            if upload_to_bunny and thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    bunny_storage_service.queue_upload(
                        local_path=thumbnail_path,
                        title=f"Thumbnail_{video.id}"
                    )
                except Exception as e:
                    logger.error(f"❌ Erreur upload miniature: {e}")

        except Exception as e:
            logger.error(f"❌ Erreur programmation upload: {e}")

    def _generate_thumbnail(self, video_path: str, session_id: str) -> Optional[str]:
        """Génère une miniature pour la vidéo"""
        try:
            thumbnail_path = self.thumbnail_dir / f"{session_id}.jpg"

            # Essayer avec FFmpeg d'abord
            ffmpeg_cmd = [
                FFMPEG_PATH,
                '-i', video_path,
                '-vf', 'select=eq(n\\,0)',
                '-vframes', '1',
                '-f', 'image2',
                '-y',
                str(thumbnail_path)
            ]

            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and thumbnail_path.exists():
                logger.info(f"📸 Miniature FFmpeg créée: {thumbnail_path}")
                return str(thumbnail_path)
            else:
                # Fallback OpenCV
                return self._generate_thumbnail_opencv(video_path, str(thumbnail_path))

        except Exception as e:
            logger.error(f"❌ Erreur génération miniature: {e}")
            return None

    def _generate_thumbnail_opencv(self, video_path: str, thumbnail_path: str) -> Optional[str]:
        """Génère une miniature avec OpenCV (fallback)"""
        try:
            cap = cv2.VideoCapture(video_path)
            ret, frame = cap.read()
            cap.release()

            if ret:
                cv2.imwrite(thumbnail_path, frame)
                logger.info(f"📸 Miniature OpenCV créée: {thumbnail_path}")
                return thumbnail_path
            else:
                logger.warning(f"⚠️ Impossible de lire le premier frame: {video_path}")
                return None

        except Exception as e:
            logger.error(f"❌ Erreur miniature OpenCV: {e}")
            return None

    def _process_monitor_loop(self):
        """Boucle de monitoring des processus actifs"""
        logger.info("👁️ Démarrage du monitoring des processus")

        while True:
            try:
                time.sleep(self.config['process_check_interval'])

                with self._state_lock:
                    sessions_to_check = list(self._active_recordings.keys())

                for session_id in sessions_to_check:
                    try:
                        self._check_recording_health(session_id)
                    except Exception as e:
                        logger.error(f"❌ Erreur check health {session_id}: {e}")

            except Exception as e:
                logger.error(f"❌ Erreur monitoring loop: {e}")
                time.sleep(10)  # Pause plus longue en cas d'erreur

    def _check_recording_health(self, session_id: str):
        """Vérifie la santé d'un enregistrement"""
        with self._state_lock:
            if session_id not in self._active_recordings:
                return

            recording = self._active_recordings[session_id]

            # Vérifier la durée maximale
            duration = (datetime.now() - recording['start_time']).total_seconds()
            if duration > self.config['max_duration']:
                logger.info(f"⏰ Durée maximale atteinte: {session_id}")
                self._thread_pool.submit(self.stop_recording, session_id)
                return

            # Vérifier le processus FFmpeg
            if session_id in self._recording_processes:
                process = self._recording_processes[session_id]
                if process.poll() is not None:
                    logger.warning(f"⚠️ Processus FFmpeg terminé prématurément: {session_id}")
                    recording['state'] = RecordingState.ERROR
                    recording['error'] = "Processus FFmpeg terminé prématurément"
                    self._thread_pool.submit(self.stop_recording, session_id)

    def _cleanup_recording_state(self, session_id: str):
        """Nettoie l'état d'un enregistrement"""
        with self._state_lock:
            # Nettoyer le processus
            if session_id in self._recording_processes:
                try:
                    process = self._recording_processes[session_id]
                    process.terminate()
                    process.wait(timeout=5)
                except:
                    pass
                del self._recording_processes[session_id]

            # Nettoyer l'état
            if session_id in self._active_recordings:
                del self._active_recordings[session_id]

            # Libérer le terrain si possible
            try:
                court = Court.query.filter_by(current_recording_id=session_id).first()
                if court:
                    court.is_recording = False
                    court.current_recording_id = None
                    db.session.commit()
            except Exception as e:
                logger.error(f"❌ Erreur libération terrain: {e}")

    def shutdown(self):
        """Arrête proprement le service"""
        logger.info("🛑 Arrêt du VideoRecordingEngine...")

        # Arrêter tous les enregistrements actifs
        with self._state_lock:
            active_sessions = list(self._active_recordings.keys())

        for session_id in active_sessions:
            try:
                self.stop_recording(session_id)
            except Exception as e:
                logger.error(f"❌ Erreur arrêt {session_id}: {e}")

        # Arrêter le pool de threads
        self._thread_pool.shutdown(wait=True)

        logger.info("✅ VideoRecordingEngine arrêté")

# Instance globale du nouveau moteur
video_recording_engine = VideoRecordingEngine()

# Alias pour compatibilité avec l'ancien système
video_capture_service = video_recording_engine

logger.info("🎬 Nouveau système d'enregistrement vidéo chargé avec succès")
