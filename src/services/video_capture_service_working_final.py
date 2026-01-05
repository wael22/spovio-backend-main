import subprocess
import threading
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DirectVideoCaptureServiceWorking:
    """Service vidéo final qui MARCHE - sans redirection DEVNULL"""
    
    def __init__(self):
        self.ffmpeg_path = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
        self.camera_url = "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi"
        self.recording = False
        self.process = None
        self.start_time = None
        
    def start_recording(self, filename, duration=300):
        """Démarrer l'enregistrement SANS redirection streams"""
        
        if self.recording:
            logger.warning("⚠️ Enregistrement déjà en cours")
            return False
            
        try:
            # Supprimer fichier existant
            if Path(filename).exists():
                Path(filename).unlink()
            
            # Configuration FFmpeg simple
            cmd = [
                self.ffmpeg_path,
                "-y",
                "-i", self.camera_url,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-t", str(duration),
                filename
            ]
            
            logger.info(f"🚀 Démarrage enregistrement: {filename}")
            logger.info(f"📝 Commande: {' '.join(cmd)}")
            
            # Lancer SANS redirection pour que ça marche !
            self.process = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NO_WINDOW
                # PAS DE REDIRECTION !
            )
            
            self.recording = True
            self.start_time = time.time()
            
            logger.info(f"✅ Enregistrement démarré - PID: {self.process.pid}")
            
            # Thread de surveillance
            def monitor_recording():
                try:
                    self.process.wait(timeout=duration + 30)
                    logger.info("✅ Enregistrement terminé naturellement")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ Timeout - arrêt forcé")
                    self.process.kill()
                    self.process.wait()
                finally:
                    self.recording = False
                    self.process = None
                    self.start_time = None
            
            threading.Thread(target=monitor_recording, daemon=True).start()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage: {e}")
            self.recording = False
            self.process = None
            self.start_time = None
            return False
    
    def stop_recording(self):
        """Arrêter l'enregistrement"""
        
        if not self.recording or not self.process:
            logger.warning("⚠️ Aucun enregistrement en cours")
            return True
            
        try:
            logger.info("🛑 Arrêt enregistrement...")
            self.process.terminate()
            
            try:
                self.process.wait(timeout=5)
                logger.info("✅ Processus arrêté proprement")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ Arrêt forcé")
                self.process.kill()
                self.process.wait()
            
            self.recording = False
            self.process = None
            self.start_time = None
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt: {e}")
            return False
    
    def is_recording(self):
        """Vérifier si enregistrement en cours"""
        return self.recording and self.process is not None
    
    def get_recording_duration(self):
        """Obtenir la durée d'enregistrement actuelle"""
        if not self.is_recording() or not self.start_time:
            return 0
        return int(time.time() - self.start_time)
    
    def get_status(self):
        """Obtenir le statut complet"""
        return {
            "recording": self.is_recording(),
            "pid": self.process.pid if self.process else None,
            "duration": self.get_recording_duration(),
            "start_time": self.start_time
        }
