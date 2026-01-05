"""
Multi-Terrain MJPEG Relay Server for Padelvar
Uses OpenCV to read from cameras and Flask to serve MJPEG streams

Each terrain has:
- Dedicated reader thread
- Frame buffer (default 120 frames)
- HTTP endpoint: http://localhost:8000/video/<terain_id>
- Automatic reconnection on camera failure
"""

import threading
import time
import os
from collections import deque
from pathlib import Path

from flask import Flask, Response, jsonify, abort
import cv2
import yaml
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("multi_relay")

app = Flask(__name__)


class TerrainRelay:
    """
    Relay vidéo pour un terrain
    Lit frames depuis caméra avec OpenCV et maintient un buffer
    """
    
    def __init__(self, terrain_id, name, source_url, buffer_frames=120):
        self.terrain_id = terrain_id
        self.name = name
        self.source_url = source_url
        self.buffer_frames = buffer_frames
        
        # Buffer circulaire de frames
        self.buffer = deque(maxlen=buffer_frames)
        
        # Threading
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        
        # Stats
        self.last_frame_time = None
        self.frames_received = 0
        self.reconnections = 0
        self.is_connected = False
    
    def start(self):
        """Démarre le thread de lecture"""
        log.info(f"🎥 Starting relay '{self.name}' from {self.source_url}")
        self.thread.start()
    
    def stop(self):
        """Arrête le thread de lecture"""
        log.info(f"🛑 Stopping relay '{self.name}'")
        self._stop.set()
    
    def _reader(self):
        """
        Thread principal de lecture des frames
        Gère la reconnexion automatique
        """
        cap = None
        
        while not self._stop.is_set():
            try:
                # Ouvrir ou réouvrir la caméra
                if cap is None or not cap.isOpened():
                    log.info(f"🔌 Connecting to {self.name}...")
                    cap = cv2.VideoCapture(self.source_url)
                    
                    if not cap.isOpened():
                        log.warning(f"⚠️ Failed to open {self.name}, retrying in 2s")
                        time.sleep(2)
                        continue
                    
                    self.is_connected = True
                    self.reconnections += 1
                    log.info(f"✅ {self.name} connected (attempt #{self.reconnections})")
                    time.sleep(0.5)  # Stabilisation
                
                # Lire une frame
                ok, frame = cap.read()
                
                if not ok:
                    log.warning(f"❌ {self.name}: Failed to read frame, reconnecting...")
                    self.is_connected = False
                    
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                    
                    time.sleep(1)
                    continue
                
                # Frame OK - ajouter au buffer
                self.buffer.append(frame)
                self.frames_received += 1
                self.last_frame_time = time.time()
                
            except Exception as e:
                log.exception(f"❌ {self.name}: Reader exception: {e}")
                self.is_connected = False
                time.sleep(1)
        
        # Nettoyage
        if cap:
            try:
                cap.release()
            except Exception:
                pass
        
        log.info(f"🏁 {self.name}: Reader stopped")
    
    def generate_mjpeg(self):
        """
        Générateur MJPEG pour Flask Response
        Yields: bytes pour stream multipart/x-mixed-replace
        """
        while True:
            # Attendre qu'il y ait des frames
            if len(self.buffer) == 0:
                time.sleep(0.05)
                continue
            
            # Prendre la dernière frame du buffer
            frame = self.buffer[-1]
            
            # Encoder en JPEG
            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                continue
            
            data = jpeg.tobytes()
            
            # Format MJPEG
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
    
    def get_stats(self):
        """Retourne les stats du relay"""
        uptime = None
        if self.last_frame_time:
            uptime = time.time() - self.last_frame_time
        
        return {
            'terrain_id': self.terrain_id,
            'name': self.name,
            'source': self.source_url,
            'connected': self.is_connected,
            'frames_received': self.frames_received,
            'reconnections': self.reconnections,
            'buffer_size': len(self.buffer),
            'buffer_max': self.buffer_frames,
            'last_frame_seconds_ago': uptime
        }


