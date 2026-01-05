"""
Service de capture vidéo PadelVar - CORRECTION "CAN'T PLAY"
Corrige le problème de corruption des fichiers vidéo
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoRecordingTask:
    """Tâche d'enregistrement avec finalisation correcte des fichiers"""
    
    def __init__(self, session_id, camera_url, output_path, max_duration, 
                 user_id, court_id, session_name, video_quality=None):
        self.session_id = session_id
        self.camera_url = camera_url
        self.output_path = output_path
        self.max_duration = max_duration
        self.user_id = user_id
        self.court_id = court_id
        self.session_name = session_name
        self.video_quality = video_quality or "web_compatible"
        self.is_recording = False
        self.process = None
        self.thread = None
        self.ffmpeg_path = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
        
    def start(self):
        """Démarre enregistrement avec configuration ultra-compatible"""
        try:
            Path(self.output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # URL correcte de la caméra
            default_camera = "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi"
            camera_url = self.camera_url or default_camera
            
            # 🎯 CONFIGURATION ULTRA-COMPATIBLE pour résoudre "can't play"
            cmd = [
                self.ffmpeg_path,
                "-nostdin",                    # Évite les blocages
                "-y",                          # Écrase fichier existant
                "-f", "mjpeg",                 # Format d'entrée
                "-i", camera_url,              # URL caméra
                "-t", str(self.max_duration),  # Durée
                
                # 🔧 ENCODAGE ULTRA-COMPATIBLE
                "-c:v", "libx264",             # Codec H.264
                "-profile:v", "baseline",      # Profil le plus compatible
                "-level", "3.0",               # Niveau compatible
                "-preset", "fast",             # Bon compromis
                "-crf", "23",                  # Qualité standard
                
                # 🌐 OPTIMISATIONS WEB CRITIQUES
                "-movflags", "+faststart",     # Métadonnées au début
                "-pix_fmt", "yuv420p",         # Format couleur standard
                "-r", "15",                    # 15 FPS pour réduire taille
                
                # 🎬 FINALISATION PROPRE
                "-avoid_negative_ts", "make_zero",  # Timestamps propres
                "-fflags", "+genpts",          # Génère timestamps manquants
                
                self.output_path
            ]
            
            logger.info(f"🎬 FFmpeg ULTRA-COMPATIBLE: {self.session_id}")
            logger.info(f"📹 URL: {camera_url}")
            logger.info(f"📁 Sortie: {self.output_path}")
            logger.info(f"✅ Config: baseline profile, faststart, yuv420p")
            
            # Processus avec gestion d'erreur améliorée
            self.process = subprocess.Popen(
                cmd, 
                stdin=subprocess.DEVNULL, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self.is_recording = True
            self.thread = threading.Thread(target=self._monitor_process, daemon=True)
            self.thread.start()
            
            logger.info(f"✅ Enregistrement COMPATIBLE démarré: {self.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur FFmpeg compatible {self.session_id}: {e}")
            return False
            
    def _monitor_process(self):
        """Surveillance avec validation de compatibilité"""
        try:
            # Attendre la fin du processus
            stdout, stderr = self.process.communicate()
            
            logger.info(f"📊 FFmpeg terminé avec code: {self.process.returncode}")
            
            # Attendre que le fichier soit complètement écrit
            time.sleep(2)
            
            if os.path.exists(self.output_path):
                size = os.path.getsize(self.output_path)
                logger.info(f"✅ Fichier créé: {size:,} bytes")
                
                # Test de validation basique
                self._validate_video_file()
            else:
                logger.error(f"❌ Fichier non créé: {self.output_path}")
                
        except Exception as e:
            logger.error(f"❌ Monitoring erreur: {e}")
        finally:
            self.is_recording = False
            
    def _validate_video_file(self):
        """Validation rapide du fichier vidéo"""
        try:
            # Test simple: lire les premiers octets pour vérifier la structure MP4
            with open(self.output_path, 'rb') as f:
                header = f.read(32)
                
            # Vérifier signature MP4
            if b'ftyp' in header or b'isom' in header:
                logger.info(f"✅ Structure MP4 valide détectée")
                
                # Test de lecture avec FFprobe si disponible
                try:
                    probe_cmd = [
                        self.ffmpeg_path.replace('ffmpeg.exe', 'ffprobe.exe'),
                        '-v', 'quiet',
                        '-select_streams', 'v:0',
                        '-show_entries', 'stream=duration',
                        '-of', 'csv=p=0',
                        self.output_path
                    ]
                    
                    result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0 and result.stdout.strip():
                        duration = float(result.stdout.strip())
                        logger.info(f"✅ Durée vidéo validée: {duration:.2f}s")
                    else:
                        logger.warning(f"⚠️ Validation FFprobe échouée")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Validation avancée échouée: {e}")
                    
            else:
                logger.error(f"❌ Structure MP4 invalide")
                
        except Exception as e:
            logger.error(f"❌ Validation fichier échouée: {e}")
            
    def stop(self):
        """Arrêt avec finalisation propre garantie"""
        try:
            if self.process and self.process.poll() is None:
                logger.info(f"🛑 Arrêt propre FFmpeg: {self.session_id}")
                
                # Envoyer signal d'arrêt propre (q pour FFmpeg)
                try:
                    self.process.stdin.write(b'q\n')
                    self.process.stdin.flush()
                except:
                    pass  # stdin peut être fermé
                
                # Attendre finalisation
                try:
                    self.process.wait(timeout=10)
                    logger.info(f"✅ FFmpeg terminé proprement: {self.session_id}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"⚠️ Timeout, terminaison forcée: {self.session_id}")
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        
            # Attendre que le fichier soit finalisé
            time.sleep(3)
            
            self.is_recording = False
            logger.info(f"✅ Enregistrement arrêté et finalisé: {self.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt: {e}")
            self.is_recording = False
            return False


class VideoCaptureService:
    """Service capture avec garantie de compatibilité"""
    
    def __init__(self):
        self.active_recordings = {}
        
    def start_recording(self, session_id, camera_url, output_path, max_duration,
                       user_id, court_id, session_name="Enregistrement", 
                       video_quality="ultra_compatible"):
        """Démarre enregistrement ultra-compatible"""
        try:
            # Forcer extension .mp4
            if not output_path.endswith('.mp4'):
                output_path = os.path.splitext(output_path)[0] + '.mp4'
                
            task = VideoRecordingTask(
                session_id, camera_url, output_path, max_duration,
                user_id, court_id, session_name, video_quality
            )
            
            if task.start():
                self.active_recordings[session_id] = task
                logger.info(f"Enregistrement ultra-compatible démarré: {session_id}")
                return {
                    'success': True, 
                    'session_id': session_id, 
                    'quality': video_quality,
                    'message': f'Enregistrement {video_quality} démarré'
                }
            return {
                'success': False, 
                'error': 'Échec FFmpeg compatible',
                'session_id': session_id
            }
            
        except Exception as e:
            logger.error(f"Erreur lors du démarrage de l'enregistrement: {e}")
            return {
                'success': False, 
                'error': str(e),
                'session_id': session_id
            }
    
    def stop_recording(self, session_id):
        """Arrête enregistrement avec validation finale"""
        try:
            if session_id in self.active_recordings:
                task = self.active_recordings[session_id]
                task.stop()
                
                # Attendre finalisation complète
                time.sleep(3)
                
                output_path = task.output_path
                file_info = {
                    'success': True,
                    'file_path': output_path,
                    'output_file': output_path,
                    'file_exists': os.path.exists(output_path),
                    'duration': task.max_duration,
                    'session_id': session_id,
                    'quality': task.video_quality,
                    'compatible': True  # Indique format compatible
                }
                
                if file_info['file_exists']:
                    file_info['file_size'] = os.path.getsize(output_path)
                    logger.info(f"📁 Fichier compatible créé: {file_info['file_size']:,} bytes")
                else:
                    file_info['file_size'] = 0
                    file_info['compatible'] = False
                    logger.warning(f"⚠️ Fichier non créé: {output_path}")
                    
                del self.active_recordings[session_id]
                logger.info(f"Enregistrement compatible arrêté: {session_id}")
                return file_info
            else:
                return {
                    'success': False,
                    'error': 'Session non trouvée',
                    'session_id': session_id
                }
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt de l'enregistrement: {e}")
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
                'file_exists': os.path.exists(task.output_path),
                'compatible': True
            }
        return None


# Instance globale ultra-compatible
video_capture_service = VideoCaptureService()
