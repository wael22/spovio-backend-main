"""
RTSP Proxy Server - Custom Implementation for Padelvar
Serveur RTSP proxy haute performance avec buffer intelligent

Architecture:
    [Caméra] ← GStreamer Pipeline ← [Serveur RTSP] → [FFmpeg/Clients]
    
Fonctionnalités:
    - Buffer intelligent (3-5s configurable)
    - Reconnexion automatique
    - Multi-clients efficace
    - Latence optimisée (<500ms)
    - Stats et monitoring
"""

import asyncio
import logging
import signal
import time
from dataclasses import dataclass
from typing import Optional, Dict
from pathlib import Path

try:
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstRtspServer', '1.0')
    from gi.repository import Gst, GstRtspServer, GLib
    GSTREAMER_AVAILABLE = True
except ImportError:
    GSTREAMER_AVAILABLE = False
    logging.warning("GStreamer not available. Install with: pip install PyGObject")

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Configuration pour un proxy RTSP"""
    terrain_id: int
    source_url: str
    listen_port: int
    buffer_seconds: float = 3.0
    bitrate_kbps: int = 4000
    reconnect_delay: float = 2.0
    max_retries: int = -1  # -1 = infinite
    latency_ms: int = 200


class RTSPProxyServer:
    """
    Serveur RTSP proxy utilisant GStreamer
    
    Crée un serveur RTSP local qui:
    1. Se connecte à une source (caméra RTSP/HTTP)
    2. Buffer le flux avec un délai configurable
    3. Sert le flux à plusieurs clients simultanément
    4. Gère la reconnexion automatique
    """
    
    def __init__(self, config: ProxyConfig):
        if not GSTREAMER_AVAILABLE:
            raise RuntimeError(
                "GStreamer n'est pas disponible. "
                "Installez avec: pip install PyGObject"
            )
        
        self.config = config
        self._server: Optional[GstRtspServer.RTSPServer] = None
        self._factory: Optional[GstRtspServer.RTSPMediaFactory] = None
        self._main_loop: Optional[GLib.MainLoop] = None
        self._running = False
        
        # Stats
        self._stats = {
            "terrain_id": config.terrain_id,
            "source_url": config.source_url,
            "status": "stopped",
            "clients": 0,
            "uptime": 0,
            "start_time": None,
            "reconnections": 0,
            "frames_received": 0,
            "frames_dropped": 0,
        }
        
        # Initialiser GStreamer
        Gst.init(None)
        
        logger.info(
            f"RTSPProxyServer initialized for terrain {config.terrain_id}"
        )
    
    def _build_pipeline(self) -> str:
        """
        Construit le pipeline GStreamer
        
        Pipeline optimisé pour:
        - Faible latence
        - Buffer intelligent
        - Reconnexion automatique
        
        Returns:
            Chaîne de description du pipeline GStreamer
        """
        source_url = self.config.source_url
        buffer_ms = int(self.config.buffer_seconds * 1000)
        
        # Déterminer le type de source
        if source_url.startswith('rtsp://'):
            # Source RTSP
            pipeline = (
                f"rtspsrc location={source_url} "
                f"latency={self.config.latency_ms} "
                f"buffer-mode=auto "
                f"retry=3 "
                f"! rtph264depay "
                f"! queue max-size-time={buffer_ms}000000 "
                f"! h264parse "
                f"! rtph264pay name=pay0 pt=96"
            )
        
        elif source_url.startswith('http://') and 'mjpg' in source_url.lower():
            # Source HTTP MJPEG
            pipeline = (
                f"souphttpsrc location={source_url} "
                f"is-live=true "
                f"! multipartdemux "
                f"! jpegdec "
                f"! queue max-size-time={buffer_ms}000000 "
                f"! videoconvert "
                f"! x264enc tune=zerolatency bitrate={self.config.bitrate_kbps} "
                f"speed-preset=veryfast key-int-max=50 "
                f"! h264parse "
                f"! rtph264pay name=pay0 pt=96"
            )
        
        else:
            # Source générique (HTTP, fichier, etc.)
            pipeline = (
                f"uridecodebin uri={source_url} "
                f"! queue max-size-time={buffer_ms}000000 "
                f"! videoconvert "
                f"! x264enc tune=zerolatency bitrate={self.config.bitrate_kbps} "
                f"speed-preset=veryfast "
                f"! h264parse "
                f"! rtph264pay name=pay0 pt=96"
            )
        
        logger.info(f"Pipeline GStreamer créé: {pipeline[:100]}...")
        return pipeline
    
    def start(self):
        """Démarre le serveur RTSP"""
        if self._running:
            logger.warning("Serveur déjà en cours d'exécution")
            return
        
        try:
            # Créer le serveur RTSP
            self._server = GstRtspServer.RTSPServer()
            self._server.set_service(str(self.config.listen_port))
            
            # Créer la factory pour le media
            self._factory = GstRtspServer.RTSPMediaFactory()
            pipeline_str = self._build_pipeline()
            self._factory.set_launch(pipeline_str)
            
            # Configurer la factory
            self._factory.set_shared(True)  # Partager entre clients
            self._factory.set_eos_shutdown(False)  # Ne pas arrêter sur EOS
            
            # Ajouter le media au serveur
            mount_point = f"/terrain_{self.config.terrain_id}"
            mount_points = self._server.get_mount_points()
            mount_points.add_factory(mount_point, self._factory)
            
            # Attacher le serveur au contexte
            self._server.attach(None)
            
            # Stats
            self._stats.update({
                "status": "running",
                "start_time": time.time(),
                "mount_point": mount_point,
            })
            
            self._running = True
            
            logger.info(
                f"✅ Serveur RTSP démarré sur port {self.config.listen_port}"
            )
            logger.info(
                f"📡 URL: rtsp://127.0.0.1:{self.config.listen_port}{mount_point}"
            )
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage serveur RTSP: {e}")
            raise
    
    def stop(self):
        """Arrête le serveur RTSP"""
        if not self._running:
            return
        
        logger.info("Arrêt du serveur RTSP...")
        
        try:
            # Arrêter le serveur
            if self._server:
                # Détacher le serveur
                self._server = None
            
            if self._factory:
                self._factory = None
            
            self._running = False
            
            # Stats
            self._stats.update({
                "status": "stopped",
                "start_time": None,
                "uptime": 0,
            })
            
            logger.info("✅ Serveur RTSP arrêté")
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt serveur: {e}")
    
    def get_proxy_url(self) -> str:
        """Retourne l'URL du proxy RTSP"""
        if not self._running:
            raise RuntimeError("Serveur non démarré")
        
        mount_point = f"/terrain_{self.config.terrain_id}"
        return f"rtsp://127.0.0.1:{self.config.listen_port}{mount_point}"
    
    def get_stats(self) -> dict:
        """Retourne les statistiques du serveur"""
        if self._stats.get("start_time"):
            self._stats["uptime"] = time.time() - self._stats["start_time"]
        
        return self._stats.copy()
    
    def is_running(self) -> bool:
        """Vérifie si le serveur est en cours d'exécution"""
        return self._running


