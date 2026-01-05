"""
Configuration for Padel Highlights Generator
Adapted for PadelVar application
"""

import os
from src.config.bunny_config import BUNNY_CONFIG

# ===== HIGHLIGHTS CONFIGURATION =====

class HighlightsConfig:
    """Configuration for automated highlights generation"""
    
    # Video Processing
    TARGET_DURATION = int(os.getenv('HIGHLIGHTS_DURATION', '90'))  # seconds
    MIN_CLIP_DURATION = 3.0  # seconds
    MAX_CLIP_DURATION = 12.0  # seconds
    
    # AI Models (if enabled)
    ENABLE_AI_DETECTION = os.getenv('ENABLE_AI_DETECTION', 'false').lower() == 'true'
    YOLO_POSE_MODEL = 'yolov8n-pose.pt'
    YOLO_OBJECT_MODEL = 'yolov8n.pt'
    
    # Scoring Weights (for AI analysis)
    WEIGHTS = {
        'audio_energy': 0.25,
        'motion_intensity': 0.20,
        'action_detection': 0.30,
        'rally_length': 0.15,
        'crowd_reaction': 0.10
    }
    
    # Storage Paths
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    TEMP_DIR = os.path.join(BASE_DIR, 'temp_highlights')
    CACHE_DIR = os.path.join(BASE_DIR, 'cache_highlights')
    
    # Ensure directories exist
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # Bunny CDN (from bunny_config)
    BUNNY_API_KEY = BUNNY_CONFIG['api_key']
    BUNNY_LIBRARY_ID = BUNNY_CONFIG['library_id']
    BUNNY_CDN_HOSTNAME = BUNNY_CONFIG['cdn_hostname']
    BUNNY_HIGHLIGHTS_COLLECTION = 'highlights'  # Collection name
    
    # Background Processing
    MAX_CONCURRENT_JOBS = int(os.getenv('HIGHLIGHTS_MAX_JOBS', '2'))
    CELERY_QUEUE = 'highlights'
    JOB_TIMEOUT = 3600  # 1 hour max per job
    
    # Video Generation
    OUTPUT_FPS = 30
    OUTPUT_CODEC = 'libx264'
    OUTPUT_BITRATE = '8000k'
    OUTPUT_PRESET = 'medium'  # fast, medium, slow
    
    # Effects
    ENABLE_SLOW_MOTION = True
    SLOW_MOTION_FACTOR = 0.5  # 50% speed
    ENABLE_TRANSITIONS = True
    TRANSITION_DURATION = 0.5  # seconds
    
    # Music
    ENABLE_BACKGROUND_MUSIC = os.getenv('HIGHLIGHTS_MUSIC', 'false').lower() == 'true'
    MUSIC_VOLUME = 0.3  # 30% of original
    ORIGINAL_AUDIO_VOLUME = 0.8  # 80% of original
    
    # Simple Mode (without AI)
    SIMPLE_MODE = not ENABLE_AI_DETECTION
    SIMPLE_INTERVAL_SECONDS = 30  # Extract clip every N seconds
    SIMPLE_CLIPS_COUNT = 6  # Number of clips to extract

# Export configuration
HIGHLIGHTS_CONFIG = {
    'target_duration': HighlightsConfig.TARGET_DURATION,
    'min_clip_duration': HighlightsConfig.MIN_CLIP_DURATION,
    'max_clip_duration': HighlightsConfig.MAX_CLIP_DURATION,
    'enable_ai': HighlightsConfig.ENABLE_AI_DETECTION,
    'simple_mode': HighlightsConfig.SIMPLE_MODE,
    'temp_dir': HighlightsConfig.TEMP_DIR,
    'cache_dir': HighlightsConfig.CACHE_DIR,
    'max_concurrent_jobs': HighlightsConfig.MAX_CONCURRENT_JOBS,
}
