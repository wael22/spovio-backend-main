"""
Contexte d'enregistrement pour le système de padel
Remplace l'ancien RecordingTask avec une approche plus structurée
"""
from __future__ import annotations
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path


@dataclass
class RecordingContext:
    """Contexte complet d'un enregistrement vidéo"""
    # Identifiants
    recording_id: str
    user_id: int
    court_id: int
    match_id: Optional[int] = None
    club_id: Optional[int] = None
    
    # Configuration caméra
    camera_url: str = ""
    camera_type: str = "rtsp"  # rtsp, mjpeg, http
    
    # Paramètres enregistrement
    max_duration: int = 3600  # secondes
    output_path: str = ""
    quality_preset: str = "medium"  # low, medium, high
    
    # État du processus
    status: str = 'created'  # created|starting|recording|stopping|processing|completed|error  # noqa: E501
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    process: Optional[subprocess.Popen] = None
    error: Optional[str] = None
    
    # Métadonnées fichier
    file_size: int = 0
    duration: float = 0.0
    resolution: Optional[tuple[int, int]] = None
    fps: Optional[float] = None
    bitrate: Optional[str] = None
    
    # Suivi upload
    upload_status: str = 'pending'  # pending|uploading|completed|failed
    bunny_video_id: Optional[str] = None
    bunny_url: Optional[str] = None
    upload_progress: float = 0.0
    
    # Instrumentation
    frame_count: int = 0
    last_ffmpeg_line: Optional[str] = None
    started_monotonic: float = field(default_factory=time.monotonic)
    last_update_monotonic: float = field(default_factory=time.monotonic)
    
    def __post_init__(self):
        if not self.output_path:
            self.output_path = f"recordings/{self.recording_id}.mp4"
    
    @property
    def elapsed_seconds(self) -> float:
        """Durée écoulée depuis le début"""
        if self.start_time:
            return (datetime.now() - self.start_time).total_seconds()
        return 0.0
    
    @property
    def should_auto_stop(self) -> bool:
        """Vérifie si l'arrêt automatique doit se déclencher"""
        return self.elapsed_seconds >= self.max_duration
    
    @property
    def output_file(self) -> Path:
        """Chemin du fichier de sortie"""
        return Path(self.output_path)
    
    def update_ffmpeg_stats(self, line: str):
        """Met à jour les statistiques depuis la sortie FFmpeg"""
        self.last_ffmpeg_line = line.strip()
        self.last_update_monotonic = time.monotonic()
        
        try:
            if 'frame=' in line:
                parts = line.split()
                for part in parts:
                    if part.startswith('frame='):
                        try:
                            self.frame_count = int(part.split('=')[1])
                        except (ValueError, IndexError):
                            pass
                    elif part.startswith('fps='):
                        try:
                            self.fps = float(part.split('=')[1])
                        except (ValueError, IndexError):
                            pass
                    elif part.startswith('bitrate='):
                        try:
                            self.bitrate = part.split('=')[1]
                        except IndexError:
                            pass
        except Exception:
            # Parsing best-effort, ne pas planter
            pass
    
    def mark_error(self, error_msg: str):
        """Marque l'enregistrement comme en erreur"""
        self.status = 'error'
        self.error = error_msg
        self.end_time = datetime.now()
    
    def mark_completed(self):
        """Marque l'enregistrement comme terminé"""
        self.status = 'completed'
        self.end_time = datetime.now()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire pour l'API"""
        return {
            'recording_id': self.recording_id,
            'user_id': self.user_id,
            'court_id': self.court_id,
            'match_id': self.match_id,
            'club_id': self.club_id,
            'camera_url': self.camera_url,
            'camera_type': self.camera_type,
            'status': self.status,
            'start_time': (self.start_time.isoformat() 
                         if self.start_time else None),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration': self.duration,
            'max_duration': self.max_duration,
            'file_size': self.file_size,
            'resolution': self.resolution,
            'fps': self.fps,
            'bitrate': self.bitrate,
            'frame_count': self.frame_count,
            'upload_status': self.upload_status,
            'bunny_video_id': self.bunny_video_id,
            'bunny_url': self.bunny_url,
            'upload_progress': self.upload_progress,
            'error': self.error,
            'elapsed_seconds': self.elapsed_seconds,
        }