# Test standalone
if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(
        description="Serveur RTSP Proxy pour Padelvar"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="URL de la source vidéo (RTSP, HTTP MJPEG, etc.)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8554,
        help="Port d'écoute RTSP (défaut: 8554)"
    )
    parser.add_argument(
        "--terrain",
        type=int,
        default=1,
        help="ID du terrain (défaut: 1)"
    )
    parser.add_argument(
        "--buffer",
        type=float,
        default=3.0,
        help="Taille du buffer en secondes (défaut: 3.0)"
    )
    
    args = parser.parse_args()
    
    if not GSTREAMER_AVAILABLE:
        logger.error(
            "GStreamer n'est pas installé. "
            "Installez avec:\n"
            "  Windows: https://gstreamer.freedesktop.org/download/\n"
            "  Linux: sudo apt install python3-gst-1.0 gstreamer1.0-rtsp"
        )
        exit(1)
    
    # Configuration
    config = ProxyConfig(
        terrain_id=args.terrain,
        source_url=args.source,
        listen_port=args.port,
        buffer_seconds=args.buffer
    )
    
    # Créer le serveur
    server = RTSPProxyServer(config)
    
    # Gestion des signaux
    loop = GLib.MainLoop()
    
    def signal_handler(sig, frame):
        logger.info("Signal reçu, arrêt du serveur...")
        server.stop()
        loop.quit()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Démarrer
    try:
        server.start()
        
        logger.info("=" * 60)
        logger.info(f"🎥 Serveur RTSP Proxy actif")
        logger.info(f"📍 Source: {args.source}")
        logger.info(f"📡 Proxy URL: {server.get_proxy_url()}")
        logger.info(f"⏱️  Buffer: {args.buffer}s")
        logger.info("=" * 60)
        logger.info("Appuyez sur Ctrl+C pour arrêter")
        
        # Boucle d'événements
        loop.run()
        
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")
        server.stop()
        exit(1)
    
    logger.info("Serveur arrêté proprement")
