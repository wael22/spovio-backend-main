"""
Proxy Manager - Gestion des Proxies Vidéo
=========================================

Responsabilités:
- Démarrer/arrêter proxies vidéo via video_proxy_server.py
- Allouer ports dynamiquement
- Vérifier santé proxy
- UN SEUL TYPE DE PROXY pour tous les flux
"""

import logging
import subprocess
import time
import requests
import sys
from typing import Optional, Tuple
from pathlib import Path

from .config import VideoConfig

logger = logging.getLogger(__name__)


def start_proxy_server(session_id: str, source_url: str, port: int) -> subprocess.Popen:
    """
    Démarrer le serveur proxy FastAPI + uvicorn + OpenCV
    
    Args:
        session_id: ID de la session
        source_url: URL source de la caméra
        port: Port HTTP local
        
    Returns:
        Processus subprocess du serveur
    """
    # Chemin vers le script proxy
    script_path = Path(__file__).parent / "video_proxy_server.py"
    
    # Commande pour démarrer le proxy
    cmd = [
        sys.executable,
        str(script_path),
        "--source", source_url,
        "--port", str(port),
        "--fps", "25",
        "--quality", "80"
    ]
    
    logger.info(f"🚀 Starting video proxy server on port {port}")
    logger.info(f"   Source: {source_url}")
    logger.info(f"   Python Executable: {sys.executable}")
    logger.info(f"   Command: {cmd}")
    
    # Démarrer le processus
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False
    )
    
    logger.info(f"✅ Video proxy server started (PID: {process.pid})")
    
    return process


class ProxyManager:
    """Gestionnaire de proxies vidéo (proxy interne universel)"""
    
    def __init__(self):
        self.active_proxies = {}  # port -> process
        logger.info("🎥 ProxyManager initialisé (VERSION FIX_V2)")
    
    def start_proxy(
        self,
        session_id: str,
        camera_url: str,
        port: Optional[int] = None
    ) -> Tuple[str, int, subprocess.Popen]:
        """
        Démarrer un proxy vidéo universel
        
        Args:
            session_id: ID de la session
            camera_url: URL de la caméra source (MJPEG, RTSP, HTTP)
            port: Port HTTP local (si None, allocation automatique)
            
        Returns:
            (local_url, port, process)
        """
        # Allouer un port si nécessaire
        if port is None:
            port = VideoConfig.allocate_port()
        
        logger.info(f"🚀 Démarrage proxy pour {session_id}")
        logger.info(f"   Source: {camera_url}")
        logger.info(f"   Port: {port}")
        
        # Démarrer le proxy
        try:
            process = start_proxy_server(
                session_id=session_id,
                source_url=camera_url,
                port=port
            )
            
            # Attendre que le serveur soit prêt
            time.sleep(2)
            
            if process.poll() is not None:
                # Process died - read stderr for error message
                stderr_output = process.stderr.read() if process.stderr else b''
                stdout_output = process.stdout.read() if process.stdout else b''
                error_msg = f"Proxy s'est arrêté immédiatement. Exit code: {process.returncode}"
                if stderr_output:
                    error_msg += f"\nSTDERR: {stderr_output.decode('utf-8', errors='ignore')}"
                if stdout_output:
                    error_msg += f"\nSTDOUT: {stdout_output.decode('utf-8', errors='ignore')}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Vérifier la santé (OBLIGATOIRE)
            local_url = f"http://127.0.0.1:{port}/stream.mjpg"
            if not self._wait_for_proxy_ready(port, timeout=30):
                # CRITICAL: Ne pas continuer si le proxy n'est pas prêt
                logger.error("❌ Proxy démarré mais le flux vidéo n'est pas disponible - arrêt du proxy")
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except:
                    process.kill()
                VideoConfig.free_port(port)
                raise RuntimeError(f"Proxy sur port {port}: flux vidéo non disponible après 30 secondes")
            
            self.active_proxies[port] = process
            
            logger.info(f"✅ Proxy démarré: {local_url}")
            return local_url, port, process
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage proxy: {e}")
            VideoConfig.free_port(port)
            raise
    
    def stop_proxy(self, port: int):
        """
        Arrêter un proxy
        
        Args:
            port: Port du proxy à arrêter
        """
        process = self.active_proxies.get(port)
        if not process:
            logger.warning(f"⚠️ Aucun proxy actif sur port {port}")
            return
        
        logger.info(f"🛑 Arrêt proxy (port {port})")
        
        try:
            # Arrêt propre
            process.terminate()
            
            # Attendre
            try:
                process.wait(timeout=5)
                logger.info(f"✅ Proxy arrêté proprement")
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️ Timeout, kill forcé")
                process.kill()
                process.wait()
            
            del self.active_proxies[port]
            VideoConfig.free_port(port)
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt proxy: {e}")
    
    def check_proxy_health(self, port: int) -> bool:
        """
        Vérifier si un proxy est en bonne santé
        
        Args:
            port: Port du proxy
            
        Returns:
            True si le proxy répond
        """
        process = self.active_proxies.get(port)
        if not process:
            return False
        
        # Vérifier que le processus tourne
        if process.poll() is not None:
            logger.warning(f"⚠️ Processus proxy mort (port {port})")
            return False
        
        # Vérifier le endpoint health
        try:
            response = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def _wait_for_proxy_ready(self, port: int, timeout: int = 15) -> bool:
        """
        Attendre que le proxy soit prêt ET qu'il ait du contenu vidéo
        
        Args:
            port: Port du proxy
            timeout: Timeout en secondes
            
        Returns:
            True si le proxy a du contenu vidéo
        """
        start_time = time.time()
        last_status = None
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"http://127.0.0.1:{port}/health", timeout=1)
                if response.status_code == 200:
                    data = response.json()
                    last_status = data.get("status")
                    
                    # Vérifier que le proxy a vraiment du contenu vidéo
                    if data.get("has_video", False):
                        logger.info(f"✅ Proxy prêt avec contenu vidéo (port {port})")
                        return True
                    else:
                        logger.debug(f"⏳ Proxy démarré mais pas encore de vidéo (status={last_status})")
            except Exception as e:
                logger.debug(f"⏳ Attente proxy (port {port}): {e}")
                pass
            
            time.sleep(0.5)
        
        logger.error(f"❌ Timeout waiting for proxy video content (port {port}, last_status={last_status})")
        return False
    
    def cleanup_all(self):
        """Arrêter tous les proxies actifs"""
        logger.info(f"🧹 Nettoyage de {len(self.active_proxies)} proxy(s)")
        
        ports = list(self.active_proxies.keys())
        for port in ports:
            self.stop_proxy(port)
        
        logger.info("✅ Tous les proxies arrêtés")
