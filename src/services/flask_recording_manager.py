"""
Service Flask pour gérer les enregistrements vidéo avec FFmpeg
Adaptation du RecordingManager FastAPI pour fonctionner avec Flask
"""
import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RecordingInfo:
    """Informations sur un enregistrement en cours"""
    
    def __init__(self, match_id: int, court_id: int, video_path: str, process: subprocess.Popen):
        self.match_id = match_id
        self.court_id = court_id
        self.video_path = video_path
        self.process = process
        self.started_at = datetime.utcnow()
        self.lock = threading.Lock()


class FlaskRecordingManager:
    """Gestionnaire d'enregistrements vidéo avec FFmpeg"""
    
    def __init__(self, ffmpeg_path: str = "ffmpeg", video_root: str = "static/videos/matches", 
                 max_concurrent: int = 5, proxy_base_port: int = 8001):
        self.recordings: Dict[int, RecordingInfo] = {}
        self.max_concurrent = max_concurrent
        self.ffmpeg_path = ffmpeg_path
        self.video_root = Path(video_root)
        self.proxy_base_port = proxy_base_port
        self.lock = threading.Lock()
        
        self.video_root.mkdir(parents=True, exist_ok=True)
    
    def start_recording(
        self,
        match_id: int,
        court_id: int,
        duration_seconds: Optional[int] = None,
        proxy_port: Optional[int] = None
    ) -> str:
        """Démarrer un enregistrement vidéo"""
        with self.lock:
            if match_id in self.recordings:
                logger.warning(f"Recording already in progress for match {match_id}")
                raise ValueError(f"Recording already in progress for match {match_id}")
            
            if len(self.recordings) >= self.max_concurrent:
                raise ValueError(f"Maximum concurrent recordings ({self.max_concurrent}) reached")
        
        # Déterminer le port du proxy
        if proxy_port is None:
            proxy_port = self.proxy_base_port + (court_id - 1)
        
        proxy_url = f"http://localhost:{proxy_port}/stream.mjpg"
        
        video_filename = f"match_{match_id}.mp4"
        video_path = self.video_root / video_filename
        
        ffmpeg_cmd = self._build_ffmpeg_command(
            proxy_url,
            str(video_path),
            duration_seconds
        )
        
        logger.info(f"Starting recording for match {match_id}, court {court_id}")
        logger.debug(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            recording_info = RecordingInfo(match_id, court_id, str(video_path), process)
            
            with self.lock:
                self.recordings[match_id] = recording_info
            
            threading.Thread(
                target=self._monitor_recording,
                args=(match_id,),
                daemon=True
            ).start()
            
            logger.info(f"Recording started for match {match_id} -> {video_path}")
            return str(video_path)
            
        except Exception as e:
            logger.error(f"Failed to start recording for match {match_id}: {e}")
            raise
    
    def _build_ffmpeg_command(
        self,
        input_url: str,
        output_path: str,
        duration_seconds: Optional[int] = None
    ) -> list:
        """Construire la commande FFmpeg"""
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_url,
            "-vf", "fps=25",
            "-vsync", "1",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-movflags", "+faststart"
        ]
        
        if duration_seconds:
            cmd.extend(["-t", str(duration_seconds)])
        
        cmd.append(output_path)
        
        return cmd
    
    def stop_recording(self, match_id: int) -> str:
        """Arrêter un enregistrement vidéo"""
        with self.lock:
            if match_id not in self.recordings:
                logger.warning(f"No recording found for match {match_id}")
                raise ValueError(f"No recording found for match {match_id}")
            
            recording = self.recordings[match_id]
        
        logger.info(f"Stopping recording for match {match_id}")
        
        try:
            if recording.process.poll() is None:
                try:
                    recording.process.stdin.write(b'q')
                    recording.process.stdin.flush()
                except Exception as e:
                    logger.warning(f"Failed to send 'q' to FFmpeg: {e}")
                
                try:
                    recording.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.warning(f"FFmpeg did not stop gracefully, terminating")
                    recording.process.terminate()
                    try:
                        recording.process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        logger.error(f"FFmpeg did not terminate, killing")
                        recording.process.kill()
            
            with self.lock:
                del self.recordings[match_id]
            
            logger.info(f"Recording stopped for match {match_id}")
            return recording.video_path
            
        except Exception as e:
            logger.error(f"Error stopping recording for match {match_id}: {e}")
            raise
    
    def is_recording(self, match_id: int) -> bool:
        """Vérifier si un enregistrement est en cours"""
        with self.lock:
            return match_id in self.recordings
    
    def get_active_recordings(self) -> list:
        """Obtenir la liste des enregistrements actifs"""
        with self.lock:
            return [
                {
                    "match_id": rec.match_id,
                    "court_id": rec.court_id,
                    "video_path": rec.video_path,
                    "started_at": rec.started_at.isoformat()
                }
                for rec in self.recordings.values()
            ]
    
    def _monitor_recording(self, match_id: int):
        """Surveiller un enregistrement en cours"""
        try:
            recording = self.recordings.get(match_id)
            if not recording:
                return
            
            process = recording.process
            
            process.wait()
            
            return_code = process.returncode
            
            if return_code != 0:
                stderr_output = process.stderr.read().decode('utf-8', errors='ignore')
                logger.error(
                    f"Recording for match {match_id} ended with error (code {return_code}): "
                    f"{stderr_output[-500:]}"
                )
            else:
                logger.info(f"Recording for match {match_id} completed successfully")
            
            with self.lock:
                if match_id in self.recordings:
                    del self.recordings[match_id]
                    
        except Exception as e:
            logger.error(f"Error monitoring recording for match {match_id}: {e}")
            with self.lock:
                if match_id in self.recordings:
                    del self.recordings[match_id]
    
    def cleanup_zombie_processes(self):
        """Nettoyer les processus FFmpeg zombies"""
        with self.lock:
            dead_matches = []
            for match_id, recording in self.recordings.items():
                if recording.process.poll() is not None:
                    dead_matches.append(match_id)
            
            for match_id in dead_matches:
                logger.info(f"Cleaning up zombie recording for match {match_id}")
                del self.recordings[match_id]


# Instance globale du gestionnaire d'enregistrements
recording_manager = None


def get_recording_manager(ffmpeg_path: str = "ffmpeg", video_root: str = "static/videos/matches",
                          max_concurrent: int = 5, proxy_base_port: int = 8001) -> FlaskRecordingManager:
    """Obtenir ou créer l'instance globale du gestionnaire d'enregistrements"""
    global recording_manager
    if recording_manager is None:
        recording_manager = FlaskRecordingManager(ffmpeg_path, video_root, max_concurrent, proxy_base_port)
    return recording_manager
