"""
RTSP Proxy Manager - Gestionnaire de Proxies RTSP
Gère plusieurs serveurs RTSP proxy pour différents terrains

Architecture:
    RTSPProxyManager
        ├── RTSPProxyServer (terrain_1) → rtsp://127.0.0.1:8554/terrain_1
        ├── RTSPProxyServer (terrain_2) → rtsp://127.0.0.1:8555/terrain_2
        └── ...

Usage avec RecordingManager:
    proxy_manager = get_proxy_manager()
    proxy_url = proxy_manager.start_proxy(terrain_id=1, camera_url="http://...")
    # proxy_url = "rtsp://127.0.0.1:8554/terrain_1"
    
    # Utiliser proxy_url avec FFmpeg
    # ...
    
    proxy_manager.stop_proxy(terrain_id=1)
"""

import logging
import threading
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from src.recording_config.recording_config import config

# Import conditionnel du serveur RTSP
try:
    from .rtsp_proxy_server import RTSPProxyServer, ProxyConfig, GSTREAMER_AVAILABLE
except ImportError:
    GSTREAMER_AVAILABLE = False
    logging.warning("rtsp_proxy_server non disponible")

logger = logging.getLogger(__name__)


@dataclass
class ProxyInfo:
    """Informations sur un proxy actif"""
    terrain_id: int
    camera_url: str
    proxy_url: str
    listen_port: int
    start_time: float
    server: 'RTSPProxyServer'


