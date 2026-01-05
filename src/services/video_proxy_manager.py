#!/usr/bin/env python3
"""
Video Proxy Manager for PadelVar
Manages multiple video proxy instances for simultaneous recordings on different courts
"""

import threading
import logging
import time
import cv2
from flask import Flask, Response
from typing import Dict, Optional
import multiprocessing
from pathlib import Path

logger = logging.getLogger(__name__)

class VideoProxyInstance:
    """Instance de proxy vidéo pour un terrain spécifique"""
    
    def __init__(self, terrain_id: int, camera_url: str, port: int):
        self.terrain_id = terrain_id
        self.camera_url = camera_url
        self.port = port
        self.cap = None
        self.frame = None
        self.frame_lock = threading.Lock()
        self.capture_thread = None
        self.running = False
        self.fps = 25
        self.frame_interval = 1.0 / self.fps
        self.last_frame_time = 0
        self.app = None
        self.server_thread = None
        
    def start(self) -> bool:
        """Démarrer le proxy pour ce terrain"""
        try:
            logger.info(f"🎥 Démarrage proxy terrain {self.terrain_id} sur port {self.port}")
            
            # Connexion à la caméra
            self.cap = cv2.VideoCapture(self.camera_url)
            if not self.cap.isOpened():
                logger.error(f"❌ Impossible de se connecter à la caméra: {self.camera_url}")
                return False
            
            # Configuration de la capture
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            
            self.running = True
            
            # Démarrer le thread de capture
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            
            logger.info(f"✅ Proxy terrain {self.terrain_id} démarré avec succès")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage proxy terrain {self.terrain_id}: {e}")
            self.stop()
            return False
    
    def _capture_loop(self):
        """Boucle de capture des frames à FPS constant"""
        logger.info(f"📹 Thread de capture démarré pour terrain {self.terrain_id}")
        consecutive_failures = 0
        max_failures = 30
        
        while self.running:
            try:
                current_time = time.time()
                
                # Limiter le framerate
                time_since_last_frame = current_time - self.last_frame_time
                if time_since_last_frame < self.frame_interval:
                    time.sleep(self.frame_interval - time_since_last_frame)
                    continue
                
                # Lire une frame
                ret, frame = self.cap.read()
                
                if ret and frame is not None:
                    # Redimensionner si nécessaire (optimisation)
                    if frame.shape[1] > 1280:
                        height = int(frame.shape[0] * (1280 / frame.shape[1]))
                        frame = cv2.resize(frame, (1280, height))
                    
                    with self.frame_lock:
                        self.frame = frame.copy()
                    
                    self.last_frame_time = current_time
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f"⚠️ Échec lecture frame terrain {self.terrain_id} ({consecutive_failures}/{max_failures})")
                    
                    if consecutive_failures >= max_failures:
                        logger.error(f"❌ Trop d'échecs consécutifs, arrêt du proxy terrain {self.terrain_id}")
                        self.running = False
                        break
                    
                    time.sleep(0.1)
                    
            except Exception as e:
                logger.error(f"❌ Erreur dans capture loop terrain {self.terrain_id}: {e}")
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    self.running = False
                    break
                time.sleep(1)
        
        logger.info(f"🛑 Thread de capture arrêté pour terrain {self.terrain_id}")
    
    def get_stream_url(self) -> str:
        """Retourner l'URL du stream local"""
        return f"http://127.0.0.1:{self.port}/stream.mjpg"
    
    def get_frame(self) -> Optional[bytes]:
        """Obtenir la frame actuelle encodée en JPEG"""
        with self.frame_lock:
            if self.frame is None:
                return None
            
            ret, jpeg = cv2.imencode('.jpg', self.frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                return jpeg.tobytes()
            return None
    
    def stop(self):
        """Arrêter le proxy"""
        logger.info(f"🛑 Arrêt du proxy terrain {self.terrain_id}")
        self.running = False
        
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=5)
        
        if self.cap:
            self.cap.release()
        
        logger.info(f"✅ Proxy terrain {self.terrain_id} arrêté")
    
    def is_healthy(self) -> bool:
        """Vérifier que le proxy fonctionne correctement"""
        return self.running and self.cap and self.cap.isOpened()


