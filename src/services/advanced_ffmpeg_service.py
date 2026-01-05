
"""
Service d'enregistrement FFmpeg avancé pour PadelVar
Utilise camera_session_manager et video_proxy_server.py
"""

import logging
import subprocess
import shutil
import time
import threading
import io
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

from .camera_session_manager import camera_session_manager

logger = logging.getLogger(__name__)


class AdvancedFFmpegRecordingService:
    def __init__(self, config=None):
        self.config = config or {}
        self.recording_processes: Dict[str, subprocess.Popen] = {}
        self.recording_outputs: Dict[str, Path] = {}

    def start_recording(self, session_id: str, court_id: int, 
                        duration_seconds: int) -> str:
        """Démarrer un enregistrement direct avec FFmpeg (sans proxy)"""
        if session_id in self.recording_processes:
            raise ValueError(f"Enregistrement déjà en cours pour {session_id}")

        # Obtenir l'URL de la caméra directement
        camera_urls = {
            1: "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi",
            2: "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi", 
            3: "http://213.3.30.80:6001/mjpg/video.mjpg",
            4: "http://213.3.30.80:6001/mjpg/video.mjpg",
            5: "http://213.3.30.80:6001/mjpg/video.mjpg"
        }
        
        source_url = camera_urls.get(court_id, camera_urls[1])
        logger.info(f"Enregistrement direct pour terrain {court_id}: {source_url}")

        # Préparer le dossier de sortie
        videos_dir = Path(self.config.get('RECORDING_DIR', 'static/videos'))
        videos_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{session_id}_{timestamp}.mp4"
        output_path = videos_dir / output_filename

        # Vérifier FFmpeg
        if not shutil.which('ffmpeg'):
            raise FileNotFoundError("FFmpeg non trouvé dans PATH")

        # Utiliser l'URL directe de la caméra
        input_url = source_url
        
        logger.info(f"Enregistrement terrain {court_id}")
        logger.info(f"Source directe: {input_url}")
        logger.info(f"Durée: {duration_seconds}s")

        # Commande FFmpeg optimisée pour MJPEG
        cmd = [
            "ffmpeg",
            "-y",  # Écraser le fichier de sortie
            "-fflags", "+genpts",  # Générer les timestamps
            "-i", input_url,
            "-t", str(duration_seconds),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",  # Pas d'audio pour les caméras
            str(output_path)
        ]

        logger.info(f"Démarrage enregistrement {session_id}")
        logger.info(f"Durée: {duration_seconds}s")

        try:
            # Démarrer le processus FFmpeg
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE
            )

            # Démarrer les threads de logging
            log_path = output_path.with_suffix('.ffmpeg.log')
            self._start_logging_threads(process, session_id, log_path)

            # Sauvegarder les références
            self.recording_processes[session_id] = process
            self.recording_outputs[session_id] = output_path
            
            logger.info(f"Enregistrement {session_id} démarré, PID: {process.pid}")
            return str(output_path)

        except Exception as e:
            logger.error(f"Erreur démarrage enregistrement {session_id}: {e}")
            raise

    def stop_recording(self, session_id: str) -> Optional[str]:
        """Arrêter un enregistrement"""
        if session_id not in self.recording_processes:
            logger.warning(f"Aucun processus pour {session_id}")
            return None

        process = self.recording_processes[session_id]
        output_path = self.recording_outputs.get(session_id)

        logger.info(f"Arrêt enregistrement {session_id}, PID: {process.pid}")

        try:
            # Terminer proprement avec q (FFmpeg)
            try:
                process.stdin.write(b'q\n')
                process.stdin.flush()
            except Exception:
            # Attendre l'arrêt gracieux
            try:
                process.wait(timeout=10)
                logger.info(f"Processus {process.pid} arrêté gracieusement")
            except subprocess.TimeoutExpired:
                logger.warning(f"Processus {process.pid} non arrêté, kill forcé")
                process.kill()
                process.wait(timeout=5)

        except Exception as e:
            logger.error(f"Erreur arrêt enregistrement {session_id}: {e}")
            try:
                process.kill()
            except Exception:
        finally:
            # Nettoyer les références
            self.recording_processes.pop(session_id, None)
            self.recording_outputs.pop(session_id, None)

            # Marquer les sessions caméra comme non en enregistrement
            for camera_session in camera_session_manager.get_all_sessions().values():
                if camera_session.recording_process == process:
                    camera_session.recording = False
                    camera_session.recording_process = None
                    break

        return str(output_path) if output_path else None

    def get_recording_status(self, session_id: str) -> dict:
        """Obtenir le statut d'un enregistrement"""
        if session_id not in self.recording_processes:
            return {"recording": False, "completed": True}

        process = self.recording_processes[session_id]
        poll_result = process.poll()

        if poll_result is None:
            # Processus actif
            return {"recording": True, "completed": False, "pid": process.pid}
        else:
            # Processus terminé
            logger.info(f"Enregistrement {session_id} terminé avec code {poll_result}")
            
            # Nettoyer
            self.recording_processes.pop(session_id, None)
            output_path = self.recording_outputs.pop(session_id, None)
            
            # Vérifier la taille du fichier
            if output_path and output_path.exists():
                size = output_path.stat().st_size
                min_size = 50 * 1024  # 50 KB minimum
                if size < min_size:
                    logger.error(f"Fichier trop petit: {output_path} ({size} bytes)")

            return {"recording": False, "completed": True, 
                   "exit_code": poll_result}

    def _wait_for_stream(self, url: str, timeout: int = 5) -> bool:
        """Attendre que le flux soit disponible"""
        import requests
        
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = requests.get(url, stream=True, timeout=2)
                if resp.status_code == 200:
                    resp.close()
                    return True
            except Exception:
            time.sleep(0.5)
        
        return False

    def _start_logging_threads(self, process: subprocess.Popen, 
                              session_id: str, log_path: Path):
        """Démarrer les threads de logging FFmpeg"""
        try:
            log_file = open(log_path, 'a', encoding='utf-8', errors='replace')
        except Exception:
            log_file = None

        def log_stream(stream, log_fn, sid: str, fh=None):
            """Logger un stream FFmpeg"""
            if not stream:
                return
            try:
                text_stream = io.TextIOWrapper(stream, encoding='utf-8', 
                                             errors='replace')
                for line in text_stream:
                    line = line.rstrip('\n')
                    if line:
                        try:
                            if fh:
                                fh.write(line + '\n')
                                fh.flush()
                        except Exception:
                        log_fn(f"[ffmpeg][{sid}] {line}")
            except Exception as e:
                logger.debug(f"Erreur lecture stream FFmpeg {sid}: {e}")

        # Threads pour stdout et stderr
        threading.Thread(
            target=log_stream, 
            args=(process.stderr, logger.error, session_id, log_file), 
            daemon=True
        ).start()
        
        threading.Thread(
            target=log_stream, 
            args=(process.stdout, logger.info, session_id, log_file), 
            daemon=True
        ).start()

        # Thread pour fermer le fichier log quand le processus se termine
        def close_log_when_done(p: subprocess.Popen, fh):
            try:
                p.wait()
            finally:
                try:
                    if fh:
                        fh.close()
                except Exception:
        threading.Thread(
            target=close_log_when_done, 
            args=(process, log_file), 
            daemon=True
        ).start()

    def cleanup_all_recordings(self):
        """Nettoyer tous les enregistrements"""
        logger.info("Nettoyage de tous les enregistrements")
        session_ids = list(self.recording_processes.keys())
        for session_id in session_ids:
            try:
                self.stop_recording(session_id)
            except Exception as e:
                logger.error(f"Erreur nettoyage {session_id}: {e}")


# Instance globale
advanced_ffmpeg_service = AdvancedFFmpegRecordingService()