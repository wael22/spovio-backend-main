
"""
Gestionnaire de sessions caméra pour PadelVar
Utilise go2rtc_proxy_service.py pour gérer les flux vidéo par terrain
Architecture inspirée de go2rtc pour plus de fiabilité
"""

import logging
import uuid
import time
import subprocess
import threading
import requests
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from .go2rtc_proxy_service import Go2RTCProxyService

logger = logging.getLogger(__name__)

# Services proxy actifs par terrain
_proxy_services: Dict[str, Go2RTCProxyService] = {}
_proxy_threads: Dict[str, threading.Thread] = {}


@dataclass
class CameraSession:
    """Session caméra pour un terrain"""
    session_id: str
    court_id: int
    source_url: str
    source_type: str
    local_mjpeg_url: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    recording: bool = False
    recording_process: Optional[subprocess.Popen] = None
    verified: bool = False


class CameraSessionManager:
    def __init__(self):
        self.sessions: Dict[str, CameraSession] = {}
        self.max_sessions = 10
        
        # Mapping des terrains vers les caméras (from proxy_manager)
        self.camera_mapping = {
            1: "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi",
            2: "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi", 
            3: "http://213.3.30.80:6001/mjpg/video.mjpg",
            4: "http://213.3.30.80:6001/mjpg/video.mjpg",
            5: "http://213.3.30.80:6001/mjpg/video.mjpg"
        }

    def create_session_for_court(self, court_id: int) -> CameraSession:
        """Créer une session caméra pour un terrain"""
        if len(self.sessions) >= self.max_sessions:
            raise ValueError(f"Nombre maximum de sessions ({self.max_sessions}) atteint")

        # Vérifier si une session existe déjà pour ce terrain
        existing_session = self.get_session_for_court(court_id)
        if existing_session:
            logger.info(f"Session existante trouvée pour terrain {court_id}: {existing_session.session_id}")
            return existing_session

        session_id = f"court_{court_id}_{uuid.uuid4().hex[:8]}"
        source_url = self.camera_mapping.get(court_id, self.camera_mapping[1])
        source_type = self.detect_source_type(source_url)
        
        logger.info(f"Création session {session_id} pour terrain {court_id}")
        logger.info(f"Source: {source_url} ({source_type})")

        # Démarrer le proxy HTTP MJPEG
        local_mjpeg_url = self.setup_http_proxy(session_id, source_url)

        # Vérifier le flux
        try:
            verified = self.verify_stream(local_mjpeg_url)
        except Exception as e:
            logger.warning(f"Vérification flux échouée pour {session_id}: {e}")
            verified = False

        session = CameraSession(
            session_id=session_id,
            court_id=court_id,
            source_url=source_url,
            source_type=source_type,
            local_mjpeg_url=local_mjpeg_url,
            verified=verified
        )
        
        self.sessions[session_id] = session
        
        logger.info(f"Session {session_id} créée avec succès")
        logger.info(f"URL locale: {local_mjpeg_url}")
        return session

    def get_session_for_court(self, court_id: int) -> Optional[CameraSession]:
        """Obtenir la session active pour un terrain"""
        for session in self.sessions.values():
            if session.court_id == court_id:
                return session
        return None

    def detect_source_type(self, url: str) -> str:
        """Détecter le type de source vidéo"""
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        
        if scheme in ["rtsp", "rtsps"]:
            return "rtsp"
        elif scheme in ["http", "https"]:
            if "mjpg" in url.lower() or "mjpeg" in url.lower():
                return "mjpeg"
            return "mjpeg"
        else:
            return "unknown"

    def setup_http_proxy(self, session_id: str, source_url: str) -> str:
        """Démarrer un proxy HTTP MJPEG avec go2rtc_proxy_service"""
        # Nettoyer l'ancien proxy s'il existe
        existing_service = _proxy_services.get(session_id)
        if existing_service:
            logger.warning(f"Arrêt de l'ancien proxy pour {session_id}")
            try:
                # Arrêter le service
                existing_service._running = False
                # Arrêter le thread
                existing_thread = _proxy_threads.get(session_id)
                if existing_thread and existing_thread.is_alive():
                    existing_thread.join(timeout=3)
                logger.info(f"Ancien proxy arrêté pour {session_id}")
            except Exception as e:
                logger.error(f"Erreur arrêt proxy: {e}")
            finally:
                _proxy_services.pop(session_id, None)
                _proxy_threads.pop(session_id, None)
            time.sleep(1)

        # Trouver un port libre
        proxy_port = self.find_free_port()
        if proxy_port is None:
            raise RuntimeError("Aucun port libre disponible")

        # Créer le service go2rtc proxy
        logger.info(f"Création proxy Go2RTC pour {session_id} sur port {proxy_port}")
        logger.info(f"Source: {source_url}")
        
        try:
            # Créer le service proxy
            from .go2rtc_proxy_service import create_proxy_service
            
            proxy_service = create_proxy_service(
                source_url=source_url,
                port=proxy_port,
                proxy_format="mjpeg",
                ffmpeg_loglevel="warning"
            )
            
            # Démarrer le service dans un thread séparé
            def run_proxy():
                try:
                    # Pas de signal handlers dans les threads
                    proxy_service.run_server(setup_signals=False)
                except Exception as e:
                    logger.error(f"Erreur dans le proxy {session_id}: {e}")
            
            proxy_thread = threading.Thread(
                target=run_proxy,
                name=f"proxy-{session_id}",
                daemon=True
            )
            proxy_thread.start()
            
            # Attendre que le service démarre
            time.sleep(3)
            
            # Vérifier que le thread est actif
            if not proxy_thread.is_alive():
                raise RuntimeError("Le thread proxy n'a pas démarré correctement")
            
            # Sauvegarder les références
            _proxy_services[session_id] = proxy_service
            _proxy_threads[session_id] = proxy_thread
            
            proxy_url = f"http://127.0.0.1:{proxy_port}/stream.mjpeg"
            health_url = f"http://127.0.0.1:{proxy_port}/health"
            
            # Attendre que le proxy soit prêt
            timeout = 15
            deadline = time.time() + timeout
            ready = False
            
            logger.info(f"Attente proxy prêt: {proxy_url}")
            while time.time() < deadline:
                try:
                    # Test health endpoint
                    r = requests.get(health_url, timeout=3)
                    if r.status_code == 200:
                        ready = True
                        logger.info("Proxy Go2RTC prêt!")
                        break
                except Exception:
                time.sleep(1)

            if not ready:
                logger.warning(f"Proxy non prêt après {timeout}s, mais on continue")
            
            logger.info(f"Proxy Go2RTC démarré: {proxy_url}")
            return proxy_url
            
        except Exception as e:
            logger.error(f"Erreur création proxy pour {session_id}: {e}")
            # Nettoyage en cas d'erreur
            _proxy_services.pop(session_id, None)
            _proxy_threads.pop(session_id, None)
            raise

    def find_free_port(self, start_port: int = 8080) -> Optional[int]:
        """Trouver un port libre de manière thread-safe"""
        import socket
        
        # Vérifier les ports déjà utilisés par les sessions existantes
        used_ports = set()
        for session in self.sessions.values():
            if session.local_mjpeg_url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(session.local_mjpeg_url)
                    if parsed.port:
                        used_ports.add(parsed.port)
                except Exception:
        # Chercher un port libre en évitant ceux déjà utilisés
        for port in range(start_port, start_port + 200):
            if port in used_ports:
                continue
                
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    logger.info(f"Port {port} trouvé libre")
                    return port
            except OSError:
                continue
                
        logger.error("Aucun port libre trouvé")
        return None

    def verify_stream(self, stream_url: str, max_attempts: int = 2) -> bool:
        """Vérifier que le flux vidéo fonctionne"""
        timeout = 5
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"Vérification flux {stream_url} (tentative {attempt + 1}/{max_attempts})")
                
                # Test simple avec requests
                response = requests.get(stream_url, stream=True, timeout=timeout)
                if response.status_code == 200:
                    # Lire quelques bytes pour vérifier le contenu
                    content = next(response.iter_content(chunk_size=1024))
                    response.close()
                    
                    if len(content) > 100:  # Au moins 100 bytes reçus
                        logger.info(f"Flux vérifié: {len(content)} bytes reçus")
                        return True
                
                response.close()
                
            except Exception as e:
                logger.warning(f"Erreur vérification flux (tentative {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
        
        return False

    def change_camera_source(self, court_id: int, new_source_url: str) -> CameraSession:
        """Changer la source caméra d'un terrain"""
        session = self.get_session_for_court(court_id)
        if not session:
            raise RuntimeError(f"Aucune session pour terrain {court_id}")

        if session.recording:
            raise RuntimeError("Impossible de changer la source pendant un enregistrement")

        logger.info(f"Changement source terrain {court_id}: {new_source_url}")
        
        # Récupérer le processus proxy
        proc = _proxy_processes.get(session.session_id)
        if proc:
            # Extraire le port de l'URL actuelle
            parsed = urlparse(session.local_mjpeg_url)
            port = parsed.port
            
            try:
                # Utiliser l'API change_source du proxy
                change_url = f"http://127.0.0.1:{port}/change_source"
                r = requests.post(change_url, params={"new_source": new_source_url})
                if r.status_code == 200:
                    logger.info("Source changée avec succès")
                    
                    # Mettre à jour la session
                    session.source_url = new_source_url
                    session.source_type = self.detect_source_type(new_source_url)
                    self.camera_mapping[court_id] = new_source_url
                    
                    # Vérifier le nouveau flux
                    try:
                        session.verified = self.verify_stream(session.local_mjpeg_url)
                    except Exception as e:
                        logger.warning(f"Vérification nouveau flux échouée: {e}")
                        session.verified = False
                    
                    return session
                else:
                    raise RuntimeError(f"Échec changement source: {r.status_code}")
            except Exception as e:
                logger.error(f"Erreur changement source: {e}")
                # En cas d'échec, recréer la session
                self.close_session(session.session_id)
                return self.create_session_for_court(court_id)

        raise RuntimeError("Proxy non trouvé pour cette session")

    def get_session(self, session_id: str) -> Optional[CameraSession]:
        """Obtenir une session par ID"""
        return self.sessions.get(session_id)

    def close_session(self, session_id: str):
        """Fermer une session"""
        session = self.sessions.get(session_id)
        if not session:
            logger.warning(f"Session {session_id} non trouvée")
            return

        logger.info(f"Fermeture session {session_id}")

        # Arrêter le service proxy Go2RTC
        service = _proxy_services.get(session_id)
        if service:
            try:
                logger.info(f"Arrêt service proxy Go2RTC pour {session_id}")
                service._running = False
                # Arrêter le thread
                thread = _proxy_threads.get(session_id)
                if thread and thread.is_alive():
                    thread.join(timeout=5)
                logger.info(f"Service proxy arrêté pour {session_id}")
            except Exception as e:
                logger.error(f"Erreur arrêt service proxy: {e}")
            finally:
                _proxy_services.pop(session_id, None)
                _proxy_threads.pop(session_id, None)

        # Supprimer la session
        del self.sessions[session_id]
        logger.info(f"Session {session_id} fermée")
    
    def cleanup_all_proxies(self):
        """Nettoyer tous les services proxy actifs"""
        logger.info("Nettoyage de tous les services proxy...")
        
        for session_id in list(_proxy_services.keys()):
            try:
                self.close_session(session_id)
            except Exception as e:
                logger.error(f"Erreur lors du nettoyage de {session_id}: {e}")
        
        # Nettoyage final
        _proxy_services.clear()
        _proxy_threads.clear()
        
        logger.info("Nettoyage terminé")

    def get_all_sessions(self) -> Dict[str, CameraSession]:
        """Obtenir toutes les sessions"""
        return self.sessions.copy()

    def cleanup(self):
        """Nettoyer toutes les sessions"""
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            self.close_session(session_id)


# Instance globale
camera_session_manager = CameraSessionManager()