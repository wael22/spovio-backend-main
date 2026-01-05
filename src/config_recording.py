"""
Configuration du nouveau système d'enregistrement
Ajoutez ces variables à votre config.py
"""

# Exemple d'ajout à votre DevelopmentConfig ou ProductionConfig

# === CONFIGURATION RECORDING ===

# Répertoires de stockage
RECORDINGS_DIR = "static/recordings"
THUMBNAILS_DIR = "static/thumbnails"

# Limites du système
MAX_RECORDINGS = 5  # Nombre max d'enregistrements simultanés
MIN_DISK_SPACE_GB = 2.0  # Espace disque minimum requis

# Configuration upload
UPLOAD_TYPE = "local"  # "local" ou "bunny"

# Bunny Stream (si activé)
BUNNY_API_KEY = ""  # Votre clé API Bunny
BUNNY_LIBRARY_ID = ""  # ID de votre librairie Bunny
BUNNY_BASE_URL = "https://video.bunnycdn.com"

# FFmpeg
FFMPEG_PATH = "ffmpeg"  # Chemin vers ffmpeg
FFPROBE_PATH = "ffprobe"  # Chemin vers ffprobe

# Qualité par défaut
DEFAULT_RECORDING_QUALITY = "medium"  # low, medium, high
DEFAULT_MAX_DURATION = 3600  # 1 heure en secondes

# JWT (si vous n'avez pas déjà)
JWT_SECRET_KEY = "your-super-secret-jwt-key"
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRES = 3600  # 1 heure
