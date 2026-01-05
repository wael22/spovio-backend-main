"""
Video System Configuration
===========================

Configuration centralisée pour le système vidéo stable.
Pipeline: Caméra → video_proxy_server.py → FFmpeg → MP4
"""

import os
import platform
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class VideoConfig:
    """Configuration du système vidéo"""
    
    # Chemins
    BASE_DIR = Path(__file__).parent.parent.parent  # Project root
    VIDEOS_DIR = BASE_DIR / "static" / "videos"
    LOGS_DIR = BASE_DIR / "logs" / "video"
    
    # FFmpeg
    FFMPEG_PATH = os.getenv('FFMPEG_PATH', 'ffmpeg')
    FFPROBE_PATH = os.getenv('FFPROBE_PATH', 'ffprobe')
    
    # Proxy settings - UN SEUL TYPE: video_proxy_server.py
    PROXY_BASE_PORT = 8080  # Port de départ pour les proxies MJPEG internes
    PROXY_TYPE = "internal"  # Toujours utiliser le proxy interne
    
    # Recording settings
    DEFAULT_DURATION_SECONDS = 90 * 60  # 90 minutes
    MAX_CONCURRENT_RECORDINGS = 10
    VIDEO_CODEC = "libx264"
    VIDEO_PRESET = "veryfast"
    VIDEO_CRF = 23
    VIDEO_FPS = 25
    
    # Session settings
    SESSION_TIMEOUT_SECONDS = 7200  # 2 heures
    SESSION_CLEANUP_INTERVAL = 300  # 5 minutes
    
    # Preview settings
    PREVIEW_FPS = 5  # Frames par seconde pour preview
    PREVIEW_JPEG_QUALITY = 70
    PREVIEW_MAX_CLIENTS = 5  # Max viewers simultanés par session
    
    # Ports alloués dynamiquement
    _allocated_ports = set()
    
    @classmethod
    def init(cls):
        """Initialiser les répertoires nécessaires"""
        cls.VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("✅ Répertoires vidéo initialisés")
    
    @classmethod
    def validate_ffmpeg(cls) -> bool:
        """Vérifier que FFmpeg est disponible"""
        import subprocess
        try:
            result = subprocess.run(
                [cls.FFMPEG_PATH, "-version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"✅ FFmpeg détecté: {cls.FFMPEG_PATH}")
                return True
        except Exception as e:
            logger.error(f"❌ FFmpeg non trouvé: {e}")
        return False
    
    @classmethod
    def get_video_dir(cls, club_id: int) -> Path:
        """Obtenir le répertoire vidéo pour un club"""
        video_dir = cls.VIDEOS_DIR / str(club_id)
        video_dir.mkdir(parents=True, exist_ok=True)
        return video_dir
    
    @classmethod
    def get_log_path(cls, session_id: str) -> Path:
        """Obtenir le chemin du fichier log FFmpeg"""
        return cls.LOGS_DIR / f"{session_id}.ffmpeg.log"
    
    @classmethod
    def is_windows(cls) -> bool:
        """Vérifier si on est sur Windows"""
        return platform.system() == "Windows"
    
    @classmethod
    def allocate_port(cls) -> int:
        """
        Allouer un port libre dynamiquement
        
        Returns:
            Port libre entre PROXY_BASE_PORT et PROXY_BASE_PORT+1000
        """
        for port in range(cls.PROXY_BASE_PORT, cls.PROXY_BASE_PORT + 1000):
            if port not in cls._allocated_ports:
                cls._allocated_ports.add(port)
                return port
        raise RuntimeError("Aucun port disponible")
    
    @classmethod
    def free_port(cls, port: int):
        """Libérer un port alloué"""
        cls._allocated_ports.discard(port)


# Initialiser au chargement du module
VideoConfig.init()
