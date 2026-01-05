import subprocess
import os
import logging
import time
import signal
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class VideoCapture:
    def __init__(self, session_id: str, camera_url: str, output_path: str):
        self.session_id = session_id
        self.camera_url = camera_url
        self.output_path = output_path
        self.process: Optional[subprocess.Popen] = None
        self.is_recording = False
        self.start_time = None
        self.duration = None  # Durée en secondes
        
    def start_recording(self, duration: int = 30, quality: str = 'medium') -> bool:
        """
        Démarre l'enregistrement avec durée fixe (solution Windows)
        
        Args:
            duration: Durée d'enregistrement en secondes
            quality: Qualité vidéo (low, medium, high)
        """
        if self.is_recording:
            logger.warning(f"⚠️ Enregistrement déjà en cours: {self.session_id}")
            return False

        try:
            # Créer le dossier de sortie
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
            
            # Configuration qualité
            quality_settings = {
                'low': {'bitrate': '500k', 'fps': 15, 'scale': '854:480'},
                'medium': {'bitrate': '1000k', 'fps': 20, 'scale': '1280:720'},
                'high': {'bitrate': '2000k', 'fps': 25, 'scale': '1920:1080'}
            }
            
            settings = quality_settings.get(quality, quality_settings['medium'])
            
            # Commande FFmpeg avec durée fixe (-t parameter)
            cmd = [
                'ffmpeg',
                '-y',  # Écraser fichier existant
                '-f', 'mjpeg',
                '-i', self.camera_url,
                '-t', str(duration),  # DURÉE FIXE - Clé du fix Windows
                '-c:v', 'libx264',
                '-b:v', settings['bitrate'],
                '-r', str(settings['fps']),
                '-vf', f"scale={settings['scale']}",
                '-preset', 'ultrafast',
                '-movflags', '+faststart',  # Pour lecture immédiate
                '-avoid_negative_ts', 'make_zero',
                '-fflags', '+genpts',
                self.output_path
            ]
            
            logger.info(f"🎬 Démarrage FFmpeg Windows: {self.session_id}")
            logger.info(f"📁 Sortie: {self.output_path}")
            logger.info(f"⏱️ Durée: {duration}s")
            logger.info(f"🔧 Commande: {' '.join(cmd)}")
            
            # Lancer FFmpeg SANS stdin (évite problème Windows)
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,  # PAS DE STDIN - Fix Windows
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )
            
            self.is_recording = True
            self.start_time = time.time()
            self.duration = duration
            
            logger.info(f"✅ Enregistrement démarré: {self.session_id} (PID: {self.process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage FFmpeg: {e}")
            self.is_recording = False
            return False
    
    def stop_recording(self) -> bool:
        """
        Arrête l'enregistrement (Windows safe)
        """
        if not self.is_recording:
            logger.warning(f"⚠️ Aucun enregistrement en cours: {self.session_id}")
            return False
            
        try:
            if self.process and self.process.poll() is None:
                logger.info(f"🛑 Arrêt FFmpeg Windows: {self.session_id}")
                
                # Méthode Windows: utiliser CTRL+C signal
                if os.name == 'nt':
                    # Windows: utiliser CTRL_C_EVENT
                    try:
                        os.kill(self.process.pid, signal.CTRL_C_EVENT)
                        logger.info(f"📝 Signal CTRL+C envoyé: {self.session_id}")
                    except Exception as signal_error:
                        logger.warning(f"⚠️ Erreur signal: {signal_error}")
                        # Fallback: terminate proprement
                        self.process.terminate()
                else:
                    # Unix: SIGINT
                    self.process.send_signal(signal.SIGINT)
                
                # Attendre terminaison propre
                try:
                    self.process.wait(timeout=10)
                    logger.info(f"✅ FFmpeg terminé proprement: {self.session_id}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"⚠️ Force terminate FFmpeg: {self.session_id}")
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logger.warning(f"⚠️ Force kill FFmpeg: {self.session_id}")
                        self.process.kill()
                        self.process.wait()
                    
            self.is_recording = False
            logger.info(f"✅ Enregistrement arrêté: {self.session_id}")
            
            # Vérifier le fichier
            if os.path.exists(self.output_path):
                file_size = os.path.getsize(self.output_path)
                logger.info(f"📁 Fichier créé: {self.output_path} ({file_size} bytes)")
                return True
            else:
                logger.error(f"❌ Fichier non créé: {self.output_path}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erreur arrêt: {e}")
            self.is_recording = False
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Retourne le statut de l'enregistrement"""
        status = {
            'session_id': self.session_id,
            'is_recording': self.is_recording,
            'output_path': self.output_path,
            'start_time': self.start_time,
            'duration': self.duration,
            'process_running': self.process and self.process.poll() is None if self.process else False
        }
        
        # Temps écoulé
        if self.start_time and self.is_recording:
            elapsed = time.time() - self.start_time
            status['elapsed_time'] = elapsed
            
            # Progression
            if self.duration:
                status['progress'] = min(elapsed / self.duration, 1.0)
                status['remaining_time'] = max(0, self.duration - elapsed)
        
        # Info fichier
        if os.path.exists(self.output_path):
            status['file_exists'] = True
            status['file_size'] = os.path.getsize(self.output_path)
        else:
            status['file_exists'] = False
            status['file_size'] = 0
            
        return status
    
    def is_finished(self) -> bool:
        """Vérifie si l'enregistrement est terminé"""
        if not self.is_recording:
            return True
            
        # Vérifier si le process est encore en vie
        if self.process and self.process.poll() is not None:
            # Process terminé
            self.is_recording = False
            logger.info(f"✅ Enregistrement terminé automatiquement: {self.session_id}")
            return True
            
        # Vérifier durée écoulée
        if self.start_time and self.duration:
            elapsed = time.time() - self.start_time
            if elapsed >= self.duration:
                logger.info(f"⏱️ Durée atteinte, arrêt: {self.session_id}")
                self.stop_recording()
                return True
                
        return False

class VideoCaptureManager:
    """Gestionnaire des sessions d'enregistrement"""
    def __init__(self):
        self.sessions: Dict[str, VideoCapture] = {}
        
    def create_session(self, session_id: str, camera_url: str, output_path: str) -> VideoCapture:
        """Crée une nouvelle session d'enregistrement"""
        if session_id in self.sessions:
            # Arrêter l'ancienne session
            old_session = self.sessions[session_id]
            if old_session.is_recording:
                old_session.stop_recording()
                
        session = VideoCapture(session_id, camera_url, output_path)
        self.sessions[session_id] = session
        return session
    
    def get_session(self, session_id: str) -> Optional[VideoCapture]:
        """Récupère une session existante"""
        return self.sessions.get(session_id)
    
    def remove_session(self, session_id: str) -> bool:
        """Supprime une session"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            if session.is_recording:
                session.stop_recording()
            del self.sessions[session_id]
            return True
        return False
    
    def get_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        """Retourne le statut de toutes les sessions"""
        return {sid: session.get_status() for sid, session in self.sessions.items()}
    
    def cleanup_finished_sessions(self):
        """Nettoie les sessions terminées"""
        finished_sessions = []
        for session_id, session in self.sessions.items():
            if session.is_finished() and not session.is_recording:
                finished_sessions.append(session_id)
                
        for session_id in finished_sessions:
            logger.info(f"🧹 Nettoyage session terminée: {session_id}")
            del self.sessions[session_id]

# Instance globale
capture_manager = VideoCaptureManager()
