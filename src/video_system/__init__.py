"""
PadelVar Video System - Architecture Stable
============================================

Pipeline: Caméra IP → video_proxy_server.py → FFmpeg → MP4

Composants:
- SessionManager: Gestion sessions caméra
- ProxyManager: Gestion proxies vidéo (proxy interne uniquement)
- VideoRecorder: Enregistrement FFmpeg (un seul MP4)
- PreviewManager: Preview WebSocket

Caractéristiques:
- Pas de segmentation vidéo
- Proxy universel pour tous les flux (MJPEG, RTSP, HTTP)
- Multi-terrain / Multi-enregistrements simultanés
- Arrêt propre et robuste
"""

from .config import VideoConfig
from .session_manager import SessionManager, VideoSession, session_manager
from .proxy_manager import ProxyManager
from .recording import VideoRecorder, video_recorder
from .preview import PreviewManager, preview_manager

__all__ = [
    'VideoConfig',
    'SessionManager',
    'VideoSession',
    'ProxyManager',
    'VideoRecorder',
    'PreviewManager',
    'session_manager',
    'video_recorder',
    'preview_manager'
]
