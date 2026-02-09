# Configuration pour le système d'enregistrement MJPEG vers Bunny Stream

import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class MJPEGRecorderConfig:
    """Configuration pour l'enregistrement MJPEG vers Bunny Stream"""
    
    # Configuration MJPEG
    mjpeg_url: str = "http://63.142.190.238:6120/mjpg/video.mjpg"
    
    # Configuration Bunny Stream
    bunny_api_key: str = "ac7bcccc-69bc-47aa-ae8fed1c3364-5693-4e1b"  # Updated 2026-02-01
    library_id: str = "589708"  # Updated 2026-02-01
    base_url: str = "https://video.bunnycdn.com"
    upload_timeout: int = 300  # 5 minutes
    
    # Configuration FFmpeg
    segment_duration: int = 300  # 5 minutes par segment
    video_quality: int = 23  # CRF (Constant Rate Factor)
    preset: str = "fast"  # ultrafast, fast, slow
    
    # Configuration des chemins
    temp_dir: str = "temp_recordings"
    # Chemin complet vers FFmpeg
    ffmpeg_path: str = (
        r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
    )
    
    # Configuration monitoring
    max_retries: int = 3
    retry_delay: int = 5
    max_age_hours: int = 24  # Nettoyage automatique des fichiers temporaires
    
    @classmethod
    def from_env(cls) -> 'MJPEGRecorderConfig':
        """Charge la configuration depuis les variables d'environnement"""
        return cls(
            mjpeg_url=os.getenv('MJPEG_URL', cls.mjpeg_url),
            bunny_api_key=os.getenv('BUNNY_API_KEY', cls.bunny_api_key),
            library_id=os.getenv('BUNNY_LIBRARY_ID', cls.library_id),
            base_url=os.getenv('BUNNY_BASE_URL', cls.base_url),
            upload_timeout=int(os.getenv('UPLOAD_TIMEOUT', cls.upload_timeout)),
            segment_duration=int(os.getenv('SEGMENT_DURATION', cls.segment_duration)),
            video_quality=int(os.getenv('VIDEO_QUALITY', cls.video_quality)),
            preset=os.getenv('FFMPEG_PRESET', cls.preset),
            temp_dir=os.getenv('TEMP_DIR', cls.temp_dir),
            ffmpeg_path=os.getenv('FFMPEG_PATH', cls.ffmpeg_path),
            max_retries=int(os.getenv('MAX_RETRIES', cls.max_retries)),
            retry_delay=int(os.getenv('RETRY_DELAY', cls.retry_delay)),
            max_age_hours=int(os.getenv('MAX_AGE_HOURS', cls.max_age_hours))
        )
    
    def to_dict(self) -> dict:
        """Convertit la configuration en dictionnaire"""
        return {
            'mjpeg_url': self.mjpeg_url,
            'bunny_api_key': '***masked***',  # Ne pas exposer la clé API
            'library_id': self.library_id,
            'base_url': self.base_url,
            'upload_timeout': self.upload_timeout,
            'segment_duration': self.segment_duration,
            'video_quality': self.video_quality,
            'preset': self.preset,
            'temp_dir': self.temp_dir,
            'ffmpeg_path': self.ffmpeg_path,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'max_age_hours': self.max_age_hours
        }
    
    def validate(self) -> bool:
        """Valide la configuration"""
        if not self.mjpeg_url or not self.mjpeg_url.startswith(('http://', 'https://')):
            return False
        
        if not self.bunny_api_key or len(self.bunny_api_key) < 10:
            return False
        
        if not self.library_id:
            return False
        
        return True
