
import logging
import requests
import time
import cv2
from flask import Flask, Response
from threading import Thread, Event, Lock
import numpy as np

# Configuration
SESSION_ID = "sess_1_1_1764876481"
SOURCE_URL = "http://77.222.181.11:8080/mjpg/video.mjpg"
PORT = 8080

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - Video Proxy - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# Global state
current_frame = None
frame_lock = Lock()
frame_event = Event()
running = True
error_message = None

def is_mjpeg_stream(url: str) -> bool:
    """Détecter si c'est un flux MJPEG"""
    return 'mjpeg' in url.lower() or 'mjpg' in url.lower()

def is_rtsp_stream(url: str) -> bool:
    """Détecter si c'est un flux RTSP"""
    return url.startswith('rtsp://')

def capture_frames_mjpeg():
    """Capturer frames depuis source MJPEG"""
    global current_frame, running, error_message
    
    logger.info(f"📹 [MJPEG] Connecting to: {SOURCE_URL}")
    
    while running:
        try:
            response = requests.get(SOURCE_URL, stream=True, timeout=10)
            
            if response.status_code == 200:
                logger.info("✅ [MJPEG] Connected successfully")
                error_message = None
                
                bytes_buffer = b''
                for chunk in response.iter_content(chunk_size=1024):
                    if not running:
                        break
                    
                    bytes_buffer += chunk
                    
                    # Rechercher les marqueurs JPEG
                    a = bytes_buffer.find(b'\xff\xd8')  # Start of JPEG
                    b = bytes_buffer.find(b'\xff\xd9')  # End of JPEG
                    
                    if a != -1 and b != -1:
                        jpg = bytes_buffer[a:b+2]
                        bytes_buffer = bytes_buffer[b+2:]
                        
                        # Décoder et stocker la frame
                        frame_array = np.frombuffer(jpg, dtype=np.uint8)
                        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                        
                        if frame is not None:
                            with frame_lock:
                                current_frame = jpg  # Stocker JPEG brut
                                frame_event.set()
            else:
                error_message = f"HTTP {response.status_code}"
                logger.error(f"❌ [MJPEG] Error: {error_message}")
                time.sleep(5)
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"❌ [MJPEG] Connection error: {e}")
            time.sleep(5)

def capture_frames_rtsp():
    """Capturer frames depuis source RTSP via OpenCV"""
    global current_frame, running, error_message
    
    logger.info(f"📹 [RTSP] Connecting to: {SOURCE_URL}")
    
    while running:
        try:
            cap = cv2.VideoCapture(SOURCE_URL)
            
            if cap.isOpened():
                logger.info("✅ [RTSP] Connected successfully")
                error_message = None
                
                while running and cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        logger.warning("⚠️ [RTSP] Frame read failed")
                        break
                    
                    # Encoder la frame en JPEG
                    _, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    
                    with frame_lock:
                        current_frame = jpg.tobytes()
                        frame_event.set()
                        
            cap.release()
            
            if running:
                error_message = "RTSP connection lost"
                logger.error(f"❌ [RTSP] Connection lost, retrying...")
                time.sleep(5)
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"❌ [RTSP] Error: {e}")
            time.sleep(5)

def generate_mjpeg():
    """Générer le flux MJPEG pour les clients"""
    logger.info("🎥 New client connected")
    
    while running:
        # Attendre qu'une frame soit disponible
        frame_event.wait(timeout=1.0)
        
        with frame_lock:
            if current_frame is not None:
                frame_data = current_frame
                frame_event.clear()
            else:
                continue
        
        # Envoyer la frame au format MJPEG
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

@app.route('/stream.mjpg')
def video_feed():
    """Route principale du flux vidéo"""
    return Response(
        generate_mjpeg(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/health')
def health():
    """Endpoint de santé"""
    return {
        'status': 'ok' if current_frame is not None else 'no_frames',
        'session_id': SESSION_ID,
        'source_url': SOURCE_URL,
        'error': error_message
    }

if __name__ == '__main__':
    # Démarrer thread de capture selon le type de source
    if is_rtsp_stream(SOURCE_URL):
        capture_thread = Thread(target=capture_frames_rtsp, daemon=True)
    else:
        capture_thread = Thread(target=capture_frames_mjpeg, daemon=True)
    
    capture_thread.start()
    logger.info(f"✅ Capture thread started")
    
    # Démarrer serveur Flask avec Waitress (Windows-compatible)
    logger.info(f"🌐 Starting Flask server on http://127.0.0.1:{PORT}/stream.mjpg")
    
    try:
        from waitress import serve
        serve(app, host='127.0.0.1', port=PORT, threads=4)
    except ImportError:
        logger.error("❌ Waitress not installed! Install with: pip install waitress")
        logger.info("🔄 Falling back to Flask dev server...")
        app.run(host='127.0.0.1', port=PORT, threaded=True, debug=False)
