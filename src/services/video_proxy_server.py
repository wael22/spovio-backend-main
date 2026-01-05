import asyncio
import cv2
import logging
import time
from typing import Optional
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
import threading
from urllib.parse import urlparse
import re

logger = logging.getLogger("video")

class VideoProxyServer:
    def __init__(self, port: int, court_id: int):
        self.port = port
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
        
        self.app = FastAPI()
        self._setup_routes()
    
    def _setup_routes(self):
        @self.app.get("/health")
        async def health():
            return {
                "status": "ok",
                "court_id": self.court_id,
                "camera_url": self._mask_credentials(self.camera_url) if self.camera_url else None,
                "connected": self.cap is not None and self.cap.isOpened() if self.cap else False,
                "running": self.running
            }
        
        @self.app.post("/set_camera")
        async def set_camera(url: str):
            logger.info(f"[Court {self.court_id}] Setting camera URL: {self._mask_credentials(url)}")
            await self._set_camera_url(url)
            return {
                "status": "ok",
                "camera_url": self._mask_credentials(url),
                "court_id": self.court_id
            }
        
        @self.app.get("/stream.mjpg")
        async def stream():
            if not self.camera_url:
                return Response(
                    content="No camera configured",
                    status_code=503,
                    media_type="text/plain"
                )
            
            return StreamingResponse(
                self._generate_frames(),
                media_type="multipart/x-mixed-replace; boundary=frame"
            )
    
    async def _set_camera_url(self, url: str):
        self.camera_url = url
        if self.running:
            await self._restart_capture()
        else:
            await self._start_capture()
    
    async def _start_capture(self):
        if self.running:
            return
        
        self.running = True
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()
        logger.info(f"[Court {self.court_id}] Capture started")
    
    async def _restart_capture(self):
        logger.info(f"[Court {self.court_id}] Restarting capture")
        await self._stop_capture()
        await asyncio.sleep(0.5)
        await self._start_capture()
    
    async def _stop_capture(self):
        self.running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info(f"[Court {self.court_id}] Capture stopped")
    
    def _capture_loop(self):
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
    
    async def _generate_frames(self):
        last_yield_time = 0
        
        while True:
            current_time = time.time()
            
            if current_time - last_yield_time < self.frame_interval:
                await asyncio.sleep(self.frame_interval / 2)
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
                await asyncio.sleep(0.1)
    
    def _mask_credentials(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        
        pattern = r'(rtsp://|http://|https://)([^:]+):([^@]+)@'
        return re.sub(pattern, r'\1***:***@', url)
    
    async def shutdown(self):
        await self._stop_capture()
        logger.info(f"[Court {self.court_id}] Proxy server shutdown")
