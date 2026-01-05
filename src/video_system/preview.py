"""
Preview Manager - WebSocket Video Streaming
===========================================

Responsabilités:
- Capturer frames depuis le proxy local
- Encoder en JPEG
- Streamer via WebSocket
- Gérer multiple viewers simultanés
- Reconnection automatique
"""

import logging
import time
import requests
import asyncio
from typing import Optional, Set
import io
from PIL import Image

logger = logging.getLogger(__name__)


class PreviewManager:
    """Gestionnaire de preview vidéo WebSocket"""
    
    def __init__(self):
        self.active_previews = {}  # session_id -> set(websockets)
        logger.info("👁️ PreviewManager initialisé")
    
    def add_viewer(self, session_id: str, websocket):
        """
        Ajouter un viewer à une session
        
        Args:
            session_id: ID de la session
            websocket: WebSocket du client
        """
        if session_id not in self.active_previews:
            self.active_previews[session_id] = set()
        
        self.active_previews[session_id].add(websocket)
        logger.info(f"👁️ Viewer ajouté à session {session_id} ({len(self.active_previews[session_id])} viewers)")
    
    def remove_viewer(self, session_id: str, websocket):
        """
        Retirer un viewer d'une session
        
        Args:
            session_id: ID de la session
            websocket: WebSocket du client
        """
        if session_id in self.active_previews:
            self.active_previews[session_id].discard(websocket)
            
            # Nettoyer si plus de viewers
            if len(self.active_previews[session_id]) == 0:
                del self.active_previews[session_id]
                logger.info(f"🧹 Plus de viewers pour session {session_id}")
    
    def get_viewer_count(self, session_id: str) -> int:
        """Obtenir le nombre de viewers pour une session"""
        return len(self.active_previews.get(session_id, set()))
    
    async def stream_preview(self, session_id: str, local_url: str, websocket):
        """
        Streamer la preview via WebSocket
        
        Args:
            session_id: ID de la session
            local_url: URL du proxy local
            websocket: WebSocket du client
        """
        logger.info(f"📡 Démarrage stream preview pour {session_id}")
        
        # Construire l'URL du snapshot
        snapshot_url = local_url.replace('/stream.mjpg', '/snapshot.jpg')
        
        try:
            while True:
                try:
                    # Récupérer une frame depuis le proxy
                    response = requests.get(snapshot_url, timeout=2)
                    
                    if response.status_code == 200:
                        # Envoyer l'image JPEG au client
                        await websocket.send_bytes(response.content)
                    else:
                        logger.warning(f"⚠️ HTTP {response.status_code} pour snapshot")
                        await asyncio.sleep(1)
                        continue
                    
                except requests.exceptions.RequestException as e:
                    logger.error(f"❌ Erreur récupération frame: {e}")
                    await asyncio.sleep(1)
                    continue
                
                # FPS du preview (configurable)
                await asyncio.sleep(1.0 / 5)  # 5 FPS
                
        except Exception as e:
            logger.error(f"❌ Erreur stream preview: {e}")
        finally:
            self.remove_viewer(session_id, websocket)
            logger.info(f"🛑 Stream preview arrêté pour {session_id}")


# Instance globale (singleton)
preview_manager = PreviewManager()
