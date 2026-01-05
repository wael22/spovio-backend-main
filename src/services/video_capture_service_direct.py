"""
Service de capture vidéo PadelVar - VERSION CORRIGÉE
Résout le problème de durée incorrecte avec arrêt propre FFmpeg
"""
import os
import time
import logging
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class DirectVideoCaptureService:
    """Service qui capture vidéo avec durée correcte via arrêt propre FFmpeg"""
    
    def __init__(self):
        self.active_recordings = {}
        # Configuration FFmpeg validée
        ffmpeg_dir = r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin"
        self.ffmpeg_path = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        self.ffprobe_path = os.path.join(ffmpeg_dir, "ffprobe.exe")

        
    def start_recording(self, session_id, camera_url, output_path,
                        max_duration, user_id, court_id,
                        session_name="Enregistrement",
                        video_quality="direct"):
        """Lance l'enregistrement CONTINU dès le start"""
        try:
            # Forcer extension .mp4
            if not output_path.endswith('.mp4'):
                output_path = os.path.splitext(output_path)[0] + '.mp4'
                
            # Assurer que le dossier existe
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # URL validée qui marche
            default_camera = "http://212.231.225.55:88/axis-cgi/mjpg/video.cgi"
            camera_url = camera_url or default_camera
            
            # COMMANDE FFmpeg SANS limite de durée pour arrêt manuel propre
            cmd = [
                self.ffmpeg_path,
                "-y",  # Pas de -nostdin pour pouvoir envoyer 'q'
                "-i", camera_url,
                "-c:v", "libx264",
                "-preset", "ultrafast", 
                "-profile:v", "baseline",
                "-level", "3.0",
                "-pix_fmt", "yuv420p",
                "-crf", "28",
                "-maxrate", "1000k",
                "-bufsize", "2000k", 
                "-g", "30",
                "-r", "15",
                "-f", "mp4",
                "-movflags", "+faststart",
                output_path
            ]
            
            logger.info(f"🎬 DÉBUT enregistrement CONTINU: {session_id}")
            logger.info(f"📁 Fichier: {output_path}")
            
            # ➡️ LANCER FFmpeg avec stdin accessible pour signal 'q'
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,  # CRUCIAL: permet envoi 'q'
                stdout=subprocess.DEVNULL,  # Éviter deadlock
                stderr=subprocess.DEVNULL,  # Éviter deadlock
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            # 💾 Stocker les infos de session
            self.active_recordings[session_id] = {
                'process': process,
                'output_path': output_path,
                'start_time': time.time(),
                'user_id': user_id,
                'court_id': court_id,
                'session_name': session_name,
                'max_duration': max_duration,
                'camera_url': camera_url,
                'quality': video_quality
            }
            
            logger.info(f"✅ FFmpeg PID: {process.pid}")
            
            return {
                'success': True,
                'session_id': session_id,
                'quality': video_quality,
                'message': f'Enregistrement CONTINU {video_quality} démarré'
            }
            
        except Exception as e:
            logger.error(f"Erreur start_recording CONTINU: {e}")
            return {
                'success': False,
                'error': str(e),
                'session_id': session_id
            }

    def stop_recording(self, session_id):
        """Arrête l'enregistrement avec durée correcte"""
        if session_id not in self.active_recordings:
            return {'success': False, 'error': 'Session non trouvée'}
            
        recording_info = self.active_recordings[session_id]
        
        try:
            # 🕐 Calculer la durée RÉELLE avant arrêt
            real_duration = int(time.time() - recording_info['start_time'])
            logger.info(f"🕐 Durée réelle calculée: {real_duration} secondes")
            
            # 🎯 Récupérer le processus FFmpeg
            process = recording_info.get('process')
            if process and process.poll() is None:  # Si encore en cours
                logger.info(f"⏰ Arrêt propre FFmpeg: {session_id}")
                
                # 🛑 Arrêt direct avec SIGTERM (plus fiable)
                try:
                    logger.info("📨 Envoi SIGTERM à FFmpeg")
                    process.terminate()
                    
                    # ⏳ Attendre que FFmpeg termine proprement
                    process.wait(timeout=10)
                    logger.info("✅ FFmpeg terminé avec SIGTERM")
                        
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ Kill forcé après SIGTERM")
                    process.kill()
                    process.wait()
                except Exception as e:
                    logger.error(f"❌ Erreur arrêt: {e}")
                    try:
                        process.kill()
                        process.wait()
                    except Exception:
                        pass
            
            # 🔄 Attendre finalisation du fichier
            logger.info("⏳ Attente finalisation fichier...")
            time.sleep(8)  # Plus de temps pour que FFmpeg finisse d'écrire
            
            # ✅ Vérifier que le fichier existe et a du contenu
            output_path = recording_info['output_path']
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                logger.info(f"📁 Fichier final: {file_size:,} bytes")
                
                if file_size > 1000:  # Plus de 1KB
                    # 🎥 VÉRIFIER LA DURÉE RÉELLE DU FICHIER VIDÉO
                    actual_duration = self._get_video_duration(output_path)
                    if actual_duration:
                        logger.info(f"🎥 Durée vidéo réelle: {actual_duration}s")
                        # Utiliser la durée de la vidéo plutôt que le calcul temporel
                        final_duration = actual_duration
                    else:
                        # Fallback sur le calcul temporel
                        final_duration = real_duration
                        logger.warning("⚠️ Impossible de lire durée vidéo, utilisation calcul temporel")
                    
                    message = (f"Vidéo créée: {final_duration}s, "
                               f"{file_size:,} bytes")
                    result = {
                        'success': True,
                        'file_path': output_path,
                        'output_file': output_path,
                        'session_id': session_id,
                        'duration': final_duration,
                        'file_size': file_size,
                        'quality': recording_info.get('quality', 'direct'),
                        'file_exists': True,
                        'message': message
                    }
                else:
                    logger.error(f"❌ Fichier trop petit: {file_size} bytes")
                    result = {
                        'success': False,
                        'error': f'Fichier corrompu: {file_size} bytes',
                        'session_id': session_id
                    }
            else:
                logger.error(f"❌ Fichier non trouvé: {output_path}")
                result = {
                    'success': False,
                    'error': 'Fichier vidéo non créé',
                    'session_id': session_id
                }
            
            # 🧹 Nettoyer la session
            del self.active_recordings[session_id]
            return result
            
        except Exception as e:
            logger.error(f"Erreur stop_recording: {e}")
            # Nettoyage d'urgence
            if session_id in self.active_recordings:
                try:
                    process = self.active_recordings[session_id].get('process')
                    if process and process.poll() is None:
                        process.kill()
                        process.wait()
                except Exception:
                    pass
                del self.active_recordings[session_id]
            return {
                'success': False,
                'error': str(e),
                'session_id': session_id
            }
    
    def _get_video_duration(self, video_path):
        """Obtient la durée réelle du fichier vidéo avec FFprobe/FFmpeg"""
        try:
            # MÉTHODE 1: FFprobe (plus rapide et précis)
            cmd = [
                self.ffprobe_path,
                "-v", "quiet",
                "-print_format", "json", 
                "-show_format",
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                import json
                data = json.loads(result.stdout)
                duration_str = data.get('format', {}).get('duration')
                if duration_str:
                    return int(float(duration_str))
                    
        except Exception as e:
            logger.warning(f"⚠️ FFprobe échoué: {e}")
            
        # MÉTHODE 2: Parser sortie FFmpeg 
        try:
            cmd = [self.ffmpeg_path, "-i", video_path, "-f", "null", "-"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            
            # Parser "Duration: HH:MM:SS.MS"
            for line in result.stderr.split('\n'):
                if 'Duration:' in line:
                    duration_part = line.split('Duration: ')[1].split(',')[0]
                    time_parts = duration_part.split(':')
                    if len(time_parts) == 3:
                        hours = int(time_parts[0])
                        minutes = int(time_parts[1]) 
                        seconds = float(time_parts[2])
                        return int(hours * 3600 + minutes * 60 + seconds)
                        
        except Exception as e:
            logger.warning(f"⚠️ FFmpeg parsing échoué: {e}")
            
        return None
    
    def get_active_recordings(self):
        """Retourne la liste des enregistrements actifs"""
        return list(self.active_recordings.keys())
    
    def is_recording(self, session_id):
        """Vérifie si une session est en cours d'enregistrement"""
        return session_id in self.active_recordings
        
    def cleanup_finished_recordings(self):
        """Nettoie les enregistrements terminés"""
        to_remove = []
        for session_id, info in self.active_recordings.items():
            process = info.get('process')
            if process and process.poll() is not None:
                logger.info(f"🧹 Nettoyage session terminée: {session_id}")
                to_remove.append(session_id)
        
        for session_id in to_remove:
            del self.active_recordings[session_id]
            
        return len(to_remove)
        
    def get_recording_status(self, session_id):
        """Obtient le statut détaillé d'un enregistrement"""
        if session_id not in self.active_recordings:
            return {'status': 'not_found'}
            
        info = self.active_recordings[session_id]
        process = info.get('process')
        
        if process:
            if process.poll() is None:
                # Processus encore actif
                current_duration = int(time.time() - info['start_time'])
                return {
                    'status': 'recording',
                    'duration': current_duration,
                    'pid': process.pid,
                    'output_path': info['output_path']
                }
            else:
                # Processus terminé
                return {
                    'status': 'finished',
                    'exit_code': process.returncode
                }
        else:
            return {'status': 'error', 'message': 'Processus non trouvé'}


# Instance globale du service
video_capture_service_direct = DirectVideoCaptureService()
