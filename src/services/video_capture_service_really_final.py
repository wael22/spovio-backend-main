import subprocess
import shutil
import threading
import time
import logging
from pathlib import Path
import psutil
import os

logger = logging.getLogger(__name__)


class DirectVideoCaptureServiceFinal:
    """Service vidéo final - Version avec réinitialisation forcée"""
    
    def __init__(self):
        # Support dynamique pour Windows (Dev) et Linux (Prod/Docker)
        self.ffmpeg_path = os.getenv('FFMPEG_PATH')
        if not self.ffmpeg_path:
            self.ffmpeg_path = shutil.which('ffmpeg')
        
        if not self.ffmpeg_path:
            # Fallback pour le dev local si shutil ne trouve rien mais que le chemin est connu
            possible_paths = [
                r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe",
                "ffmpeg"
            ]
            for path in possible_paths:
                if Path(path).exists() or path == "ffmpeg":
                    self.ffmpeg_path = path
                    break
        
        logger.info(f"🎥 FFmpeg Path configuré: {self.ffmpeg_path}")
        self.camera_url = "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi"
        self.reset_state()
        
    def reset_state(self):
        """Réinitialisation complète de l'état du service"""
        self.recording = False
        self.process = None
        self.start_time = None
        self.current_session_id = None
        self.current_output_path = None
        logger.info("🔄 État du service réinitialisé")
        
    def force_cleanup(self):
        """Nettoyage forcé des processus FFmpeg orphelins"""
        try:
            cleaned_count = 0
            for process in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'ffmpeg' in process.info['name'].lower():
                        cmdline = ' '.join(process.info['cmdline']) if process.info['cmdline'] else ''
                        if 'mjpg' in cmdline or 'video.cgi' in cmdline:
                            logger.warning(f"🧹 Nettoyage processus FFmpeg orphelin PID {process.info['pid']}")
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except psutil.TimeoutExpired:
                                process.kill()
                            cleaned_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if cleaned_count > 0:
                logger.info(f"✅ {cleaned_count} processus FFmpeg nettoyés")
                
        except Exception as e:
            logger.error(f"❌ Erreur nettoyage forcé: {e}")
        
        # Forcer la réinitialisation de l'état
        self.reset_state()
        
    def start_recording(self, session_id, camera_url, output_path, max_duration, user_id, court_id, session_name, video_quality="medium"):
        """Démarrer enregistrement - Version avec nettoyage automatique"""
        
        # Nettoyage préventif au démarrage
        if self.recording:
            logger.warning("⚠️ Service bloqué - nettoyage forcé")
            self.force_cleanup()
            
        try:
            # Supprimer fichier existant
            if Path(output_path).exists():
                Path(output_path).unlink()
                logger.info(f"🗑️ Ancien fichier supprimé: {output_path}")
            
            # Créer le dossier parent si nécessaire
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Convertir max_duration en secondes
            duration_seconds = max_duration if max_duration else 300
            
            # Commande FFmpeg optimisée
            cmd = [
                self.ffmpeg_path,
                "-y",  # Overwrite output
                "-f", "mjpeg",
                "-timeout", "10000000",  # 10 secondes timeout
                "-i", camera_url,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "28",
                "-profile:v", "baseline",  # Compatibilité maximale
                "-level", "3.0",
                "-movflags", "+faststart",  # Optimisation streaming
                "-t", str(duration_seconds),
                output_path
            ]
            
            logger.info(f"🚀 Démarrage: {session_id}")
            logger.info(f"📝 Fichier: {output_path}")
            logger.info(f"⏱️ Durée: {duration_seconds}s")
            
            # Subprocess avec configuration optimisée
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            self.recording = True
            self.start_time = time.time()
            self.current_session_id = session_id
            self.current_output_path = output_path
            
            logger.info(f"✅ PID: {self.process.pid}")
            
            # Surveillance améliorée
            def monitor():
                try:
                    stdout, stderr = self.process.communicate(timeout=duration_seconds + 30)
                    
                    if self.process.returncode == 0:
                        logger.info(f"✅ Enregistrement {session_id} terminé avec succès")
                        # Vérifier que le fichier est créé et non vide
                        if Path(output_path).exists() and Path(output_path).stat().st_size > 1000:
                            logger.info(f"✅ Fichier validé: {Path(output_path).stat().st_size} bytes")
                        else:
                            logger.warning(f"⚠️ Fichier manquant ou trop petit: {output_path}")
                    else:
                        logger.error(f"❌ FFmpeg erreur (code {self.process.returncode})")
                        if stderr:
                            logger.error(f"❌ Stderr: {stderr[:500]}")
                        
                except subprocess.TimeoutExpired:
                    logger.warning(f"⚠️ Timeout {session_id} - arrêt forcé")
                    try:
                        self.process.kill()
                        self.process.wait(timeout=5)
                    except:
                        pass
                except Exception as e:
                    logger.error(f"❌ Erreur monitoring: {e}")
                finally:
                    # Réinitialisation garantie
                    self.reset_state()
            
            threading.Thread(target=monitor, daemon=True).start()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage: {e}")
            self.reset_state()
            return False
    
    def stop_recording(self, session_id=None):
        """Arrêter enregistrement avec nettoyage garanti"""
        
        if not self.recording or not self.process:
            logger.warning("⚠️ Aucun enregistrement actif")
            # Nettoyage préventif même si pas d'enregistrement détecté
            self.force_cleanup()
            return True
            
        try:
            logger.info(f"🛑 Arrêt enregistrement {session_id or self.current_session_id}...")
            
            # Envoyer SIGTERM
            self.process.terminate()
            
            try:
                # Attendre 5 secondes pour un arrêt propre
                self.process.wait(timeout=5)
                logger.info("✅ Arrêté proprement")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ Kill forcé nécessaire")
                self.process.kill()
                try:
                    self.process.wait(timeout=3)
                    logger.info("✅ Kill forcé réussi")
                except subprocess.TimeoutExpired:
                    logger.error("❌ Processus résistant au kill")
            
            # Vérifier que le processus est terminé
            if self.process.poll() is not None:
                logger.info(f"✅ Processus PID {self.process.pid} confirmé terminé")
            else:
                logger.warning(f"⚠️ Processus PID {self.process.pid} encore actif")
                
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt: {e}")
            return False
        finally:
            # Réinitialisation forcée dans tous les cas
            self.reset_state()
    
    def is_recording(self):
        """Vérifier l'état d'enregistrement avec validation"""
        if not self.recording:
            return False
            
        # Validation que le processus existe toujours
        if self.process and self.process.poll() is not None:
            logger.warning("⚠️ Processus terminé mais état non mis à jour")
            self.reset_state()
            return False
            
        return self.recording and self.process is not None
    
    def get_recording_duration(self):
        """Durée actuelle de l'enregistrement"""
        if not self.is_recording() or not self.start_time:
            return 0
        return int(time.time() - self.start_time)
    
    def get_status(self):
        """Statut complet avec validation"""
        is_recording = self.is_recording()
        return {
            "recording": is_recording,
            "pid": self.process.pid if self.process and is_recording else None,
            "duration": self.get_recording_duration(),
            "start_time": self.start_time,
            "session_id": self.current_session_id if is_recording else None,
            "output_path": self.current_output_path if is_recording else None
        }
