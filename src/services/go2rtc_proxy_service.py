
"""
go2rtc_proxy_service.py
Service proxy vidéo inspiré de go2rtc (https://github.com/AlexxIT/go2rtc)
- Architecture fiable sans dépendances OpenCV/NumPy
- Support MJPEG, RTSP et H264 streaming
- Utilise FFmpeg directement pour la conversion et le proxy
- Compatible avec notre système d'enregistrement vidéo
"""

import asyncio
import logging
import signal
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional
import shutil

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Configuration pour le service proxy go2rtc"""
    source_url: str
    listen_port: int = 8080
    proxy_format: str = "mjpeg"  # mjpeg, rtsp, h264
    buffer_size: int = 1024 * 1024  # 1MB buffer
    timeout: float = 30.0
    ffmpeg_loglevel: str = "warning"
    reconnect_interval: float = 5.0


class Go2RTCProxyService:
    """
    Service proxy vidéo inspiré de go2rtc
    
    Fonctionnalités:
    - Proxy MJPEG stream fiable
    - Support conversion via FFmpeg
    - Endpoints API REST
    - Gestion automatique des reconnexions
    - Pas de dépendances OpenCV/NumPy
    """
    
    def __init__(self, config: ProxyConfig):
        self.config = config
        self._running = False
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._proxy_thread: Optional[threading.Thread] = None
        self._app = self._create_app()
        
        # État du proxy
        self._is_streaming = False
        self._stream_info = {
            "source": config.source_url,
            "status": "stopped",
            "clients": 0,
            "uptime": 0,
            "start_time": None
        }
    
    def _create_app(self) -> FastAPI:
        """Crée l'application FastAPI"""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            logger.info("Démarrage du service Go2RTC Proxy")
            yield
            # Shutdown
            logger.info("Arrêt du service Go2RTC Proxy")
            await self._cleanup()
        
        app = FastAPI(
            title="Go2RTC Proxy Service",
            description="Service proxy vidéo inspiré de go2rtc",
            version="1.0.0",
            lifespan=lifespan
        )
        
        # Health check endpoint
        @app.get("/health")
        async def health_check():
            return {
                "status": "ok" if self._running else "stopped",
                "service": "go2rtc-proxy",
                "streaming": self._is_streaming,
                "source": self.config.source_url,
                "port": self.config.listen_port
            }
        
        # Stream info endpoint
        @app.get("/api/info")
        async def stream_info():
            current_time = time.time()
            if self._stream_info["start_time"]:
                start_time = self._stream_info["start_time"]
                self._stream_info["uptime"] = current_time - start_time
            return self._stream_info
        
        # MJPEG stream endpoint - inspiré de go2rtc
        @app.get("/stream.mjpeg")
        async def mjpeg_stream():
            """Endpoint principal pour le stream MJPEG - compatible go2rtc"""
            if not self._is_streaming:
                await self.start_streaming()
            
            if not self._is_streaming:
                raise HTTPException(
                    status_code=503,
                    detail="Stream non disponible"
                )
            
            self._stream_info["clients"] += 1
            
            try:
                return StreamingResponse(
                    self._mjpeg_generator(),
                    media_type="multipart/x-mixed-replace; boundary=frame",
                    headers={
                        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                        "Connection": "close"
                    }
                )
            finally:
                self._stream_info["clients"] = max(0, self._stream_info["clients"] - 1)
        
        # H.264 stream endpoint
        @app.get("/stream.h264")
        async def h264_stream():
            """Stream H.264 raw pour FFmpeg"""
            if not self._is_streaming:
                await self.start_streaming()
                
            if not self._is_streaming:
                raise HTTPException(status_code=503, detail="Stream H264 non disponible")
            
            return StreamingResponse(
                self._h264_generator(),
                media_type="video/h264"
            )
        
        # Control endpoints
        @app.post("/api/start")
        async def start_stream():
            """Démarrer le streaming"""
            await self.start_streaming()
            return {"status": "started", "source": self.config.source_url}
        
        @app.post("/api/stop")
        async def stop_stream():
            """Arrêter le streaming"""
            await self.stop_streaming()
            return {"status": "stopped"}
        
        @app.post("/api/restart")
        async def restart_stream():
            """Redémarrer le streaming"""
            await self.stop_streaming()
            await asyncio.sleep(1)
            await self.start_streaming()
            return {"status": "restarted"}
        
        return app
    
    async def start_streaming(self):
        """Démarre le streaming via FFmpeg"""
        if self._is_streaming:
            logger.info("Stream déjà en cours")
            return
        
        logger.info(f"Démarrage du stream depuis: {self.config.source_url}")
        
        # Vérifier si FFmpeg est disponible
        if not shutil.which("ffmpeg"):
            logger.error("FFmpeg non trouvé dans le PATH")
            raise RuntimeError("FFmpeg non disponible")
        
        try:
            # Commande FFmpeg optimisée pour proxy MJPEG
            # Inspirée de l'architecture go2rtc
            ffmpeg_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", self.config.ffmpeg_loglevel,
                "-fflags", "+genpts",
                "-thread_queue_size", "1024",
                "-i", self.config.source_url,
                "-f", "mjpeg",
                "-q:v", "2",  # Haute qualité JPEG
                "-r", "25",   # 25 FPS
                "-"  # Output vers stdout
            ]
            
            logger.info(f"Commande FFmpeg: {' '.join(ffmpeg_cmd)}")
            
            # Démarrer le processus FFmpeg
            self._ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.config.buffer_size
            )
            
            # Attendre un peu pour vérifier que le processus démarre correctement
            await asyncio.sleep(2)
            
            if self._ffmpeg_process.poll() is not None:
                stderr = self._ffmpeg_process.stderr.read().decode() if self._ffmpeg_process.stderr else ""
                logger.error(f"FFmpeg a échoué: {stderr}")
                raise RuntimeError(f"Échec du démarrage FFmpeg: {stderr}")
            
            self._is_streaming = True
            self._stream_info.update({
                "status": "streaming",
                "start_time": time.time(),
                "clients": 0
            })
            
            logger.info("Stream démarré avec succès")
            
        except Exception as e:
            logger.error(f"Erreur lors du démarrage du stream: {e}")
            await self._cleanup_ffmpeg()
            raise
    
    async def stop_streaming(self):
        """Arrête le streaming"""
        logger.info("Arrêt du streaming...")
        self._is_streaming = False
        
        await self._cleanup_ffmpeg()
        
        self._stream_info.update({
            "status": "stopped",
            "clients": 0,
            "uptime": 0,
            "start_time": None
        })
        
        logger.info("Streaming arrêté")
    
    async def _cleanup_ffmpeg(self):
        """Nettoie les ressources FFmpeg"""
        if self._ffmpeg_process:
            try:
                # Terminer proprement
                self._ffmpeg_process.terminate()
                
                # Attendre un peu
                await asyncio.sleep(1)
                
                # Forcer l'arrêt si nécessaire
                if self._ffmpeg_process.poll() is None:
                    self._ffmpeg_process.kill()
                    await asyncio.sleep(1)
                
                self._ffmpeg_process = None
                logger.info("Processus FFmpeg nettoyé")
                
            except Exception as e:
                logger.error(f"Erreur lors du nettoyage FFmpeg: {e}")
    
    async def _mjpeg_generator(self):
        """
        Générateur MJPEG inspiré de go2rtc
        Lit les frames depuis FFmpeg et les stream en format MJPEG
        """
        boundary = "frame"
        
        if not self._ffmpeg_process or not self._ffmpeg_process.stdout:
            logger.error("Processus FFmpeg non disponible")
            return
        
        buffer = b""
        
        try:
            while self._is_streaming and self._ffmpeg_process.poll() is None:
                # Lire les données de FFmpeg
                chunk = self._ffmpeg_process.stdout.read(8192)
                
                if not chunk:
                    await asyncio.sleep(0.01)
                    continue
                
                buffer += chunk
                
                # Chercher les marqueurs JPEG (SOI: 0xFFD8, EOI: 0xFFD9)
                while True:
                    # Chercher le début d'une image JPEG
                    start_idx = buffer.find(b'\xff\xd8')
                    if start_idx == -1:
                        break
                    
                    # Chercher la fin de l'image JPEG
                    end_idx = buffer.find(b'\xff\xd9', start_idx)
                    if end_idx == -1:
                        break
                    
                    # Extraire l'image complète
                    jpeg_frame = buffer[start_idx:end_idx + 2]
                    
                    # Envoyer la frame au format MJPEG
                    if len(jpeg_frame) > 0:
                        yield (
                            f"--{boundary}\r\n"
                            "Content-Type: image/jpeg\r\n"
                            f"Content-Length: {len(jpeg_frame)}\r\n\r\n"
                        ).encode() + jpeg_frame + b"\r\n"
                    
                    # Supprimer la frame traitée du buffer
                    buffer = buffer[end_idx + 2:]
                
                # Éviter l'accumulation de données
                if len(buffer) > self.config.buffer_size:
                    logger.warning("Buffer overflow, reset")
                    buffer = b""
                
                await asyncio.sleep(0.001)  # Petit délai pour éviter la surcharge CPU
                
        except Exception as e:
            logger.error(f"Erreur dans le générateur MJPEG: {e}")
        finally:
            logger.info("Générateur MJPEG terminé")
    
    async def _h264_generator(self):
        """Générateur H.264 pour des besoins spécifiques"""
        # Pour une implémentation future si nécessaire
        # Pour l'instant, on utilise MJPEG qui est plus universel
        raise HTTPException(status_code=501, detail="H.264 streaming non implémenté")
    
    async def _cleanup(self):
        """Nettoyage général"""
        await self.stop_streaming()
    
    def run_server(self, setup_signals=True):
        """Lance le serveur proxy"""
        self._running = True
        
        logger.info(f"Démarrage du serveur Go2RTC Proxy sur le port {self.config.listen_port}")
        logger.info(f"Source: {self.config.source_url}")
        logger.info(f"Format: {self.config.proxy_format}")
        
        # Configuration uvicorn
        uvicorn_config = uvicorn.Config(
            app=self._app,
            host="0.0.0.0",
            port=self.config.listen_port,
            log_level="warning",  # Réduire les logs pour éviter le spam
            access_log=False
        )
        
        server = uvicorn.Server(uvicorn_config)
        
        # Gestion des signaux seulement si demandé (pas dans les threads)
        if setup_signals:
            try:
                def signal_handler(signum, frame):
                    logger.info(f"Signal {signum} reçu, arrêt du serveur...")
                    self._running = False
                    asyncio.create_task(self._cleanup())
                
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
            except Exception as e:
                logger.warning(f"Impossible de configurer les signaux: {e}")
        
        # Lancer le serveur
        try:
            server.run()
        except KeyboardInterrupt:
            logger.info("Arrêt par l'utilisateur")
        finally:
            self._running = False


