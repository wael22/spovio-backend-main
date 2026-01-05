"""
Recording Manager - Production Ready
Gestion robuste des enregistrements FFmpeg avec segmentation
Refactorisé selon le style camera-recorder qui FONCTIONNE
"""
import os
import time
import json
import logging
import subprocess
import threading
import signal
import platform
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass

# Import configuration
from ..recording_config.recording_config import config

# Configuration du logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class RecordingInfo:
    """Information sur un enregistrement en cours"""
    recording_id: str
    match_id: str
    terrain_id: int
    club_id: int
    user_id: int
    
    proxy_url: str
    duration_seconds: int
    
    tmp_dir: Path
    final_dir: Path
    
    process: subprocess.Popen
    pid: int
    
    start_time: datetime
    expected_end_time: datetime
    
    status: str  # 'recording', 'stopping', 'stopped', 'failed'
    
    segments_written: List[Path]
    final_video_path: Optional[Path]
    
    errors: List[str]
    
    def to_dict(self) -> dict:
        """Convertir en dictionnaire (pour JSON)"""
        # Manually build dict to avoid serializing non-picklable objects
        return {
            'recording_id': self.recording_id,
            'match_id': self.match_id,
            'terrain_id': self.terrain_id,
            'club_id': self.club_id,
            'user_id': self.user_id,
            'proxy_url': self.proxy_url,
            'duration_seconds': self.duration_seconds,
            'tmp_dir': str(self.tmp_dir),
            'final_dir': str(self.final_dir),
            'pid': self.pid,
            'start_time': self.start_time.isoformat(),
            'expected_end_time': self.expected_end_time.isoformat(),
            'status': self.status,
            'segments_written': [str(p) for p in self.segments_written],
            'final_video_path': (
                str(self.final_video_path)
                if self.final_video_path else None
            )
        }

