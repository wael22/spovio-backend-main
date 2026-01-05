from __future__ import annotations
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

# Dataclass indépendante (Étape 2)
# Sera intégrée ensuite dans video_capture_service


@dataclass
class RecordingTask:
    session_id: str
    camera_url: str
    output_path: str
    max_duration: int
    user_id: int
    court_id: int
    session_name: str
    video_quality: Dict[str, Any]

    start_time: datetime = field(default_factory=datetime.now)
    status: str = 'created'  # created|recording|stopping|completed|error
    process: Optional[subprocess.Popen] = None
    camera_stream: Optional[Any] = None
    error: Optional[str] = None
    file_size: int = 0
    recording_type: Optional[str] = None  # mjpeg_single|bunny|rtsp|opencv
    bunny_session_id: Optional[str] = None

    # Instrumentation
    frame_count: int = 0
    last_ffmpeg_line: Optional[str] = None
    ffmpeg_fps: Optional[float] = None
    ffmpeg_bit_rate: Optional[str] = None
    last_frame_wallclock: Optional[datetime] = None
    started_monotonic: float = field(default_factory=time.monotonic)
    last_update_monotonic: float = field(default_factory=time.monotonic)

    def update_ffmpeg_stats(self, line: str):
        self.last_ffmpeg_line = line.strip()
        self.last_update_monotonic = time.monotonic()
        try:
            if 'frame=' in line:
                parts = line.split()
                for p in parts:
                    if p.startswith('frame='):
                        try:
                            self.frame_count = int(p.split('frame=')[-1])
                        except ValueError:
                            pass
                    elif p.startswith('fps='):
                        try:
                            self.ffmpeg_fps = float(p.split('fps=')[-1])
                        except ValueError:
                            pass
                    elif p.startswith('bitrate='):
                        self.ffmpeg_bit_rate = p.split('bitrate=')[-1]
        except Exception:
            # Parsing best-effort
            pass

    def to_dict(self) -> Dict[str, Any]:
        duration = int((datetime.now() - self.start_time).total_seconds())
        return {
            'session_id': self.session_id,
            'camera_url': self.camera_url,
            'output_path': self.output_path,
            'status': self.status,
            'start_time': self.start_time.isoformat(),
            'duration': duration,
            'user_id': self.user_id,
            'court_id': self.court_id,
            'session_name': self.session_name,
            'file_size': self.file_size,
            'error': self.error,
            'recording_type': self.recording_type,
            'frame_count': self.frame_count,
            'ffmpeg_fps': self.ffmpeg_fps,
            'ffmpeg_bit_rate': self.ffmpeg_bit_rate,
            'last_ffmpeg_line': self.last_ffmpeg_line,
        }
