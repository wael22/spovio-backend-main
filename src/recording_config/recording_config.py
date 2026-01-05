"""
Configuration centralisée pour le système d'enregistrement vidéo PadelVar
Production-ready configuration with all tunable parameters
"""
import os
from pathlib import Path


class RecordingConfig:
    """Configuration pour l'enregistrement vidéo et les proxies"""
    
    # ==================== CHEMINS ET DOSSIERS ====================
    
    # Chemin FFmpeg
    FFMPEG_PATH = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
    
    # Dossier racine des vidéos
    VIDEO_ROOT = Path(r"C:\Users\PC\Videos\PadelVar")
    
    # Structure: VIDEO_ROOT/<club_id>/<match_id>/tmp/ et /final/
    
    # ==================== PROXY RTSP ====================
    
    # Plage de ports pour les proxies RTSP (un port par terrain)
    PROXY_PORT_START = 8554
    PROXY_PORT_END = 8599
    PROXY_PORT_RANGE = list(range(PROXY_PORT_START, PROXY_PORT_END + 1))
    
    # Host du proxy (local uniquement)
    PROXY_HOST = "127.0.0.1"
    
    # Timeout de connexion à la caméra IP (secondes)
    CAMERA_CONNECTION_TIMEOUT = 5
    
    # Nombre de tentatives de reconnexion
    CAMERA_RETRY_ATTEMPTS = 3
    
    # Test de validité: nombre de frames à lire pour valider le flux
    VALIDATION_FRAMES_COUNT = 3
    
    # Timeout pour le test de frames (secondes)
    VALIDATION_TIMEOUT = 10
    
    # Délai avant libération du port après arrêt (secondes)
    PORT_RELEASE_DELAY = 30
    
    # FPS de capture du proxy
    PROXY_CAPTURE_FPS = 25
    
    # ==================== PARAMÈTRES FFMPEG ====================
    
    # Résolution de sortie (largeur, hauteur auto-calculée)
    VIDEO_WIDTH = 1280
    VIDEO_HEIGHT = -2  # -2 = auto avec préservation aspect ratio
    
    # FPS de sortie
    VIDEO_FPS = 25
    
    # Codec vidéo
    VIDEO_CODEC = "libx264"
    
    # Preset FFmpeg: ultrafast, veryfast, fast, medium, slow
    # veryfast = bon compromis performance/qualité pour enregistrement continu
    FFMPEG_PRESET = "veryfast"
    
    # CRF (Constant Rate Factor): 18-28
    # 23 = qualité standard (défaut FFmpeg)
    VIDEO_CRF = 23
    
    # Options supplémentaires FFmpeg
    FFMPEG_EXTRA_OPTIONS = [
        "-movflags", "+faststart",  # Optimisation streaming web
        "-pix_fmt", "yuv420p",      # Compatibilité maximale
    ]
    
    # ==================== VALIDATION ET SÉCURITÉ ====================
    
    # Taille minimale d'un fichier vidéo valide (bytes)
    # Segment de 60s à 2 Mbps ≈ 15 MB
    MIN_SEGMENT_SIZE_BYTES = 1_000_000  # 1 MB minimum
    
    # Pourcentage minimum de la durée attendue
    # Si enregistrement de 60s dure < 5% (3s), considéré invalide
    MIN_DURATION_PERCENTAGE = 5
    
    # Espace disque minimum requis (bytes)
    # Refuser nouvel enregistrement si < 10 GB disponibles
    MIN_DISK_SPACE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
    
    # Timeout pour arrêt gracieux FFmpeg (secondes)
    FFMPEG_GRACEFUL_SHUTDOWN_TIMEOUT = 10
    
    # ==================== LOGGING ====================
    
    # Dossier des logs
    LOG_DIR = Path("logs/recordings")
    
    # Niveau de log
    LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
    
    # Rotation des logs
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB par fichier
    LOG_BACKUP_COUNT = 5  # Garder 5 fichiers de backup
    
    # ==================== PERFORMANCE ====================
    
    # Nombre maximum d'enregistrements simultanés
    MAX_CONCURRENT_RECORDINGS = 10
    
    # Thread pool size pour monitoring
    MONITOR_THREAD_POOL_SIZE = 5
    
    # Intervalle de vérification des processus (secondes)
    PROCESS_CHECK_INTERVAL = 30
    
    # ==================== MÉTHODES UTILITAIRES ====================
    
    @classmethod
    def ensure_directories(cls):
        """Créer tous les dossiers nécessaires"""
        cls.VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def get_match_tmp_dir(cls, club_id: int, match_id: str) -> Path:
        """Obtenir le dossier temporaire d'un match (utilisé pendant l'enregistrement)"""
        return cls.VIDEO_ROOT / "matches" / str(club_id) / "tmp"
    
    @classmethod
    def get_match_final_dir(cls, club_id: int, match_id: str) -> Path:
        """Obtenir le dossier final d'un match"""
        return cls.VIDEO_ROOT / "matches" / str(club_id)
    
    @classmethod
    def get_final_video_path(cls, club_id: int, court_id: int, timestamp: str) -> Path:
        """Construire le chemin final de la vidéo: match_<court_id>_<timestamp>.mp4"""
        final_dir = cls.get_match_final_dir(club_id, "")  # match_id not needed
        return final_dir / f"match_{court_id}_{timestamp}.mp4"
    
    @classmethod
    def get_proxy_url(cls, port: int, terrain_id: int) -> str:
        """Construire l'URL RTSP du proxy"""
        return f"rtsp://{cls.PROXY_HOST}:{port}/terrain_{terrain_id}"
    
    @classmethod
    def validate_ffmpeg(cls) -> bool:
        """Vérifier que FFmpeg est disponible"""
        return Path(cls.FFMPEG_PATH).exists()
    
    @classmethod
    def get_available_disk_space(cls) -> int:
        """Obtenir l'espace disque disponible (bytes)"""
        import shutil
        stats = shutil.disk_usage(cls.VIDEO_ROOT.parent)
        return stats.free
    
    @classmethod
    def has_sufficient_disk_space(cls) -> bool:
        """Vérifier si espace disque suffisant"""
        return cls.get_available_disk_space() >= cls.MIN_DISK_SPACE_BYTES


# Instance globale
config = RecordingConfig()
