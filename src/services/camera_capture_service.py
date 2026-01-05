import subprocess
import os
import logging
import signal
import time
import threading
from datetime import datetime, timedelta
import json
import psutil

logger = logging.getLogger(__name__)

class CameraCaptureService:
    def __init__(self):
        self.active_captures = {}  # recording_id: capture_info
        self.output_dir = 'recordings'
        self.temp_dir = 'temp_recordings'
        
        # Créer les dossiers
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Configuration par défaut pour caméras IP Axis
        self.default_config = {
            'input_format': 'mjpeg',
            'reconnect': 1,
            'reconnect_streamed': 1,
            'reconnect_delay_max': 5,
            'timeout': 30000000,  # 30 secondes en microsecondes
            'analyzeduration': '10M',
            'probesize': '10M',
            'buffer_size': '1024k'
        }
    
    def get_optimized_ffmpeg_cmd(self, camera_url, output_path, duration_minutes, quality='high'):
        """Génère la commande FFmpeg optimisée pour caméra IP Axis"""
        
        # Configuration qualité
        quality_configs = {
            'high': {
                'resolution': '1920x1080',
                'fps': '25',
                'crf': '20',
                'preset': 'medium',
                'bitrate_video': '2500k',
                'bitrate_audio': '128k'
            },
            'medium': {
                'resolution': '1280x720', 
                'fps': '20',
                'crf': '23',
                'preset': 'fast',
                'bitrate_video': '1500k',
                'bitrate_audio': '96k'
            },
            'low': {
                'resolution': '854x480',
                'fps': '15', 
                'crf': '26',
                'preset': 'faster',
                'bitrate_video': '800k',
                'bitrate_audio': '64k'
            }
        }
        
        config = quality_configs.get(quality, quality_configs['medium'])
        
        # Utiliser le chemin FFmpeg complet de votre système
        ffmpeg_path = "C:\\ffmpeg\\ffmpeg-7.1.1-essentials_build\\bin\\ffmpeg.exe"
        
        # Commande FFmpeg optimisée pour Axis MJPEG
        cmd = [
            ffmpeg_path, '-y',  # Force overwrite
            
            # === OPTIONS D'ENTRÉE OPTIMISÉES ===
            '-f', 'mjpeg',  # Format d'entrée MJPEG
            '-analyzeduration', self.default_config['analyzeduration'],
            '-probesize', self.default_config['probesize'],
            '-buffer_size', self.default_config['buffer_size'],
            
            # === GESTION RÉSEAU ROBUSTE ===
            '-reconnect', str(self.default_config['reconnect']),
            '-reconnect_streamed', str(self.default_config['reconnect_streamed']),  
            '-reconnect_delay_max', str(self.default_config['reconnect_delay_max']),
            '-timeout', str(self.default_config['timeout']),
            '-user_agent', 'PadelVar-Recorder/1.0',
            
            # === URL CAMÉRA ===
            '-i', camera_url,
            
            # === DURÉE ===
            '-t', str(duration_minutes * 60),
            
            # === ENCODAGE VIDÉO OPTIMISÉ ===
            '-c:v', 'libx264',
            '-preset', config['preset'],
            '-crf', config['crf'],
            '-maxrate', config['bitrate_video'],
            '-bufsize', str(int(config['bitrate_video'].replace('k', '')) * 2) + 'k',
            
            # === RÉSOLUTION ET FPS ===
            '-vf', f'scale={config["resolution"]}:force_original_aspect_ratio=decrease:force_divisible_by=2,fps={config["fps"]}',
            
            # === ENCODAGE AUDIO (si disponible) ===
            '-c:a', 'aac',
            '-b:a', config['bitrate_audio'],
            '-ar', '44100',
            
            # === OPTIONS DE SORTIE ===
            '-movflags', '+faststart',  # Optimisation web
            '-f', 'mp4',
            '-avoid_negative_ts', 'make_zero',
            
            # === GESTION D'ERREURS ===
            '-xerror',  # Sortir en cas d'erreur
            '-loglevel', 'info',
            
            output_path
        ]
        
        return cmd
    
    def start_capture(self, recording_id, camera_url, duration_minutes, quality='medium', title="Enregistrement"):
        """Démarre la capture vidéo"""
        try:
            # Nom du fichier de sortie
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{recording_id}_{timestamp}.mp4"
            temp_path = os.path.join(self.temp_dir, filename)
            final_path = os.path.join(self.output_dir, filename)
            
            # Générer la commande FFmpeg
            cmd = self.get_optimized_ffmpeg_cmd(camera_url, temp_path, duration_minutes, quality)
            
            logger.info(f"🎬 Démarrage capture {recording_id}")
            logger.info(f"📹 Caméra: {camera_url}")
            logger.info(f"⏱️ Durée: {duration_minutes} minutes")
            logger.info(f"🎯 Qualité: {quality}")
            logger.debug(f"🔧 Commande: {' '.join(cmd)}")
            
            # Lancer FFmpeg avec gestion Windows appropriée
            if os.name == 'nt':  # Windows
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    text=False,  # Mode binaire pour termination propre
                    bufsize=1,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:  # Unix/Linux
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    text=False,
                    preexec_fn=os.setsid,
                    bufsize=1
                )
            
            # Stocker les informations
            self.active_captures[recording_id] = {
                'process': process,
                'temp_path': temp_path,
                'final_path': final_path,
                'camera_url': camera_url,
                'start_time': datetime.now(),
                'duration_minutes': duration_minutes,
                'quality': quality,
                'title': title,
                'cmd': cmd
            }
            
            # Thread de monitoring
            monitor_thread = threading.Thread(
                target=self._monitor_capture,
                args=(recording_id,),
                daemon=True
            )
            monitor_thread.start()
            
            logger.info(f"✅ Capture démarrée - PID: {process.pid}")
            return True, f"Capture démarrée (PID: {process.pid})"
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage capture {recording_id}: {e}")
            return False, str(e)
    
    def _monitor_capture(self, recording_id):
        """Monitore une capture en arrière-plan"""
        try:
            if recording_id not in self.active_captures:
                return
            
            capture_info = self.active_captures[recording_id]
            process = capture_info['process']
            
            # Attendre la fin du processus
            stdout, stderr = process.communicate()
            
            # Traitement post-capture
            if process.returncode == 0:
                self._finalize_capture(recording_id, success=True)
            else:
                logger.error(f"❌ Capture {recording_id} échouée: {stderr}")
                self._finalize_capture(recording_id, success=False, error=stderr)
                
        except Exception as e:
            logger.error(f"❌ Erreur monitoring {recording_id}: {e}")
            self._finalize_capture(recording_id, success=False, error=str(e))
    
    def _finalize_capture(self, recording_id, success=True, error=None):
        """Finalise une capture"""
        try:
            if recording_id not in self.active_captures:
                return
            
            capture_info = self.active_captures[recording_id]
            temp_path = capture_info['temp_path']
            final_path = capture_info['final_path']
            
            if success and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                # Déplacer vers le dossier final
                os.rename(temp_path, final_path)
                logger.info(f"✅ Capture {recording_id} finalisée: {final_path}")
                
                # Mettre à jour les infos
                capture_info['status'] = 'completed'
                capture_info['final_path'] = final_path
                capture_info['file_size'] = os.path.getsize(final_path)
                
            else:
                logger.error(f"❌ Capture {recording_id} échouée: {error}")
                capture_info['status'] = 'failed'
                capture_info['error'] = error
                
                # Nettoyer le fichier temporaire
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
            
        except Exception as e:
            logger.error(f"❌ Erreur finalisation {recording_id}: {e}")
    
    def stop_capture(self, recording_id):
        """Arrête une capture avec termination propre FFmpeg"""
        try:
            if recording_id not in self.active_captures:
                return False, "Capture non trouvée"
            
            capture_info = self.active_captures[recording_id]
            process = capture_info['process']
            
            if process.poll() is None:  # Processus encore en vie
                logger.info(f"🛑 Arrêt capture {recording_id} (PID: {process.pid})")
                
                # TERMINATION PROPRE COMME NOTRE FIX
                try:
                    # Envoyer 'q' à FFmpeg pour arrêt gracieux
                    process.stdin.write(b'q\n')
                    process.stdin.flush()
                    
                    # Attendre la terminaison propre
                    exit_code = process.wait(timeout=10)
                    logger.info(f"✅ FFmpeg terminé proprement avec code: {exit_code}")
                    
                except subprocess.TimeoutExpired:
                    logger.warning(f"⚠️ Timeout - force kill pour {recording_id}")
                    if os.name == 'nt':  # Windows
                        process.terminate()
                    else:  # Unix/Linux
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        except:
                            process.kill()
                except Exception as e:
                    logger.error(f"❌ Erreur termination propre: {e}")
                    process.terminate()
            
            # Finaliser
            time.sleep(1)
            self._finalize_capture(recording_id, success=True)
            
            return True, "Capture arrêtée"
            
        except Exception as e:
            logger.error(f"❌ Erreur arrêt capture {recording_id}: {e}")
            return False, str(e)
    
    def get_capture_status(self, recording_id):
        """Récupère le statut d'une capture"""
        if recording_id not in self.active_captures:
            return None
        
        capture_info = self.active_captures[recording_id]
        process = capture_info['process']
        
        # Vérifier si le processus est actif
        is_running = process.poll() is None
        
        status = {
            'recording_id': recording_id,
            'is_running': is_running,
            'start_time': capture_info['start_time'].isoformat(),
            'duration_minutes': capture_info['duration_minutes'],
            'quality': capture_info['quality'],
            'camera_url': capture_info['camera_url'],
            'title': capture_info['title'],
            'pid': process.pid if is_running else None,
            'temp_path': capture_info['temp_path'],
            'status': capture_info.get('status', 'running' if is_running else 'unknown')
        }
        
        # Ajouter info fichier si disponible
        temp_path = capture_info['temp_path']
        if os.path.exists(temp_path):
            status['file_size'] = os.path.getsize(temp_path)
            status['duration_recorded'] = (datetime.now() - capture_info['start_time']).total_seconds() / 60
        
        return status
    
    def get_all_active_captures(self):
        """Récupère toutes les captures actives"""
        active = []
        for recording_id in list(self.active_captures.keys()):
            status = self.get_capture_status(recording_id)
            if status:
                active.append(status)
        return active
    
    def cleanup_finished_captures(self):
        """Nettoie les captures terminées"""
        finished = []
        for recording_id, capture_info in list(self.active_captures.items()):
            if capture_info['process'].poll() is not None:
                finished.append(recording_id)
        
        for recording_id in finished:
            del self.active_captures[recording_id]
            logger.info(f"🧹 Capture {recording_id} nettoyée")
        
        return len(finished)
    
    def test_camera_connection(self, camera_url, timeout=20):
        """Teste la connexion à une caméra avec timeout plus long"""
        try:
            # Utiliser le chemin FFmpeg complet
            ffmpeg_path = "C:\\ffmpeg\\ffmpeg-7.1.1-essentials_build\\bin\\ffmpeg.exe"
            
            # Commande FFmpeg simple pour tester
            cmd = [
                ffmpeg_path, '-y',
                '-f', 'mjpeg',
                '-timeout', str(timeout * 1000000),  # En microsecondes
                '-user_agent', 'PadelVar-Test/1.0',
                '-i', camera_url,
                '-frames:v', '1',  # Capturer 1 frame seulement
                '-f', 'null', '-'  # Sortie vers null
            ]
            
            logger.info(f"🔍 Test connexion caméra: {camera_url}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10
            )
            
            if result.returncode == 0:
                logger.info("✅ Connexion caméra OK")
                return True, "Connexion réussie"
            else:
                error_msg = result.stderr or "Erreur inconnue"
                logger.error(f"❌ Échec connexion caméra: {error_msg}")
                return False, error_msg
                
        except subprocess.TimeoutExpired:
            return False, "Timeout de connexion"
        except Exception as e:
            logger.error(f"❌ Erreur test caméra: {e}")
            return False, str(e)

# Instance globale
camera_capture = CameraCaptureService()
