import asyncio
import logging
import multiprocessing
import uvicorn
from typing import Dict, Optional
from services.video_proxy_server import VideoProxyServer
from config import settings

logger = logging.getLogger("video")

class ProxyManager:
    def __init__(self):
        self.proxies: Dict[int, dict] = {}
        self.base_port = settings.PROXY_BASE_PORT
        self.max_courts = settings.MAX_COURTS
    
    async def start_proxy(self, court_id: int, camera_url: Optional[str] = None) -> int:
        if court_id in self.proxies and self.proxies[court_id].get("process"):
            if self.proxies[court_id]["process"].is_alive():
                logger.info(f"Proxy for court {court_id} already running")
                if camera_url:
                    await self.set_camera_url(court_id, camera_url)
                return self.proxies[court_id]["port"]
        
        if court_id < 1 or court_id > self.max_courts:
            raise ValueError(f"Court ID must be between 1 and {self.max_courts}")
        
        port = self.base_port + (court_id - 1)
        
        process = multiprocessing.Process(
            target=self._run_proxy,
            args=(court_id, port, camera_url),
            daemon=True
        )
        process.start()
        
        self.proxies[court_id] = {
            "port": port,
            "process": process,
            "camera_url": camera_url
        }
        
        await asyncio.sleep(1.0)
        
        logger.info(f"Started proxy for court {court_id} on port {port}")
        return port
    
    @staticmethod
    def _run_proxy(court_id: int, port: int, camera_url: Optional[str]):
        import asyncio
        
        async def run():
            proxy = VideoProxyServer(port, court_id)
            
            if camera_url:
                await proxy._set_camera_url(camera_url)
            
            config = uvicorn.Config(
                proxy.app,
                host="0.0.0.0",
                port=port,
                log_level="info",
                access_log=False
            )
            server = uvicorn.Server(config)
            await server.serve()
        
        asyncio.run(run())
    
    async def stop_proxy(self, court_id: int):
        if court_id not in self.proxies:
            logger.warning(f"No proxy found for court {court_id}")
            return
        
        process = self.proxies[court_id].get("process")
        if process and process.is_alive():
            process.terminate()
            process.join(timeout=5.0)
            if process.is_alive():
                process.kill()
            logger.info(f"Stopped proxy for court {court_id}")
        
        del self.proxies[court_id]
    
    async def set_camera_url(self, court_id: int, camera_url: str):
        if court_id not in self.proxies:
            await self.start_proxy(court_id, camera_url)
            return
        
        port = self.proxies[court_id]["port"]
        self.proxies[court_id]["camera_url"] = camera_url
        
        import httpx
        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"http://localhost:{port}/set_camera",
                    params={"url": camera_url},
                    timeout=5.0
                )
                logger.info(f"Updated camera URL for court {court_id}")
            except Exception as e:
                logger.error(f"Failed to update camera URL for court {court_id}: {e}")
                raise
    
    def get_proxy_port(self, court_id: int) -> Optional[int]:
        if court_id in self.proxies:
            return self.proxies[court_id]["port"]
        return None
    
    def get_stream_url(self, court_id: int) -> str:
        port = self.get_proxy_port(court_id)
        if port is None:
            port = self.base_port + (court_id - 1)
        
        return f"{settings.HOST_PUBLIC_BASE_URL}:{port}/stream.mjpg"
    
    async def is_proxy_healthy(self, court_id: int) -> bool:
        if court_id not in self.proxies:
            return False
        
        port = self.proxies[court_id]["port"]
        
        import httpx
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"http://localhost:{port}/health",
                    timeout=2.0
                )
                return response.status_code == 200
            except Exception:
                return False
    
    async def shutdown_all(self):
        logger.info("Shutting down all proxies")
        court_ids = list(self.proxies.keys())
        for court_id in court_ids:
            await self.stop_proxy(court_id)

proxy_manager = ProxyManager()
