"""
Mini Serveur Proxy MJPEG Interne
=================================

Proxy léger pour flux MJPEG:
- Connexion source MJPEG
- Buffering frames
- Re-streaming local
- Reconnection automatique
"""

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def start_mjpeg_proxy_server(
    session_id: str,
    source_url: str,
    port: int
) -> subprocess.Popen:
    """
    Démarrer le serveur proxy MJPEG dans un subprocess
    
    Args:
        session_id: ID de la session
        source_url: URL MJPEG source
        port: Port HTTP local
        
    Returns:
        Processus du serveur
    """
    logger.info(f"🚀 Starting MJPEG proxy server on port {port}")
    
    # Script Python qui sera exécuté dans un subprocess
    script_content = f'''
import logging
import requests
import time
from flask import Flask, Response
from threading import Thread, Event

# Configuration
SESSION_ID = "{session_id}"
SOURCE_URL = "{source_url}"
PORT = {port}

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# Global state
current_frame = None
frame_lock = Event()
running = True

def capture_frames():
    """Capturer frames depuis la source MJPEG"""
    global current_frame, running
    
    logger.info(f"📹 Connecting to MJPEG source: {{SOURCE_URL}}")
    
    while running:
        try:
            response = requests.get(SOURCE_URL, stream=True, timeout=10)
            
            if response.status_code == 200:
                logger.info("✅ Connected to MJPEG source")
                
                # Lire le flux multipart
                boundary = None
                for line in response.iter_lines():
                    if not running:
                        break
                    
                    if line.startswith(b'--'):
                        boundary = line
                    elif line.startswith(b'Content-Type'):
                        pass
                    elif line.startswith(b'Content-Length'):
                        # Lire la longueur
                        length = int(line.split(b':')[1].strip())
                        # Skip ligne vide
                        next(response.iter_lines())
                        # Lire l'image
                        frame = response.raw.read(length)
                        current_frame = frame
                        frame_lock.set()
            else:
                logger.error(f"❌ HTTP error: {{response.status_code}}")
                time.sleep(5)
                
        except Exception as e:
            logger.error(f"❌ Error: {{e}}")
            time.sleep(5)
    
    logger.info("🛑 Capture thread stopped")

def generate_frames():
    """Générer frames pour les clients"""
    while True:
        # Attendre une frame
        frame_lock.wait(timeout=1)
        
        if current_frame:
            yield (b'--frame\\r\\n'
                   b'Content-Type: image/jpeg\\r\\n\\r\\n' + current_frame + b'\\r\\n')
        
        frame_lock.clear()

@app.route('/video')
def video_feed():
    """Endpoint vidéo MJPEG"""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/health')
def health():
    """Health check"""
    return {{'status': 'ok', 'session_id': SESSION_ID}}

if __name__ == '__main__':
    # Démarrer thread capture
    capture_thread = Thread(target=capture_frames, daemon=True)
    capture_thread.start()
    
    # Démarrer serveur Flask
    logger.info(f"🌐 MJPEG proxy listening on http://127.0.0.1:{{PORT}}/video")
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)
'''
    
    # Écrire le script temporaire (compatible Windows)
    temp_dir = Path(tempfile.gettempdir())
    script_path = temp_dir / f"mjpeg_proxy_{session_id}.py"
    script_path.write_text(script_content, encoding='utf-8')
    
    # Démarrer le subprocess
    try:
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        logger.info(f"✅ MJPEG proxy server started (PID: {process.pid})")
        return process
        
    except Exception as e:
        logger.error(f"❌ Failed to start MJPEG proxy: {e}")
        # Cleanup script temporaire en cas d'erreur
        if script_path.exists():
            try:
                script_path.unlink()
            except:
                pass
        raise
