"""
Runner FFmpeg pour l'enregistrement vidéo
Gère les commandes FFmpeg et le cycle de vie des processus
"""
import os
import subprocess
import threading
import json
import platform
import shutil
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def detect_ffmpeg_path():
    """Détecte automatiquement le chemin FFmpeg selon le système d'exploitation"""
    system = platform.system().lower()
    
    # Chemins possibles selon l'OS
    possible_paths = []
    
    if system == 'windows':
        possible_paths = [
            r"C:\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\bin\ffmpeg.exe",
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            "ffmpeg.exe"
        ]
    elif system == 'linux':
        possible_paths = [
            '/usr/bin/ffmpeg',
            '/usr/local/bin/ffmpeg',
            '/snap/bin/ffmpeg',
            'ffmpeg'
        ]
    elif system == 'darwin':  # macOS
        possible_paths = [
            '/usr/local/bin/ffmpeg',
            '/opt/homebrew/bin/ffmpeg',
            '/usr/bin/ffmpeg',
            'ffmpeg'
        ]
    else:
        # Default fallback
        possible_paths = ['ffmpeg']
    
    # Tester chaque chemin
    for path in possible_paths:
        if path == 'ffmpeg' or path == 'ffmpeg.exe':
            # Vérifier dans le PATH système
            if shutil.which('ffmpeg'):
                return 'ffmpeg', 'ffprobe'
        else:
            # Vérifier le chemin absolu
            if Path(path).exists():
                probe_path = str(Path(path).parent / ('ffprobe.exe' if system == 'windows' else 'ffprobe'))
                return path, probe_path
    
    # Si rien n'est trouvé, utiliser les commandes système
    return 'ffmpeg', 'ffprobe'


def install_ffmpeg_linux():
    """Installe FFmpeg sur les systèmes Linux/Ubuntu"""
    try:
        logger.info("🔄 Tentative d'installation automatique de FFmpeg...")
        
        # Mettre à jour les paquets
        subprocess.run(['sudo', 'apt', 'update'], check=True, capture_output=True)
        
        # Installer FFmpeg
        subprocess.run(['sudo', 'apt', 'install', '-y', 'ffmpeg'], check=True, capture_output=True)
        
        logger.info("✅ FFmpeg installé avec succès")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Échec installation FFmpeg: {e}")
        return False
    except FileNotFoundError:
        logger.warning("⚠️ sudo/apt non disponible - installation manuelle requise")
        return False


