# video_proxy_server.py
# Python 3.10+
# Dépendances: fastapi, uvicorn, opencv-python, numpy
# Installation: pip install fastapi uvicorn opencv-python numpy

import argparse
import logging
import signal
import sys
import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn


@dataclass
class ProxyConfig:
    source: str
    fps: int = 25
    buffer_size: int = 50  # frames (encoded JPEG)
    jpeg_quality: int = 80
    reconnect_interval: float = 5.0  # seconds


class VideoProxy:
    def __init__(self, config: ProxyConfig):
        self.cfg = config

        # Shared state
        self._buffer: Deque[bytes] = deque(maxlen=self.cfg.buffer_size)
        self._latest_jpeg: Optional[bytes] = None
        self._latest_raw: Optional[np.ndarray] = None
        self._latest_shape: Optional[Tuple[int, int]] = None  # (H, W)
        self._running = threading.Event()
        self._running.set()

        self._lock = threading.Lock()
        self._cap: Optional[cv2.VideoCapture] = None
        self._capture_thread = threading.Thread(target=self._capture_loop, name="capture", daemon=True)

    def start(self):
        logging.info("Démarrage du thread de capture…")
        self._capture_thread.start()

    def stop(self):
        logging.info("Arrêt du proxy vidéo…")
        self._running.clear()
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        logging.info(f"Connexion à la source: {self.cfg.source}")
        cap = cv2.VideoCapture(self.cfg.source, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            logging.warning("Impossible d'ouvrir la source vidéo.")
            return None
        try:
            # Certaines plateformes ignorent ce paramètre mais ça vaut la peine d'essayer.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        except Exception:
            pass
        logging.info("Source vidéo connectée.")
        return cap

    def _encode_jpeg(self, frame: np.ndarray) -> Optional[bytes]:
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(self.cfg.jpeg_quality)])
            if not ok:
                return None
            return buf.tobytes()
        except Exception as e:
            logging.error(f"Erreur encodage JPEG: {e}")
            return None

    def _capture_loop(self):
        # Placeholder noir tant que pas d'image
        self._latest_jpeg = self._black_jpeg(640, 480)
        self._latest_shape = (480, 640)

        while self._running.is_set():
            # Assurer cap ouvert
            if self._cap is None or not self._cap.isOpened():
                self._cap = self._open_capture()
                if self._cap is None:
                    time.sleep(self.cfg.reconnect_interval)
                    continue

            # Lire une image
            ret, frame = self._cap.read()
            if not ret or frame is None:
                logging.warning("Perte du flux. Tentative de reconnexion dans 5s…")
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
                time.sleep(self.cfg.reconnect_interval)
                continue

            # Mettre à jour état partagé
            h, w = frame.shape[:2]
            jpeg = self._encode_jpeg(frame)
            if jpeg is None:
                continue

            with self._lock:
                self._latest_raw = frame
                self._latest_shape = (h, w)
                self._latest_jpeg = jpeg
                self._buffer.append(jpeg)

        logging.info("Capture loop arrêtée.")

    def _black_jpeg(self, w: int, h: int) -> bytes:
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else b""

    def get_latest_jpeg(self) -> bytes:
        with self._lock:
            if self._latest_jpeg is not None:
                return self._latest_jpeg
        # Fallback
        return self._black_jpeg(640, 480)

    def get_latest_raw(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int]]]:
        with self._lock:
            if self._latest_raw is None:
                return None, self._latest_shape
            return self._latest_raw.copy(), self._latest_shape

    def mjpeg_generator(self, fps: Optional[int] = None):
        boundary = "frame"
        interval = 1.0 / float(fps or self.cfg.fps)
        next_t = time.perf_counter()
        while True:
            # Rythmer à FPS fixe
            now = time.perf_counter()
            if now < next_t:
                time.sleep(next_t - now)
            next_t += interval

            jpeg = self.get_latest_jpeg()
            yield (
                b"--" + boundary.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                + jpeg
                + b"\r\n"
            )


def build_app(proxy: VideoProxy, fps: int) -> FastAPI:
    app = FastAPI(title="Video Proxy Server", version="1.0.0")

    @app.get("/stream.mjpg")
    def stream_mjpg():
        boundary = "frame"
        return StreamingResponse(
            proxy.mjpeg_generator(fps=fps),
            media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "fps": fps}

    return app


def parse_args():
    p = argparse.ArgumentParser(description="Serveur proxy vidéo MJPEG (FastAPI + uvicorn + OpenCV).")
    p.add_argument("--source", required=True, help="URL caméra (ex: http://.../mjpg/video.mjpg)")
    p.add_argument("--port", type=int, default=8080, help="Port HTTP local (par défaut 8080)")
    p.add_argument("--fps", type=int, default=25, help="Fréquence d'images de sortie (par défaut 25)")
    p.add_argument("--buffer", type=int, default=50, help="Taille du tampon circulaire (frames JPEG)")
    p.add_argument("--quality", type=int, default=80, help="Qualité JPEG (0-100, par défaut 80)")
    return p.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = ProxyConfig(
        source=args.source,
        fps=args.fps,
        buffer_size=args.buffer,
        jpeg_quality=args.quality,
    )
    proxy = VideoProxy(cfg)
    proxy.start()

    app = build_app(proxy, fps=cfg.fps)

    def shutdown(signum, frame):
        logging.info("Signal reçu, arrêt…")
        proxy.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logging.info(f"Proxy server started on http://127.0.0.1:{args.port}/stream.mjpg")

    uvicorn.run(app, host="127.0.0.1", port=int(args.port), log_level="info")


if __name__ == "__main__":
    main()