class RTSPProxyManager:
    """
    Gestionnaire de proxies RTSP multi-terrains
    
    Responsabilités:
    - Allocation automatique des ports
    - Création/arrêt des proxies
    - Monitoring et stats
    - Thread-safe
    """
    
    def __init__(self):
        self._proxies: Dict[int, ProxyInfo] = {}
        self._lock = threading.Lock()
        self._base_port = 8554  # Port de base RTSP
        self._port_allocations: Dict[int, int] = {}  # terrain_id -> port
        
        logger.info("🎬 RTSPProxyManager initialisé")
        
        if not GSTREAMER_AVAILABLE:
            logger.warning(
                "⚠️ GStreamer non disponible. "
                "Les proxies RTSP ne fonctionneront pas. "
                "Installez GStreamer pour activer cette fonctionnalité."
            )
    
    def _allocate_port(self, terrain_id: int) -> int:
        """
        Alloue un port pour un terrain
        
        Returns:
            Port alloué (8554 + terrain_id)
        """
        with self._lock:
            if terrain_id in self._port_allocations:
                return self._port_allocations[terrain_id]
            
            # Port = base_port + terrain_id
            # Terrain 1 → 8554, Terrain 2 → 8555, etc.
            port = self._base_port + terrain_id
            
            self._port_allocations[terrain_id] = port
            logger.info(f"🔓 Port {port} alloué au terrain {terrain_id}")
            
            return port
    
    def _release_port(self, terrain_id: int):
        """Libère le port d'un terrain"""
        with self._lock:
            if terrain_id in self._port_allocations:
                port = self._port_allocations[terrain_id]
                del self._port_allocations[terrain_id]
                logger.info(f"🔐 Port {port} libéré (terrain {terrain_id})")
    
    def start_proxy(
        self,
        terrain_id: int,
        camera_url: str,
        buffer_seconds: float = 3.0
    ) -> Tuple[bool, Optional[str], str]:
        """
        Démarre un proxy RTSP pour un terrain
        
        Args:
            terrain_id: ID du terrain
            camera_url: URL de la caméra source
            buffer_seconds: Taille du buffer (défaut: 3.0s)
        
        Returns:
            (success: bool, proxy_url: str ou None, message: str)
        """
        if not GSTREAMER_AVAILABLE:
            msg = (
                "GStreamer non disponible. "
                "Impossible de démarrer le proxy RTSP."
            )
            logger.error(f"❌ {msg}")
            return False, None, msg
        
        with self._lock:
            # Vérifier si un proxy existe déjà
            if terrain_id in self._proxies:
                proxy_info = self._proxies[terrain_id]
                if proxy_info.server.is_running():
                    logger.info(
                        f"♻️ Proxy déjà actif terrain {terrain_id}"
                    )
                    return (
                        True,
                        proxy_info.proxy_url,
                        "Proxy déjà actif"
                    )
                else:
                    # Proxy existe mais n'est plus actif, on le supprime
                    logger.warning(
                        f"⚠️ Proxy terrain {terrain_id} inactif, restart..."
                    )
                    del self._proxies[terrain_id]
        
        try:
            # Allouer un port
            port = self._allocate_port(terrain_id)
            
            # Créer la configuration
            proxy_config = ProxyConfig(
                terrain_id=terrain_id,
                source_url=camera_url,
                listen_port=port,
                buffer_seconds=buffer_seconds,
                bitrate_kbps=config.VIDEO_BITRATE if hasattr(config, 'VIDEO_BITRATE') else 4000
            )
            
            # Créer le serveur RTSP
            server = RTSPProxyServer(proxy_config)
            
            # Démarrer le serveur
            server.start()
            
            # Obtenir l'URL du proxy
            proxy_url = server.get_proxy_url()
            
            # Stocker les informations
            proxy_info = ProxyInfo(
                terrain_id=terrain_id,
                camera_url=camera_url,
                proxy_url=proxy_url,
                listen_port=port,
                start_time=time.time(),
                server=server
            )
            
            with self._lock:
                self._proxies[terrain_id] = proxy_info
            
            logger.info(
                f"✅ Proxy RTSP démarré terrain {terrain_id}"
            )
            logger.info(
                f"📡 URL: {proxy_url}"
            )
            
            return True, proxy_url, "Proxy démarré avec succès"
            
        except Exception as e:
            logger.error(
                f"❌ Erreur démarrage proxy terrain {terrain_id}: {e}"
            )
            self._release_port(terrain_id)
            return False, None, f"Erreur: {str(e)}"
    
    def stop_proxy(self, terrain_id: int, immediate: bool = False):
        """
        Arrête un proxy RTSP
        
        Args:
            terrain_id: ID du terrain
            immediate: Si True, arrêt immédiat. Sinon, délai de 30s
        """
        with self._lock:
            if terrain_id not in self._proxies:
                logger.warning(
                    f"⚠️ Aucun proxy actif pour terrain {terrain_id}"
                )
                return
            
            proxy_info = self._proxies[terrain_id]
        
        logger.info(f"🛑 Arrêt proxy terrain {terrain_id}")
        
        try:
            # Arrêter le serveur
            proxy_info.server.stop()
            
            # Supprimer de la liste
            with self._lock:
                del self._proxies[terrain_id]
            
            # Libérer le port (avec délai optionnel)
            if not immediate:
                # Attendre 30s avant de libérer le port
                # (au cas où un autre enregistrement démarre rapidement)
                threading.Timer(
                    30.0,
                    lambda: self._release_port(terrain_id)
                ).start()
                logger.info("⏳ Port sera libéré dans 30s")
            else:
                self._release_port(terrain_id)
            
            logger.info(f"✅ Proxy arrêté terrain {terrain_id}")
            
        except Exception as e:
            logger.error(
                f"❌ Erreur arrêt proxy terrain {terrain_id}: {e}"
            )
    
    def get_proxy_url(self, terrain_id: int) -> Optional[str]:
        """
        Obtient l'URL du proxy pour un terrain
        
        Returns:
            URL du proxy ou None si pas actif
        """
        with self._lock:
            if terrain_id in self._proxies:
                return self._proxies[terrain_id].proxy_url
            return None
    
    def get_stats(self, terrain_id: int) -> Optional[dict]:
        """
        Obtient les statistiques d'un proxy
        
        Returns:
            Dictionnaire de stats ou None
        """
        with self._lock:
            if terrain_id not in self._proxies:
                return None
            
            proxy_info = self._proxies[terrain_id]
            stats = proxy_info.server.get_stats()
            
            # Ajouter des infos supplémentaires
            stats.update({
                "camera_url": proxy_info.camera_url,
                "proxy_url": proxy_info.proxy_url,
                "listen_port": proxy_info.listen_port,
            })
            
            return stats
    
    def get_all_stats(self) -> dict:
        """
        Obtient les stats de tous les proxies
        
        Returns:
            {
                "total_proxies": int,
                "proxies": [...]
            }
        """
        with self._lock:
            return {
                "total_proxies": len(self._proxies),
                "gstreamer_available": GSTREAMER_AVAILABLE,
                "proxies": [
                    {
                        "terrain_id": info.terrain_id,
                        "camera_url": info.camera_url,
                        "proxy_url": info.proxy_url,
                        "listen_port": info.listen_port,
                        "uptime": time.time() - info.start_time,
                        "stats": info.server.get_stats()
                    }
                    for info in self._proxies.values()
                ]
            }
    
    def stop_all(self):
        """Arrête tous les proxies"""
        logger.info("🛑 Arrêt de tous les proxies RTSP...")
        
        terrain_ids = list(self._proxies.keys())
        
        for terrain_id in terrain_ids:
            self.stop_proxy(terrain_id, immediate=True)
        
        logger.info("✅ Tous les proxies RTSP arrêtés")


# Instance globale (singleton)
_proxy_manager: Optional[RTSPProxyManager] = None


def get_proxy_manager() -> RTSPProxyManager:
    """
    Obtient l'instance globale du RTSPProxyManager (singleton)
    
    Returns:
        Instance du RTSPProxyManager
    """
    global _proxy_manager
    
    if _proxy_manager is None:
        _proxy_manager = RTSPProxyManager()
    
    return _proxy_manager
