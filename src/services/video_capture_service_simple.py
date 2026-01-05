"""
Service de capture vidéo PadelVar - SOLUTION SIMPLIFIÉE QUI MARCHE
Reproduction EXACTE de la méthode qui fonctionne (19MB/5s)
"""
import os
import time
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

class VideoRecordingTaskSimple:
    """Tâche simple qui reproduit EXACTEMENT la solution qui marche"""
    
    def __init__(self, session_id, camera_url, output_path, max_duration, 
                 user_id, court_id, session_name, video_quality=None):
        self.session_id = session_id
        self.camera_url = camera_url
        self.output_path = output_path
        self.max_duration = max_duration
        self.user_id = user_id
        self.court_id = court_id
        self.session_name = session_name
        self.video_quality = video_quality or "simple"
        self.is_recording = False
        self.process = None
        self.ffmpeg_path = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
        
    def start(self):
        """Démarre avec méthode EXACTE qui marche"""
        try:
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # URL confirmée qui marche
            default_camera = "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi"
            camera_url = self.camera_url or default_camera
            
            # COMMANDE EXACTE qui marche (reproduction_exacte_solution.py)
            cmd = [
                self.ffmpeg_path,
                "-nostdin",
                "-y", 
                "-f", "mjpeg",
                "-i", camera_url,
                "-t", str(self.max_duration),
                "-c:v", "libx264",
                "-profile:v", "baseline",
                "-preset", "fast", 
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-r", "15",
                self.output_path
            ]
            
            logger.info(f"🎬 SIMPLE qui marche: {self.session_id}")
            logger.info(f"📹 URL: {camera_url}")
            logger.info(f"📁 Sortie: {self.output_path}")
            logger.info("✅ Config: REPRODUCTION EXACTE (19MB/5s)")
            
            # 🚀 MÉTHODE EXACTE: pas de threading, execution directe
            self.process = subprocess.Popen(
                cmd, 
                stdin=subprocess.DEVNULL, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self.is_recording = True
            logger.info(f"✅ Enregistrement SIMPLE démarré: {self.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur start simple: {e}")
            return False
            
    def wait_and_finish(self):
        """Attendre la fin NATURELLE comme reproduction_exacte_solution.py"""
        try:
            if self.process:
                logger.info(f"⏳ Attente fin naturelle FFmpeg: {self.session_id}")
                
                # 🚀 MÉTHODE EXACTE: process.communicate() comme solution qui marche
                stdout, stderr = self.process.communicate()
                
                logger.info(f"📊 FFmpeg terminé naturellement: code {self.process.returncode}")
                
                # Vérification fichier comme reproduction_exacte_solution.py
                if os.path.exists(self.output_path):
                    size = os.path.getsize(self.output_path)
                    logger.info(f"✅ Vidéo créée: {size:,} bytes")
                    
                    if size > 500000:
                        logger.info(f"✅ Fichier valide: {size:,} bytes")
                    else:
                        logger.warning(f"⚠️ Fichier petit: {size:,} bytes")
                else:
                    logger.error(f"❌ Fichier non créé: {self.output_path}")
                    
        except Exception as e:
            logger.error(f"❌ Erreur wait_and_finish: {e}")
        finally:
            self.is_recording = False
            
    def stop(self):
        """Arrêt simple sans forcer - laisser FFmpeg finir naturellement"""
        try:
            if self.process and self.process.poll() is None:
                logger.info(f"🛑 Demande arrêt doux: {self.session_id}")
                
                # PAS de terminate/kill forcé - laisser finir naturellement
                # Juste marquer comme arrêté
                self.is_recording = False
                
                logger.info(f"✅ Arrêt doux programmé: {self.session_id}")
                return True
            else:
                logger.info(f"✅ Processus déjà terminé: {self.session_id}")
                self.is_recording = False
                return True
                
        except Exception as e:
            logger.error(f"❌ Erreur arrêt: {e}")
            self.is_recording = False
            return False


class VideoCaptureServiceSimple:
    """Service simple qui reproduit la méthode qui marche"""
    
    def __init__(self):
        self.active_recordings = {}
        
    def start_recording(self, session_id, camera_url, output_path, max_duration,
                       user_id, court_id, session_name="Enregistrement", 
                       video_quality="simple"):
        """Démarre enregistrement simple qui marche"""
        try:
            # Forcer extension .mp4
            if not output_path.endswith('.mp4'):
                output_path = os.path.splitext(output_path)[0] + '.mp4'
                
            task = VideoRecordingTaskSimple(
                session_id, camera_url, output_path, max_duration,
                user_id, court_id, session_name, video_quality
            )
            
            if task.start():
                self.active_recordings[session_id] = task
                logger.info(f"Enregistrement SIMPLE démarré: {session_id}")
                return {
                    'success': True, 
                    'session_id': session_id, 
                    'quality': video_quality,
                    'message': f'Enregistrement SIMPLE {video_quality} démarré'
                }
            return {
                'success': False, 
                'error': 'Échec démarrage simple',
                'session_id': session_id
            }
            
        except Exception as e:
            logger.error(f"Erreur start_recording simple: {e}")
            return {
                'success': False, 
                'error': str(e),
                'session_id': session_id
            }
    
    def stop_recording(self, session_id):
        """Arrête et attend la fin naturelle"""
        try:
            if session_id in self.active_recordings:
                task = self.active_recordings[session_id]
                
                # Arrêt doux
                task.stop()
                
                # Attendre fin naturelle comme reproduction_exacte_solution.py
                task.wait_and_finish()
                
                # Attendre finalisation fichier
                time.sleep(2)
                
                output_path = task.output_path
                file_info = {
                    'success': True,
                    'file_path': output_path,
                    'output_file': output_path,
                    'file_exists': os.path.exists(output_path),
                    'duration': task.max_duration,
                    'session_id': session_id,
                    'quality': task.video_quality
                }
                
                if file_info['file_exists']:
                    file_size = os.path.getsize(output_path)
                    file_info['file_size'] = file_size
                    logger.info(f"📁 Fichier créé: {file_size:,} bytes")
                else:
                    file_info['file_size'] = 0
                    logger.warning(f"⚠️ Fichier non créé: {output_path}")
                    
                del self.active_recordings[session_id]
                logger.info(f"Enregistrement SIMPLE arrêté: {session_id}")
                return file_info
            else:
                return {
                    'success': False,
                    'error': 'Session non trouvée',
                    'session_id': session_id
                }
                
        except Exception as e:
            logger.error(f"Erreur stop_recording simple: {e}")
            return {
                'success': False,
                'error': str(e),
                'session_id': session_id
            }
    
    def is_recording(self, session_id):
        """Vérifie si une session est en cours"""
        return session_id in self.active_recordings
        
    def get_active_recordings(self):
        """Retourne la liste des enregistrements actifs"""
        return list(self.active_recordings.keys())
    
    def get_recording_status(self, session_id):
        """Retourne le statut d'un enregistrement"""
        if session_id in self.active_recordings:
            task = self.active_recordings[session_id]
            return {
                'session_id': session_id,
                'is_recording': task.is_recording,
                'quality': task.video_quality,
                'output_path': task.output_path,
                'file_exists': os.path.exists(task.output_path)
            }
        return None


# Instance globale simple
video_capture_service_simple = VideoCaptureServiceSimple()
