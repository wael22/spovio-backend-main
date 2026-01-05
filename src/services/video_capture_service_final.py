import subprocess
import threading
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DirectVideoCaptureService:
    """Service de capture vidéo fonctionnel - Version finale qui marche"""
    
    def __init__(self):
        # Configuration FFmpeg
        self.ffmpeg_path = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
        
        # URL correcte de la caméra
        self.camera_url = "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi"
        
        # État du service
        self.recording = False
        self.process = None
        self.start_time = None
        
    def start_recording(self, filename, duration=300):
        """Démarrer l'enregistrement avec durée spécifiée"""
        
        if self.recording:
            logger.warning("⚠️ Enregistrement déjà en cours")
            return False
            
        try:
            # Supprimer fichier existant si présent
            if Path(filename).exists():
                Path(filename).unlink()
                logger.info(f"🗑️ Ancien fichier supprimé: {filename}")
            
            # Configuration FFmpeg optimisée
            cmd = [
                self.ffmpeg_path,
                "-y",  # Écraser sans demander
                "-f", "mjpeg",  # Forcer le format MJPEG
                "-i", self.camera_url,
                "-c:v", "libx264",  # Codec H.264
                "-preset", "ultrafast",  # Vitesse maximale
                "-crf", "28",  # Qualité raisonnable
                "-t", str(duration),  # Durée en secondes
                "-avoid_negative_ts", "make_zero",  # Fix timestamps
                "-fflags", "+genpts",  # Générer timestamps
                filename
            ]
            
            logger.info(f"🚀 Démarrage enregistrement: {filename}")
            logger.info(f"⏱️ Durée: {duration}s")
            logger.info(f"📝 Commande: {' '.join(cmd)}")
            
            # Lancer le processus FFmpeg
            self.process = subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NO_WINDOW
                # Pas de redirection pour permettre l'écriture
            )
            
            self.recording = True
            self.start_time = time.time()
            
            logger.info(f"✅ Enregistrement démarré - PID: {self.process.pid}")
            
            # Thread de surveillance pour arrêt automatique
            def monitor_recording():
                try:
                    # Attendre la fin naturelle avec marge
                    self.process.wait(timeout=duration + 30)
                    logger.info("✅ Enregistrement terminé naturellement")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ Timeout dépassé - arrêt forcé")
                    self.process.kill()
                    self.process.wait()
                finally:
                    self.recording = False
                    self.process = None
                    self.start_time = None
                    
                    # Vérifier le fichier final
                    if Path(filename).exists():
                        size = Path(filename).stat().st_size
                        logger.info(f"📁 Fichier final: {size:,} bytes")
                    else:
                        logger.error("❌ Fichier final non créé")
            
            # Lancer la surveillance en arrière-plan
            threading.Thread(target=monitor_recording, daemon=True).start()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage enregistrement: {e}")
            self.recording = False
            self.process = None
            self.start_time = None
            return False
    
    def stop_recording(self):
        """Arrêter l'enregistrement en cours"""
        
        if not self.recording or not self.process:
            logger.warning("⚠️ Aucun enregistrement en cours")
            return True
            
        try:
            logger.info("🛑 Arrêt de l'enregistrement...")
            
            # Arrêt propre avec SIGTERM
            self.process.terminate()
            
            # Attendre un arrêt propre
            try:
                self.process.wait(timeout=5)
                logger.info("✅ Processus arrêté proprement")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ Arrêt forcé nécessaire")
                self.process.kill()
                self.process.wait()
            
            # Nettoyer l'état
            self.recording = False
            self.process = None
            self.start_time = None
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt enregistrement: {e}")
            return False
    
    def is_recording(self):
        """Vérifier si un enregistrement est en cours"""
        return self.recording and self.process is not None
    
    def get_recording_duration(self):
        """Obtenir la durée d'enregistrement actuelle"""
        if not self.is_recording() or not self.start_time:
            return 0
        return int(time.time() - self.start_time)
    
    def get_status(self):
        """Obtenir le statut complet du service"""
        return {
            "recording": self.is_recording(),
            "pid": self.process.pid if self.process else None,
            "duration": self.get_recording_duration(),
            "start_time": self.start_time
        }
    
    def _get_video_duration(self, filename):
        """Obtenir la durée d'une vidéo avec FFprobe"""
        try:
            ffprobe_path = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffprobe.exe"
            
            cmd = [
                ffprobe_path,
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                filename
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                duration = float(result.stdout.strip())
                logger.info(f"📏 Durée vidéo: {duration:.2f}s")
                return duration
            else:
                logger.warning(f"⚠️ Impossible de lire la durée: {result.stderr}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Erreur lecture durée: {e}")
            return None