class RecordingManager:
    """
    Gestionnaire d'enregistrement vidéo utilisant FFmpeg directement.
    Version simplifiée et robuste.
    """
    
    def __init__(self):
        self.recordings: Dict[str, RecordingInfo] = {}
        self.monitor_thread = None
        self.lock = threading.Lock()
        
        logger.info("🎬 RecordingManager initialisé")
    
    def _log_ffmpeg_output(self, process: subprocess.Popen, recording_id: str):
        """Lire et logger la sortie stderr de FFmpeg en temps réel"""
        try:
            for line in iter(process.stderr.readline, ''):
                if not line:
                    break
                line = line.strip()
                if line:
                    # Logger seulement les lignes importantes
                    if any(x in line.lower() for x in ['error', 'failed', 'invalid', 'cannot']):
                        logger.error(f"FFmpeg [{recording_id}]: {line}")
                    elif 'frame=' in line.lower():
                        logger.debug(f"FFmpeg [{recording_id}]: {line}")
                    else:
                        logger.info(f"FFmpeg [{recording_id}]: {line}")
        except Exception as e:
            logger.error(f"❌ Erreur lecture stderr FFmpeg: {e}")
        finally:
            if process.stderr:
                process.stderr.close()
    
    def start_recording(
        self,
        recording_id: str,
        match_id: str,
        terrain_id: int,
        club_id: int,
        user_id: int,
        camera_url: str,
        duration_seconds: int
    ) -> Tuple[bool, str, Optional[dict]]:
        """
        Démarrer un enregistrement avec segmentation
        
        Args:
            recording_id: ID unique de l'enregistrement
            match_id: ID du match
            terrain_id: ID du terrain
            club_id: ID du club
            user_id: ID de l'utilisateur
            camera_url: URL de la caméra IP
            duration_seconds: Durée en secondes
        
        Returns:
            (success: bool, message: str, recording_info: dict ou None)
        """
        
        # 1. Vérifications préalables
        
        # Vérifier espace disque
        if not config.has_sufficient_disk_space():
            available_gb = config.get_available_disk_space() / (
                1024**3
            )
            msg = (
                f"Espace disque insuffisant: {available_gb:.1f} GB "
                f"disponibles"
            )
            logger.error(f"❌ {msg}")
            return False, msg, None
        
        # Vérifier limite d'enregistrements concurrent
        with self.lock:
            active_count = sum(
                1 for r in self.recordings.values()
                if r.status == 'recording'
            )
            
            if active_count >= config.MAX_CONCURRENT_RECORDINGS:
                msg = (
                    f"Limite d'enregistrements simultanés atteinte: "
                    f"{active_count}/{config.MAX_CONCURRENT_RECORDINGS}"
                )
                logger.error(f"❌ {msg}")
                return False, msg, None
        
        # Vérifier si enregistrement existe déjà
        with self.lock:
            if recording_id in self.recordings:
                msg = f"Enregistrement {recording_id} existe déjà"
                logger.error(f"❌ {msg}")
                return False, msg, None
        
        # 2. Utiliser le relay local pour flux stable
        # Le serveur multi_relay_server.py doit être en cours d'exécution
        # Il sert les streams sur http://127.0.0.1:8000/video/<terrain_id>
        
        relay_url = f"http://127.0.0.1:8000/video/{terrain_id}"
        
        logger.info(
            f"🎥 Utilisation du relay MJPEG pour terrain {terrain_id}"
        )
        logger.info(f"📡 Relay URL: {relay_url}")
        logger.info(f"📹 Source caméra: {camera_url}")
        
        # Vérifier (optionnel) si le relay est accessible
        try:
            import requests
            response = requests.get(
                f"http://127.0.0.1:8000/api/stats/{terrain_id}",
                timeout=2
            )
            if response.ok:
                stats = response.json()
                logger.info(
                    f"✅ Relay actif - "
                    f"Connecté: {stats.get('connected')}, "
                    f"Frames: {stats.get('frames_received', 0)}"
                )
            else:
                logger.warning(
                    f"⚠️ Relay non accessible - "
                    f"Assurez-vous que multi_relay_server.py est démarré"
                )
        except Exception as e:
            logger.warning(
                f"⚠️ Impossible de vérifier relay status: {e} - "
                f"FFmpeg va quand même essayer de se connecter"
            )
        
        # 3. Préparer les dossiers
        
        tmp_dir = config.get_match_tmp_dir(club_id, match_id)
        final_dir = config.get_match_final_dir(club_id, match_id)
        
        tmp_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"📁 Dossier tmp: {tmp_dir}")
        logger.info(f"📁 Dossier final: {final_dir}")
        
        # 4. Construire la commande FFmpeg avec relay URL
        stream_url = relay_url  # Utiliser relay au lieu de camera directe
        
        cmd, output_file = self._build_direct_command(
            stream_url,
            tmp_dir,
            recording_id,
            duration_seconds
        )
        
        logger.info(f"🎬 Commande FFmpeg:")
        logger.info(f"   {' '.join(cmd)}")
        
        # 5. Lancer FFmpeg
        
        try:
            # CREATE_NEW_PROCESS_GROUP pour Windows (style camera-recorder)
            if platform.system() == "Windows":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                creationflags = 0
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=creationflags
            )
            
            logger.info(
                f"✅ Processus FFmpeg démarré: PID={process.pid}"
            )
            
            # Démarrer thread pour logger stderr
            stderr_thread = threading.Thread(
                target=self._log_ffmpeg_output,
                args=(process, recording_id),
                daemon=True
            )
            stderr_thread.start()
            
        except Exception as e:
            msg = f"Erreur lancement FFmpeg: {e}"
            logger.error(f"❌ {msg}")
            self.proxy_manager.stop_proxy(terrain_id)
            return False, msg, None
        
        # 6. Créer RecordingInfo
        
        start_time = datetime.now()
        expected_end_time = start_time + timedelta(
            seconds=duration_seconds
        )
        
        recording_info = RecordingInfo(
            recording_id=recording_id,
            match_id=match_id,
            terrain_id=terrain_id,
            club_id=club_id,
            user_id=user_id,
            proxy_url=relay_url,
            duration_seconds=duration_seconds,
            tmp_dir=tmp_dir,
            final_dir=final_dir,
            process=process,
            pid=process.pid,
            start_time=start_time,
            expected_end_time=expected_end_time,
            status='recording',
            segments_written=[],
            final_video_path=None,
            errors=[]
        )
        
        # 7. Enregistrer
        
        with self.lock:
            self.recordings[recording_id] = recording_info
        
        # 8. Démarrer monitoring si pas déjà fait
        
        if not self.monitoring:
            self._start_monitoring()
        
        # 9. Retourner les infos
        
        logger.info(
            f"✅ Enregistrement démarré: {recording_id} "
            f"(terrain {terrain_id}, durée {duration_seconds}s)"
        )
        
        return True, "Enregistrement démarré", recording_info.to_dict()
    
    def _build_direct_command(
        self,
        proxy_url: str,
        tmp_dir: Path,
        recording_id: str,
        duration_seconds: int
    ) -> Tuple[List[str], str]:
        """
        Construire commande FFmpeg capture directe - STYLE CAMERA-RECORDER
        Simple et fiable, sans options complexes
        
        Returns:
            (command: List[str], output_file: str)
        """
        # Fichier de sortie unique dans tmp/
        output_file = str(tmp_dir / f"{recording_id}.mp4")
        
        # Commande SIMPLE comme camera-recorder (qui marche!)
        cmd = [
            str(config.FFMPEG_PATH),
            "-hide_banner",
            "-loglevel", "info"
        ]
        
        # Ajouter rtsp_transport seulement pour RTSP
        if proxy_url.startswith("rtsp"):
            cmd.extend(["-rtsp_transport", "tcp"])
            
        cmd.extend([
            "-i", proxy_url,
            "-t", str(duration_seconds),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-an",  # Pas d'audio (caméras IP)
            "-y",
            output_file
        ])
        
        return cmd, output_file
    
    def _build_single_command(
        self,
        proxy_url: str,
        tmp_dir: Path,
        recording_id: str,
        duration_seconds: int
    ) -> Tuple[List[str], str]:
        """
        Construire commande FFmpeg fichier unique (version complète)
        
        Returns:
            (command: List[str], output_file: str)
        """
        # Utiliser .mp4 directement
        output_file = str(tmp_dir / f"{recording_id}.mp4")
        
        cmd = [
            str(config.FFMPEG_PATH),
            "-hide_banner",
            "-loglevel", "info",
            
            # Input
            "-rtsp_transport", "tcp",
            "-i", proxy_url,
            
            # Durée
            "-t", str(duration_seconds),
            
            # Filtres
            "-vf", (
                f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
                f"fps={config.VIDEO_FPS}"
            ),
            
            # Codec
            "-c:v", config.VIDEO_CODEC,
            "-preset", config.VIDEO_PRESET,
            "-crf", str(config.VIDEO_CRF),
            
            # Pas d'audio
            "-an",
            
            # MP4 options
            "-movflags", "+faststart",
            
            # Options supplémentaires
            *config.FFMPEG_EXTRA_OPTIONS,
            
            # Output
            "-y",  # Écraser
            output_file
        ]
        
        return cmd, output_file
    
    def stop_recording(
        self,
        recording_id: str,
        reason: str = "manual"
    ) -> Tuple[bool, str]:
        """
        Arrêter un enregistrement proprement
        
        Args:
            recording_id: ID de l'enregistrement
            reason: Raison (manual, timeout, error)
        
        Returns:
            (success: bool, message: str)
        """
        with self.lock:
            if recording_id not in self.recordings:
                msg = f"Enregistrement {recording_id} introuvable"
                logger.warning(f"⚠️ {msg}")
                return False, msg
            
            recording = self.recordings[recording_id]
        
        logger.info(
            f"🛑 Arrêt enregistrement {recording_id} "
            f"(raison: {reason})"
        )
        
        # Marquer comme en cours d'arrêt
        recording.status = 'stopping'
        
        # 1. Envoyer signal d'arrêt gracieux à FFmpeg
        logger.info("📤 Arrêt FFmpeg...")
        success = self._stop_ffmpeg_process(recording)
        
        if not success:
            recording.errors.append(
                "Arrêt forcé du processus FFmpeg"
            )
        
        # 2. Finaliser l'enregistrement (attendre fichier)
        logger.info("🔄 Finalisation...")
        finalize_success = self._finalize_recording(recording)
        
        # 3. Arrêter le proxy APRÈS (comme camera-recorder)
        logger.info("🛑 Arrêt proxy...")
        self.proxy_manager.stop_proxy(recording.terrain_id)
        
        if finalize_success:
            recording.status = 'stopped'
            msg = "Enregistrement arrêté et finalisé"
        else:
            recording.status = 'failed'
            msg = "Enregistrement arrêté mais erreurs de finalisation"
        
        logger.info(f"✅ {msg}: {recording_id}")
        
        return finalize_success, msg
    
    def _stop_ffmpeg_process(
        self,
        recording: RecordingInfo
    ) -> bool:
        """
        Arrêter le processus FFmpeg - STYLE CAMERA-RECORDER
        Utilise CTRL_BREAK_EVENT sur Windows (signal 1)
        
        Returns:
            success: bool
        """
        process = recording.process
        
        if process.poll() is not None:
            logger.info(
                f"ℹ️ Processus FFmpeg déjà terminé "
                f"(code: {process.returncode})"
            )
            return True
        
        logger.info(f"� Arrêt FFmpeg (PID: {process.pid})")
        
        try:
            # Envoyer CTRL_BREAK_EVENT sur Windows (comme camera-recorder)
            if platform.system() == "Windows":
                try:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    # CTRL_BREAK_EVENT = signal 1
                    kernel32.GenerateConsoleCtrlEvent(1, process.pid)
                    logger.info(
                        f"📤 Sent CTRL_BREAK_EVENT to PID {process.pid}"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to send CTRL_BREAK_EVENT: {e}, "
                        f"using terminate()"
                    )
                    process.terminate()
            else:
                # Unix: utiliser SIGINT
                import signal
                process.send_signal(signal.SIGINT)
            
            # Attendre 10s (comme camera-recorder, pas 5s)
            try:
                returncode = process.wait(timeout=10)
                logger.info(
                    f"✅ FFmpeg terminé proprement (code: {returncode})"
                )
                return True
            except subprocess.TimeoutExpired:
                logger.warning(
                    "⏱️ Timeout 10s, FFmpeg ne répond pas, killing..."
                )
                process.kill()
                process.wait(timeout=5)
                logger.warning("⚠️ FFmpeg tué (SIGKILL)")
                return False
        
        except Exception as e:
            logger.error(
                f"❌ Erreur arrêt processus FFmpeg: {e}"
            )
            recording.errors.append(f"Erreur arrêt FFmpeg: {e}")
            try:
                process.kill()
            except Exception:
                pass
            return False
    
    def _finalize_recording(
        self,
        recording: RecordingInfo
    ) -> bool:
        """
        Finaliser l'enregistrement (fichier unique):
        - Trouver le fichier MP4 dans tmp/
        - Le déplacer vers final/
        - Nettoyer
        
        Returns:
            success: bool
        """
        logger.info(
            f"🔄 Finalisation enregistrement {recording.recording_id}"
        )
        
        try:
            # 1. Trouver le fichier MP4 de sortie dans tmp/
            tmp_file = recording.tmp_dir / f"{recording.recording_id}.mp4"
            
            # Attendre que FFmpeg finalise le fichier (max 10s)
            max_wait = 10
            wait_interval = 0.5
            elapsed = 0
            
            while not tmp_file.exists() and elapsed < max_wait:
                logger.info(f"⏳ Attente fichier MP4... ({elapsed:.1f}s)")
                time.sleep(wait_interval)
                elapsed += wait_interval
            
            if not tmp_file.exists():
                msg = (
                    f"Fichier introuvable après {max_wait}s: {tmp_file}. "
                    "Vérifiez que FFmpeg a bien démarré et que le proxy RTSP fonctionne."
                )
                logger.error(f"❌ {msg}")
                recording.errors.append(msg)
                return False
            
            # 2. Vérifier la taille
            file_size = tmp_file.stat().st_size
            file_size_mb = file_size / (1024**2)
            
            logger.info(f"📂 Fichier trouvé: {file_size_mb:.1f} MB")
            
            if file_size < config.MIN_SEGMENT_SIZE_BYTES:
                msg = (
                    f"Fichier trop petit: {file_size_mb:.2f} MB "
                    f"(min: {config.MIN_SEGMENT_SIZE_BYTES / (1024**2):.1f} MB)"
                )
                logger.warning(f"⚠️ {msg}")
                recording.errors.append(msg)
                # Continue quand même
            
            # 3. Déplacer vers final/
            final_name = f"{recording.match_id}_final.mp4"
            final_path = recording.final_dir / final_name
            
            # Si le fichier final existe déjà, le supprimer (écrasement)
            if final_path.exists():
                final_path.unlink()
            
            tmp_file.rename(final_path)
            
            logger.info(
                f"✅ Vidéo finale: {final_path.name} ({file_size_mb:.1f} MB)"
            )
            
            recording.final_video_path = str(final_path)
            recording.status = "completed"
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur critique finalisation: {e}")
            recording.errors.append(f"Erreur finalisation: {e}")
            return False
            
            recording.final_video_path = final_path
            
            # 4. Nettoyer tmp/
            self._cleanup_tmp_files(recording)
            
            return True
                
        except Exception as e:
            msg = f"Erreur finalisation: {e}"
            logger.error(f"❌ {msg}")
            recording.errors.append(msg)
            return False
    
    def _find_segments(
        self,
        recording: RecordingInfo
    ) -> List[Path]:
        """Trouver tous les segments d'un enregistrement"""
        pattern = f"segment_{recording.recording_id}_*.mp4"
        segments = sorted(recording.tmp_dir.glob(pattern))
        return segments
    
    def _validate_segments(
        self,
        segments: List[Path],
        recording: RecordingInfo
    ) -> List[Path]:
        """
        Valider que les segments sont lisibles et suffisamment gros
        
        Returns:
            Liste des segments valides
        """
        valid_segments = []
        
        for segment in segments:
            try:
                size = segment.stat().st_size
                
                if size < config.MIN_SEGMENT_SIZE_BYTES:
                    logger.warning(
                        f"⚠️ Segment trop petit ignoré: {segment.name} "
                        f"({size} bytes)"
                    )
                    continue
                
                valid_segments.append(segment)
                logger.debug(
                    f"✓ Segment valide: {segment.name} "
                    f"({size / (1024**2):.1f} MB)"
                )
                
            except Exception as e:
                logger.warning(
                    f"⚠️ Erreur validation segment {segment.name}: {e}"
                )
                continue
        
        return valid_segments
    
    def _rename_single_segment(
        self,
        segment: Path,
        recording: RecordingInfo
    ) -> Optional[Path]:
        """Renommer un segment unique vers final"""
        try:
            final_name = f"{recording.match_id}_final.mp4"
            final_path = recording.final_dir / final_name
            
            segment.rename(final_path)
            
            logger.info(
                f"✅ Segment renommé: {segment.name} → {final_name}"
            )
            
            return final_path
            
        except Exception as e:
            logger.error(
                f"❌ Erreur renommage segment: {e}"
            )
            return None
    
    def _concatenate_segments(
        self,
        segments: List[Path],
        recording: RecordingInfo
    ) -> Optional[Path]:
        """Concaténer plusieurs segments en un fichier final"""
        try:
            # Créer liste de segments pour FFmpeg
            list_file = recording.tmp_dir / "segments_list.txt"
            
            with open(list_file, 'w') as f:
                for segment in segments:
                    # Échapper les backslashes pour Windows
                    escaped_path = str(segment).replace('\\', '/')
                    f.write(f"file '{escaped_path}'\n")
            
            logger.info(
                f"📝 Liste segments créée: {list_file}"
            )
            
            # Fichier de sortie
            final_name = f"{recording.match_id}_final.mp4"
            final_path = recording.final_dir / final_name
            
            # Commande de concaténation
            cmd = [
                config.FFMPEG_PATH,
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",  # Copy sans réencodage
                "-y",
                str(final_path)
            ]
            
            logger.info(
                f"🎬 Concaténation de {len(segments)} segments..."
            )
            
            # Exécuter
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )
            
            if result.returncode == 0 and final_path.exists():
                logger.info(
                    f"✅ Segments concaténés: {final_name}"
                )
                return final_path
            else:
                logger.error(
                    f"❌ Échec concaténation: "
                    f"{result.stderr[:500]}"
                )
                return None
                
        except Exception as e:
            logger.error(
                f"❌ Erreur concaténation: {e}"
            )
            return None
    
    def _finalize_single_file(
        self,
        temp_file: Path,
        recording: RecordingInfo
    ) -> Optional[Path]:
        """Finaliser un fichier unique (.part → .mp4)"""
        try:
            final_name = f"{recording.match_id}_final.mp4"
            final_path = recording.final_dir / final_name
            
            # Si .part, renommer
            if temp_file.suffix == '.part':
                final_temp = temp_file.with_suffix('.mp4')
                temp_file.rename(final_temp)
                temp_file = final_temp
            
            # Déplacer vers final
            temp_file.rename(final_path)
            
            logger.info(
                f"✅ Fichier finalisé: {final_name}"
            )
            
            return final_path
            
        except Exception as e:
            logger.error(
                f"❌ Erreur finalisation fichier: {e}"
            )
            return None
    
    def _cleanup_tmp_files(self, recording: RecordingInfo):
        """Nettoyer les fichiers temporaires"""
        try:
            # Supprimer segments originaux
            for segment in recording.tmp_dir.glob(
                f"segment_{recording.recording_id}_*.mp4"
            ):
                try:
                    segment.unlink()
                    logger.debug(f"🗑️ Supprimé: {segment.name}")
                except Exception as e:
                    logger.warning(
                        f"⚠️ Impossible de supprimer {segment.name}: {e}"
                    )
            
            # Supprimer liste de segments
            list_file = recording.tmp_dir / "segments_list.txt"
            if list_file.exists():
                list_file.unlink()
            
            logger.info(
                f"✅ Fichiers temporaires nettoyés: "
                f"{recording.recording_id}"
            )
            
        except Exception as e:
            logger.warning(
                f"⚠️ Erreur nettoyage fichiers tmp: {e}"
            )
    
    def _start_monitoring(self):
        """Démarrer le thread de monitoring des enregistrements"""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="RecordingMonitor"
        )
        self.monitor_thread.start()
        
        logger.info("👀 Thread monitoring démarré")
    
    def _monitor_loop(self):
        """Boucle de monitoring des enregistrements actifs"""
        while self.monitoring:
            try:
                with self.lock:
                    recording_ids = list(self.recordings.keys())
                
                for recording_id in recording_ids:
                    with self.lock:
                        if recording_id not in self.recordings:
                            continue
                        
                        recording = self.recordings[recording_id]
                    
                    # Vérifier seulement les enregistrements actifs
                    if recording.status != 'recording':
                        continue
                    
                    # Vérifier si processus terminé
                    if recording.process.poll() is not None:
                        logger.info(
                            f"ℹ️ Processus FFmpeg terminé pour "
                            f"{recording_id}"
                        )
                        self.stop_recording(
                            recording_id,
                            reason="process_ended"
                        )
                        continue
                    
                    # Vérifier timeout
                    now = datetime.now()
                    if now >= recording.expected_end_time:
                        logger.info(
                            f"⏱️ Durée atteinte pour {recording_id}"
                        )
                        self.stop_recording(
                            recording_id,
                            reason="timeout"
                        )
                        continue
                
                # Pause
                time.sleep(config.PROCESS_CHECK_INTERVAL)
                
            except Exception as e:
                logger.error(
                    f"❌ Erreur dans boucle monitoring: {e}"
                )
                time.sleep(5)
        
        logger.info("🛑 Thread monitoring arrêté")
    
    def get_recording_info(
        self,
        recording_id: str
    ) -> Optional[dict]:
        """Obtenir les informations d'un enregistrement"""
        with self.lock:
            if recording_id in self.recordings:
                return self.recordings[recording_id].to_dict()
            return None
    
    def get_all_active(self) -> List[dict]:
        """Obtenir tous les enregistrements actifs"""
        with self.lock:
            return [
                rec.to_dict()
                for rec in self.recordings.values()
                if rec.status == 'recording'
            ]
    
    def get_all_recordings(self) -> List[dict]:
        """Obtenir tous les enregistrements (actifs et terminés)"""
        with self.lock:
            return [rec.to_dict() for rec in self.recordings.values()]
    
    def cleanup_old_recordings(self, max_age_hours: int = 24):
        """Nettoyer les enregistrements terminés anciens"""
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        with self.lock:
            to_remove = []
            
            for recording_id, recording in self.recordings.items():
                if (
                    recording.status in ['stopped', 'failed']
                    and recording.start_time < cutoff_time
                ):
                    to_remove.append(recording_id)
            
            for recording_id in to_remove:
                del self.recordings[recording_id]
                logger.info(
                    f"🗑️ Enregistrement nettoyé: {recording_id}"
                )
        
        if to_remove:
            logger.info(
                f"✅ {len(to_remove)} enregistrement(s) nettoyé(s)"
            )
    
    def stop_all(self):
        """Arrêter tous les enregistrements"""
        logger.info("🛑 Arrêt de tous les enregistrements...")
        
        recording_ids = list(self.recordings.keys())
        
        for recording_id in recording_ids:
            recording = self.recordings[recording_id]
            if recording.status == 'recording':
                self.stop_recording(recording_id, reason="shutdown")
        
        # Arrêter monitoring
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("✅ Tous les enregistrements arrêtés")


# Instance globale
_recording_manager = None


def get_recording_manager() -> RecordingManager:
    """Obtenir l'instance globale du RecordingManager"""
    global _recording_manager
    
    if _recording_manager is None:
        _recording_manager = RecordingManager()
    
    return _recording_manager
