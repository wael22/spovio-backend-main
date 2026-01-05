"""
Service Flask pour gérer le Video Proxy Server
Adaptation du VideoProxyServer FastAPI pour fonctionner avec Flask
"""
import cv2
import logging
import time
import threading
from typing import Optional
from urllib.parse import urlparse
import re

logger = logging.getLogger(__name__)


class FlaskVideoProxyServer:
    """Serveur proxy vidéo pour capturer et streamer le flux vidéo d'une caméra"""
    
    def __init__(self, court_id: int):
        self.court_id = court_id
        self.camera_url: Optional[str] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.last_frame = None
        self.last_frame_time = 0
        self.frame_lock = threading.Lock()
        self.reconnect_attempts = 0
        self.max_reconnect_delay = 5.0
        self.target_fps = 25
        self.frame_interval = 1.0 / self.target_fps
        self.low_fps_threshold = 5
        self.low_fps_count = 0
        self.capture_thread: Optional[threading.Thread] = None
    
    async def set_camera_url(self, url: str):
        """Définir l'URL de la caméra et démarrer la capture"""
        logger.info(f"[Court {self.court_id}] Setting camera URL: {self._mask_credentials(url)}")
        self.camera_url = url
        if self.running:
            await self._restart_capture()
        else:
            await self._start_capture()
    
    async def _start_capture(self):
        """Démarrer la capture vidéo"""
        if self.running:
            return
        
        self.running = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        logger.info(f"[Court {self.court_id}] Capture started")
    
    async def _restart_capture(self):
        """Redémarrer la capture vidéo"""
        logger.info(f"[Court {self.court_id}] Restarting capture")
        await self._stop_capture()
        time.sleep(0.5)
        await self._start_capture()
    
    async def _stop_capture(self):
        """Arrêter la capture vidéo"""
        self.running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info(f"[Court {self.court_id}] Capture stopped")
    
    def _capture_loop(self):
        """Boucle de capture vidéo"""
        while self.running:
            try:
                if not self.cap or not self.cap.isOpened():
                    self._connect_camera()
                
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    
                    if ret and frame is not None:
                        current_time = time.time()
                        
                        with self.frame_lock:
                            self.last_frame = frame
                            self.last_frame_time = current_time
                        
                        self.reconnect_attempts = 0
                        self.low_fps_count = 0
                        
                        elapsed = time.time() - current_time
                        sleep_time = max(0, self.frame_interval - elapsed)
                        time.sleep(sleep_time)
                    else:
                        logger.warning(f"[Court {self.court_id}] Failed to read frame")
                        self._handle_connection_loss()
                else:
                    time.sleep(1.0)
                    
            except Exception as e:
                logger.error(f"[Court {self.court_id}] Capture error: {e}")
                self._handle_connection_loss()
    
    def _connect_camera(self):
        """Connecter à la caméra"""
        if not self.camera_url:
            return
        
        try:
            logger.info(f"[Court {self.court_id}] Connecting to camera: {self._mask_credentials(self.camera_url)}")
            
            if self.cap:
                self.cap.release()
            
            if self.camera_url.startswith("rtsp://"):
                self.cap = cv2.VideoCapture(self.camera_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            else:
                self.cap = cv2.VideoCapture(self.camera_url)
            
            if self.cap.isOpened():
                logger.info(f"[Court {self.court_id}] Camera connected successfully")
                self.reconnect_attempts = 0
            else:
                raise Exception("Failed to open camera")
                
        except Exception as e:
            logger.error(f"[Court {self.court_id}] Connection failed: {e}")
            self.cap = None
    
    def _handle_connection_loss(self):
        """Gérer la perte de connexion"""
        self.reconnect_attempts += 1
        delay = min(2 ** (self.reconnect_attempts - 1), self.max_reconnect_delay)
        logger.warning(
            f"[Court {self.court_id}] Connection lost, "
            f"reconnecting in {delay:.1f}s (attempt {self.reconnect_attempts})"
        )
        time.sleep(delay)
        
        if self.cap:
            self.cap.release()
            self.cap = None
    
    def generate_frames(self):
        """Générer les frames MJPEG pour le streaming"""
        last_yield_time = 0
        
        while True:
            current_time = time.time()
            
            if current_time - last_yield_time < self.frame_interval:
                time.sleep(self.frame_interval / 2)
                continue
            
            with self.frame_lock:
                if self.last_frame is not None:
                    frame = self.last_frame.copy()
                else:
                    frame = None
            
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    last_yield_time = current_time
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            else:
                time.sleep(0.1)
    
    def get_health_status(self) -> dict:
        """Obtenir le statut de santé du proxy"""
        return {
            "status": "ok",
            "court_id": self.court_id,
            "camera_url": self._mask_credentials(self.camera_url) if self.camera_url else None,
            "connected": self.cap is not None and self.cap.isOpened() if self.cap else False,
            "running": self.running
        }
    
    def _mask_credentials(self, url: Optional[str]) -> Optional[str]:
        """Masquer les identifiants dans l'URL"""
        if not url:
            return None
        
        pattern = r'(rtsp://|http://|https://)([^:]+):([^@]+)@'
        return re.sub(pattern, r'\1***:***@', url)
    
    async def shutdown(self):
        """Arrêter le serveur proxy"""
        await self._stop_capture()
        logger.info(f"[Court {self.court_id}] Proxy server shutdown")