class RelayManager:
    """
    Gestionnaire de tous les relays
    Charge la config et gère les relays multiples
    """
    
    def __init__(self, config_path):
        self.relays = {}
        self.config_path = config_path
        log.info(f"📋 RelayManager initialized with config: {config_path}")
    
    def load_and_start(self):
        """Charge config YAML et démarre tous les relays"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        
        log.info(f"📂 Loading config from {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        
        proxies = cfg.get('proxies', [])
        log.info(f"📡 Found {len(proxies)} terrain(s) in config")
        
        for entry in proxies:
            tid = int(entry['terrain_id'])
            name = entry.get('name', f'Terrain {tid}')
            src = entry['source_url']
            buf = int(entry.get('buffer_frames', 120))
            
            relay = TerrainRelay(
                terrain_id=tid,
                name=name,
                source_url=src,
                buffer_frames=buf
            )
            
            self.relays[tid] = relay
            relay.start()
            
            log.info(f"✅ Relay {tid} started: {name} → http://localhost:8000/video/{tid}")
        
        log.info(f"🎉 All {len(self.relays)} relay(s) started successfully")
    
    def get_relay(self, terrain_id):
        """Retourne un relay par son ID"""
        return self.relays.get(int(terrain_id))
    
    def get_all_stats(self):
        """Retourne stats de tous les relays"""
        return {
            tid: relay.get_stats()
            for tid, relay in self.relays.items()
        }
    
    def stop_all(self):
        """Arrête tous les relays"""
        log.info("🛑 Stopping all relays...")
        for relay in self.relays.values():
            relay.stop()
        log.info("✅ All relays stopped")


# Instance globale du manager
BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'proxies.yaml'
relay_manager = RelayManager(str(CONFIG_PATH))


# === Routes Flask ===

@app.route('/')
def index():
    """Page d'accueil avec liste des terrains"""
    stats = relay_manager.get_all_stats()
    
    html = """
    <html>
    <head><title>Padelvar Multi-Relay Server</title></head>
    <body>
        <h1>🎾 Padelvar Multi-Terrain MJPEG Relay</h1>
        <h2>Terrains disponibles:</h2>
        <ul>
    """
    
    for tid, stat in stats.items():
        status = "🟢 Connected" if stat['connected'] else "🔴 Disconnected"
        html += f"""
        <li>
            <strong>{stat['name']}</strong> ({status})<br>
            Stream: <a href="/video/{tid}">http://localhost:8000/video/{tid}</a><br>
            Frames: {stat['frames_received']}, Buffer: {stat['buffer_size']}/{stat['buffer_max']}
        </li>
        """
    
    html += """
        </ul>
        <h2>API:</h2>
        <ul>
            <li><a href="/api/stats">Stats JSON</a></li>
        </ul>
    </body>
    </html>
    """
    
    return html


@app.route('/video/<int:terrain_id>')
def video_feed(terrain_id):
    """Stream MJPEG pour un terrain"""
    relay = relay_manager.get_relay(terrain_id)
    
    if not relay:
        return abort(404, description=f'Terrain {terrain_id} not found')
    
    return Response(
        relay.generate_mjpeg(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/stats')
def api_stats():
    """API JSON avec stats de tous les relays"""
    return jsonify(relay_manager.get_all_stats())


@app.route('/api/stats/<int:terrain_id>')
def api_terrain_stats(terrain_id):
    """Stats d'un terrain spécifique"""
    relay = relay_manager.get_relay(terrain_id)
    
    if not relay:
        return abort(404, description=f'Terrain {terrain_id} not found')
    
    return jsonify(relay.get_stats())


if __name__ == '__main__':
    try:
        log.info("=" * 60)
        log.info("🎾 Padelvar Multi-Terrain MJPEG Relay Server")
        log.info("=" * 60)
        
        # Charger et démarrer tous les relays
        relay_manager.load_and_start()
        
        log.info("")
        log.info("🌐 Flask server starting on http://0.0.0.0:8000")
        log.info("📺 View streams:")
        for tid in relay_manager.relays.keys():
            log.info(f"   - Terrain {tid}: http://localhost:8000/video/{tid}")
        log.info("")
        log.info("Press Ctrl+C to stop")
        log.info("=" * 60)
        
        # Démarrer Flask
        app.run(
            host='0.0.0.0',
            port=8000,
            threaded=True,
            debug=False
        )
        
    except KeyboardInterrupt:
        log.info("\n🛑 Shutting down...")
        relay_manager.stop_all()
        log.info("✅ Server stopped")
    except Exception as e:
        log.exception(f"❌ Fatal error: {e}")
        relay_manager.stop_all()
        raise