class VideoProxyManager:
    """Gestionnaire de proxys vidéo pour plusieurs terrains"""
    
    def __init__(self):
        self.proxies: Dict[int, VideoProxyInstance] = {}  # terrain_id -> proxy_instance
        self.base_port = 8080
        self.lock = threading.Lock()
        logger.info("🎬 VideoProxyManager initialisé")
    
    def start_proxy(self, terrain_id: int, camera_url: str) -> Optional[str]:
        """
        Démarrer un proxy pour un terrain spécifique
        
        Args:
            terrain_id: ID du terrain
            camera_url: URL de la caméra IP
            
        Returns:
            URL du stream local ou None si échec
        """
        with self.lock:
            # Vérifier si un proxy existe déjà
            if terrain_id in self.proxies:
                proxy = self.proxies[terrain_id]
                if proxy.is_healthy():
                    logger.info(f"♻️ Proxy existant réutilisé pour terrain {terrain_id}")
                    return proxy.get_stream_url()
                else:
                    logger.warning(f"⚠️ Proxy existant non sain, redémarrage pour terrain {terrain_id}")
                    self.stop_proxy(terrain_id)
            
            # Allouer un port disponible
            port = self._allocate_port()
            
            # Créer et démarrer le proxy
            proxy = VideoProxyInstance(terrain_id, camera_url, port)
            
            if proxy.start():
                self.proxies[terrain_id] = proxy
                logger.info(f"✅ Proxy créé pour terrain {terrain_id} sur port {port}")
                return proxy.get_stream_url()
            else:
                logger.error(f"❌ Échec création proxy pour terrain {terrain_id}")
                return None
    
    def stop_proxy(self, terrain_id: int) -> bool:
        """
        Arrêter le proxy d'un terrain
        
        Args:
            terrain_id: ID du terrain
            
        Returns:
            True si succès
        """
        with self.lock:
            if terrain_id not in self.proxies:
                logger.warning(f"⚠️ Aucun proxy à arrêter pour terrain {terrain_id}")
                return False
            
            proxy = self.proxies[terrain_id]
            proxy.stop()
            del self.proxies[terrain_id]
            
            logger.info(f"✅ Proxy arrêté et supprimé pour terrain {terrain_id}")
            return True
    
    def get_proxy_stream_url(self, terrain_id: int) -> Optional[str]:
        """Obtenir l'URL du stream pour un terrain"""
        with self.lock:
            if terrain_id in self.proxies:
                proxy = self.proxies[terrain_id]
                if proxy.is_healthy():
                    return proxy.get_stream_url()
            return None
    
    def get_proxy_frame(self, terrain_id: int) -> Optional[bytes]:
        """Obtenir la frame JPEG actuelle d'un terrain"""
        with self.lock:
            if terrain_id in self.proxies:
                return self.proxies[terrain_id].get_frame()
            return None
    
    def _allocate_port(self) -> int:
        """Allouer un port disponible pour un nouveau proxy"""
        used_ports = {proxy.port for proxy in self.proxies.values()}
        port = self.base_port
        
        while port in used_ports:
            port += 1
        
        return port
    
    def get_active_proxies(self) -> Dict[int, dict]:
        """Obtenir la liste des proxys actifs"""
        with self.lock:
            return {
                terrain_id: {
                    'terrain_id': terrain_id,
                    'camera_url': proxy.camera_url,
                    'port': proxy.port,
                    'stream_url': proxy.get_stream_url(),
                    'healthy': proxy.is_healthy()
                }
                for terrain_id, proxy in self.proxies.items()
            }
    
    def cleanup_inactive_proxies(self):
        """Nettoyer les proxys inactifs ou non sains"""
        with self.lock:
            inactive = []
            for terrain_id, proxy in self.proxies.items():
                if not proxy.is_healthy():
                    logger.warning(f"⚠️ Proxy terrain {terrain_id} non sain, marqué pour nettoyage")
                    inactive.append(terrain_id)
            
            for terrain_id in inactive:
                self.stop_proxy(terrain_id)
            
            if inactive:
                logger.info(f"🧹 {len(inactive)} proxy(s) inactif(s) nettoyé(s)")
    
    def stop_all(self):
        """Arrêter tous les proxys"""
        logger.info("🛑 Arrêt de tous les proxys...")
        with self.lock:
            terrain_ids = list(self.proxies.keys())
            for terrain_id in terrain_ids:
                self.stop_proxy(terrain_id)
        logger.info("✅ Tous les proxys arrêtés")


# Instance singleton globale
_proxy_manager_instance = None

def get_proxy_manager() -> VideoProxyManager:
    """Obtenir l'instance singleton du VideoProxyManager"""
    global _proxy_manager_instance
    if _proxy_manager_instance is None:
        _proxy_manager_instance = VideoProxyManager()
    return _proxy_manager_instance