def check_and_install_ffmpeg():
    """Vérifie FFmpeg et tente l'installation si nécessaire"""
    global FFMPEG_PATH, FFPROBE_PATH
    
    # Première détection
    FFMPEG_PATH, FFPROBE_PATH = detect_ffmpeg_path()
    
    # Vérification avec le chemin détecté
    try:
        # Tester la commande FFmpeg détectée
        result = subprocess.run([FFMPEG_PATH, '-version'], 
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info(f"✅ FFmpeg détecté: {FFMPEG_PATH}")
            logger.info(f"✅ FFprobe détecté: {FFPROBE_PATH}")
            return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        # Si échec avec le chemin détecté, essayer dans le PATH système
        if shutil.which('ffmpeg'):
            FFMPEG_PATH = 'ffmpeg'
            FFPROBE_PATH = 'ffprobe'
            logger.info(f"✅ FFmpeg détecté dans PATH: {FFMPEG_PATH}")
            logger.info(f"✅ FFprobe détecté dans PATH: {FFPROBE_PATH}")
            return True
    
    # Installation automatique sur Linux
    system = platform.system().lower()
    if system == 'linux':
        logger.warning("⚠️ FFmpeg non trouvé - tentative d'installation...")
        if install_ffmpeg_linux():
            # Redétecter après installation
            FFMPEG_PATH, FFPROBE_PATH = detect_ffmpeg_path()
            try:
                result = subprocess.run([FFMPEG_PATH, '-version'], 
                                       capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    logger.info(f"✅ FFmpeg installé et détecté: {FFMPEG_PATH}")
                    return True
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                pass
    
    # Si échec, log d'aide
    logger.error("❌ FFmpeg non disponible - veuillez l'installer manuellement:")
    if system == 'linux':
        logger.error("   sudo apt update && sudo apt install ffmpeg")
    elif system == 'windows':
        logger.error("   Télécharger depuis https://ffmpeg.org/download.html")
    elif system == 'darwin':
        logger.error("   brew install ffmpeg")
    
    return False


# Détection et installation automatique
FFMPEG_AVAILABLE = check_and_install_ffmpeg()


class FFmpegRunner:
    """Gestionnaire de processus FFmpeg pour l'enregistrement"""
    
    def __init__(self):
        if not FFMPEG_AVAILABLE:
            raise RuntimeError("FFmpeg n'est pas disponible sur ce système")
            
        self.quality_presets = {
            'low': {
                'crf': '28',
                'preset': 'veryfast',
                'scale': '854:480',
                'fps': '15',
                'bitrate': '500k'
            },
            'medium': {
                'crf': '23',
                'preset': 'fast', 
                'scale': '1280:720',
                'fps': '25',
                'bitrate': '1500k'
            },
            'high': {
                'crf': '18',
                'preset': 'medium',
                'scale': '1920:1080',
                'fps': '30',
                'bitrate': '3000k'
            }
        }
        
        # Cache pour les informations de caméras testées
        self._camera_cache = {}
        self._cache_lock = threading.Lock()
    
    def build_command(self, camera_url: str, output_path: str,
                      camera_type: str = 'rtsp', quality: str = 'medium',
                      max_duration: int = 3600) -> List[str]:
        """Construit la commande FFmpeg optimisée selon le type de caméra"""
        
        preset = self.quality_presets.get(
            quality, self.quality_presets['medium'])
        
        cmd = [FFMPEG_PATH, '-hide_banner', '-loglevel', 'error', 
               '-stats', '-nostdin']
        
        # Configuration d'entrée selon le type de caméra avec optimisations
        if camera_type.lower() == 'rtsp':
            cmd.extend([
                '-rtsp_transport', 'tcp',
                '-rtsp_flags', 'prefer_tcp',
                '-max_delay', '500000',  # Réduit la latence
                '-fflags', 'nobuffer',   # Pas de buffer pour le streaming
                '-flags', 'low_delay',   # Mode faible latence
                '-i', camera_url,
                '-use_wallclock_as_timestamps', '1',
                '-fflags', '+genpts+discardcorrupt'
            ])
        elif camera_type.lower() in ['mjpeg', 'http']:
            cmd.extend([
                '-f', 'mjpeg',
                '-fflags', 'nobuffer',
                '-flags', 'low_delay',
                '-i', camera_url,
                '-use_wallclock_as_timestamps', '1',
                '-fflags', '+genpts+discardcorrupt'
            ])
        else:
            # Par défaut, traiter comme RTSP avec optimisations
            cmd.extend([
                '-rtsp_transport', 'tcp',
                '-rtsp_flags', 'prefer_tcp',
                '-max_delay', '500000',
                '-fflags', 'nobuffer',
                '-flags', 'low_delay',
                '-i', camera_url,
                '-use_wallclock_as_timestamps', '1',
                '-fflags', '+genpts+discardcorrupt'
            ])
        
        # Configuration de sortie optimisée pour le web et performance
        cmd.extend([
            '-c:v', 'libx264',
            '-preset', preset['preset'],
            '-crf', preset['crf'],
            '-tune', 'zerolatency',
            '-profile:v', 'main',      # Profil compatible
            '-level:v', '4.0',         # Niveau compatible
            '-pix_fmt', 'yuv420p',     # Format pixel compatible
            '-vf', (f"scale={preset['scale']}:"
                   f"force_original_aspect_ratio=decrease,fps={preset['fps']},"
                   f"format=yuv420p"),
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',            # Sample rate audio
            '-ac', '2',                # Stéréo
            '-movflags', '+faststart+dash', # Optimisé pour streaming
            '-f', 'mp4',
            '-max_muxing_queue_size', '1024', # Buffer mux plus grand
            '-t', str(max_duration),   # Durée maximale
            '-y',                      # Écrase le fichier existant
            output_path
        ])
        
        return cmd
    
    def start_recording(self, camera_url: str, output_path: str,
                        camera_type: str = 'rtsp', quality: str = 'medium',
                        max_duration: int = 3600) -> subprocess.Popen:
        """Démarre l'enregistrement FFmpeg avec gestion d'erreurs robuste"""
        
        # Créer le dossier de sortie si nécessaire
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Vérifier la disponibilité de la caméra (optionnel - cache)
        if camera_url not in self._camera_cache:
            logger.info(f"Test de connectivité caméra: {camera_url}")
            
        # Construire et exécuter la commande
        cmd = self.build_command(
            camera_url, output_path, camera_type, quality, max_duration)
        
        logger.info(f"Démarrage FFmpeg: {' '.join(cmd[:8])}... (commande tronquée)")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=0,  # Pas de buffer
                env=dict(os.environ, **{'FFREPORT': 'file=/tmp/ffmpeg-report.log:level=32'})
            )
            
            # Vérifier que le processus a démarré
            time.sleep(0.5)
            if process.poll() is not None:
                # Processus déjà arrêté
                stderr_output = process.stderr.read() if process.stderr else "Aucune erreur capturée"
                raise RuntimeError(f"FFmpeg a échoué au démarrage: {stderr_output}")
            
            return process
            
        except Exception as e:
            logger.error(f"Erreur démarrage FFmpeg: {e}")
            raise
    
    def stop_recording(self, process: subprocess.Popen, timeout: int = 10) -> bool:
        """Arrête proprement l'enregistrement en envoyant 'q' à FFmpeg"""
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.write('q\n')
                process.stdin.flush()
                process.stdin.close()
            
            # Attendre que le processus se termine
            try:
                process.wait(timeout=timeout)
                logger.info(f"FFmpeg arrêté proprement (code: {process.returncode})")
                return True
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg ne s'arrête pas, forçage...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt FFmpeg: {e}")
            try:
                process.terminate()
                process.wait(timeout=5)
            except:  # noqa: E722
                process.kill()
                process.wait()
            return False
    
    def drain_stderr(self, process: subprocess.Popen, callback=None):
        """Lit stderr de FFmpeg en arrière-plan pour éviter les blocages"""
        def read_stderr():
            try:
                for line in iter(process.stderr.readline, ''):
                    if line:
                        line = line.strip()
                        if callback:
                            callback(line)
                        # Log des lignes importantes
                        if any(keyword in line.lower() for keyword in ['error', 'warning', 'frame=']):
                            logger.debug(f"FFmpeg: {line}")
            except Exception as e:
                logger.error(f"Erreur lecture stderr: {e}")
            finally:
                try:
                    process.stderr.close()
                except:  # noqa: E722
                    pass
        
        thread = threading.Thread(target=read_stderr, daemon=True)
        thread.start()
        return thread
    
    def probe_video_info(self, video_path: str) -> Optional[Dict[str, Any]]:
        """Extrait les informations du fichier vidéo avec ffprobe"""
        try:
            cmd = [
                FFPROBE_PATH,
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                
                # Extraire les informations utiles
                info = {
                    'duration': 0.0,
                    'size': 0,
                    'width': 0,
                    'height': 0,
                    'fps': 0.0,
                    'bitrate': 0,
                    'codec': 'unknown'
                }
                
                # Informations du format
                if 'format' in data:
                    format_info = data['format']
                    info['duration'] = float(format_info.get('duration', 0))
                    info['size'] = int(format_info.get('size', 0))
                    info['bitrate'] = int(format_info.get('bit_rate', 0))
                
                # Informations du stream vidéo
                for stream in data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        info['width'] = stream.get('width', 0)
                        info['height'] = stream.get('height', 0)
                        info['codec'] = stream.get('codec_name', 'unknown')
                        
                        # Calcul du FPS
                        fps_str = stream.get('r_frame_rate', '0/1')
                        if '/' in fps_str:
                            num, den = fps_str.split('/')
                            if int(den) > 0:
                                info['fps'] = float(num) / float(den)
                        break
                
                return info
                
        except Exception as e:
            logger.error(f"Erreur ffprobe pour {video_path}: {e}")
        
        return None
    
    def check_camera_accessibility(self, camera_url: str, timeout: int = 10) -> bool:
        """Teste si la caméra est accessible"""
        try:
            cmd = [
                FFPROBE_PATH,
                '-v', 'quiet',
                '-rtsp_transport', 'tcp',
                '-i', camera_url,
                '-t', '1',
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Test caméra {camera_url} échoué: {e}")
            return False
    
    def get_disk_space(self, path: str) -> Dict[str, int]:
        """Retourne l'espace disque disponible en bytes"""
        try:
            stat = os.statvfs(path)
            free_bytes = stat.f_bavail * stat.f_frsize
            total_bytes = stat.f_blocks * stat.f_frsize
            return {
                'free': free_bytes,
                'total': total_bytes,
                'used': total_bytes - free_bytes
            }
        except Exception:
            # Fallback pour Windows
            import shutil
            free_bytes = shutil.disk_usage(path).free
            total_bytes = shutil.disk_usage(path).total
            return {
                'free': free_bytes,
                'total': total_bytes,
                'used': total_bytes - free_bytes
            }