def create_proxy_service(source_url: str, port: int = 8080, **kwargs) -> Go2RTCProxyService:
    """
    Factory pour créer un service proxy
    
    Args:
        source_url: URL de la source vidéo (RTSP, HTTP MJPEG, etc.)
        port: Port d'écoute du proxy
        **kwargs: Options supplémentaires pour ProxyConfig
    
    Returns:
        Instance du service proxy
    """
    config = ProxyConfig(
        source_url=source_url,
        listen_port=port,
        **kwargs
    )
    
    return Go2RTCProxyService(config)


# Script de test direct
if __name__ == "__main__":
    import argparse
    
    # Configuration des logs
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Arguments en ligne de commande
    parser = argparse.ArgumentParser(description="Go2RTC Proxy Service")
    parser.add_argument("--source", required=True, help="URL de la source vidéo")
    parser.add_argument("--port", type=int, default=8080, help="Port d'écoute")
    parser.add_argument("--format", default="mjpeg", choices=["mjpeg", "h264"], help="Format de proxy")
    parser.add_argument("--loglevel", default="info", choices=["debug", "info", "warning", "error"], help="Niveau de log")
    
    args = parser.parse_args()
    
    # Ajuster le niveau de log
    log_level = getattr(logging, args.loglevel.upper())
    logging.getLogger().setLevel(log_level)
    
    # Créer et lancer le service
    try:
        service = create_proxy_service(
            source_url=args.source,
            port=args.port,
            proxy_format=args.format
        )
        
        logger.info("=== Go2RTC Proxy Service ===")
        logger.info(f"Source: {args.source}")
        logger.info(f"Port: {args.port}")
        logger.info(f"Format: {args.format}")
        logger.info("Endpoints disponibles:")
        logger.info(f"  - Health: http://localhost:{args.port}/health")
        logger.info(f"  - Info: http://localhost:{args.port}/api/info")
        logger.info(f"  - MJPEG Stream: http://localhost:{args.port}/stream.mjpeg")
        logger.info(f"  - Start: POST http://localhost:{args.port}/api/start")
        logger.info(f"  - Stop: POST http://localhost:{args.port}/api/stop")
        logger.info("===========================")
        
        service.run_server()
        
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")
        exit(1)