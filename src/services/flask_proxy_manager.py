"""
Service Flask pour gérer les proxies vidéo
Gère le démarrage, l'arrêt et la configuration des serveurs proxy vidéo
"""
import logging
import threading
import time
from typing import Dict, Optional
from .flask_video_proxy_server import FlaskVideoProxyServer
import requests

logger = logging.getLogger(__name__)


class FlaskProxyManager:
    """Gestionnaire des proxies vidéo pour les terrains de padel"""
    
    def __init__(self, base_port: int = 8001, max_courts: int = 10):
        self.proxies: Dict[int, dict] = {}
        self.base_port = base_port
        self.max_courts = max_courts
        self.lock = threading.Lock()
    
    async def start_proxy(self, court_id: int, camera_url: Optional[str] = None) -> int:
        """Démarrer un proxy vidéo pour un terrain"""
        with self.lock:
            if court_id in self.proxies and self.proxies[court_id].get("proxy"):
                logger.info(f"Proxy for court {court_id} already running")
                if camera_url:
                    await self.set_camera_url(court_id, camera_url)
                return self.proxies[court_id]["port"]
        
        if court_id < 1 or court_id > self.max_courts:
            raise ValueError(f"Court ID must be between 1 and {self.max_courts}")
        
        port = self.base_port + (court_id - 1)
        
        # Créer une instance du proxy vidéo
        proxy = FlaskVideoProxyServer(court_id)
        
        # Démarrer la capture si une URL de caméra est fournie
        if camera_url:
            await proxy.set_camera_url(camera_url)
        
        with self.lock:
            self.proxies[court_id] = {
                "port": port,
                "proxy": proxy,
                "camera_url": camera_url,
                "started_at": time.time()
            }
        
        logger.info(f"Started proxy for court {court_id} on port {port}")
        return port
    
    async def stop_proxy(self, court_id: int):
        """Arrêter un proxy vidéo"""
        with self.lock:
            if court_id not in self.proxies:
                logger.warning(f"No proxy found for court {court_id}")
                return
            
            proxy = self.proxies[court_id].get("proxy")
        
        if proxy:
            await proxy.shutdown()
            logger.info(f"Stopped proxy for court {court_id}")
        
        with self.lock:
            if court_id in self.proxies:
                del self.proxies[court_id]
    
    async def set_camera_url(self, court_id: int, camera_url: str):
        """Définir l'URL de la caméra pour un terrain"""
        with self.lock:
            if court_id not in self.proxies:
                # Créer le proxy s'il n'existe pas
                await self.start_proxy(court_id, camera_url)
                return
            
            proxy = self.proxies[court_id].get("proxy")
            self.proxies[court_id]["camera_url"] = camera_url
        
        if proxy:
            await proxy.set_camera_url(camera_url)
            logger.info(f"Updated camera URL for court {court_id}")
    
    def get_proxy_port(self, court_id: int) -> Optional[int]:
        """Obtenir le port du proxy pour un terrain"""
        with self.lock:
            if court_id in self.proxies:
                return self.proxies[court_id]["port"]
        return None
    
    def get_stream_url(self, court_id: int, host: str = "localhost") -> str:
        """Obtenir l'URL du flux vidéo pour un terrain"""
        port = self.get_proxy_port(court_id)
        if port is None:
            port = self.base_port + (court_id - 1)
        
        return f"http://{host}:{port}/stream.mjpg"
    
    def is_proxy_healthy(self, court_id: int) -> bool:
        """Vérifier si un proxy vidéo est en bonne santé"""
        with self.lock:
            if court_id not in self.proxies:
                return False
            
            proxy = self.proxies[court_id].get("proxy")
        
        if proxy:
            status = proxy.get_health_status()
            return status.get("running", False) and status.get("connected", False)
        
        return False
    
    def get_proxy_status(self, court_id: int) -> Optional[dict]:
        """Obtenir le statut d'un proxy vidéo"""
        with self.lock:
            if court_id not in self.proxies:
                return None
            
            proxy = self.proxies[court_id].get("proxy")
        
        if proxy:
            return proxy.get_health_status()
        
        return None
    
    async def shutdown_all(self):
        """Arrêter tous les proxies vidéo"""
        logger.info("Shutting down all proxies")
        with self.lock:
            court_ids = list(self.proxies.keys())
        
        for court_id in court_ids:
            await self.stop_proxy(court_id)
    
    def get_all_proxies_status(self) -> dict:
        """Obtenir le statut de tous les proxies vidéo"""
        with self.lock:
            return {
                court_id: proxy_data["proxy"].get_health_status()
                for court_id, proxy_data in self.proxies.items()
                if proxy_data.get("proxy")
            }


# Instance globale du gestionnaire de proxies
proxy_manager = None


def get_proxy_manager(base_port: int = 8001, max_courts: int = 10) -> FlaskProxyManager:
    """Obtenir ou créer l'instance globale du gestionnaire de proxies"""
    global proxy_manager
    if proxy_manager is None:
        proxy_manager = FlaskProxyManager(base_port, max_courts)
    return proxy_manager
