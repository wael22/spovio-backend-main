"""
Service optimisé pour le stockage et la distribution de vidéos avec Bunny Stream CDN
Gère l'upload robuste des fichiers vidéo avec retry automatique et gestion d'erreurs améliorée
"""

import os
import logging
import threading
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
import requests
from pathlib import Path
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
import hashlib

# Configuration du logger
logger = logging.getLogger(__name__)


class BunnyStorageConfig:
    """Configuration centralisée pour Bunny Storage"""
    
    def __init__(self):
        self.api_key = os.environ.get('BUNNY_API_KEY', '1e962f55-b5f8-49e4-a11ee33c4216-2035-4b81')  # CORRECTED
        self.library_id = os.environ.get('BUNNY_LIBRARY_ID', '573234')  # Updated
        self.cdn_hostname = os.environ.get('BUNNY_CDN_HOSTNAME', 'vz-f6fd0c7d-d70.b-cdn.net')  # Updated
        
        # URLs API
        self.api_base_url = f"https://video.bunnycdn.com/library/{self.library_id}"
        
        # Headers API
        self.headers = {
            "AccessKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Configuration avancée
        self.chunk_size = 8 * 1024 * 1024  # 8MB chunks pour upload
        self.max_retries = 3
        self.retry_delay = 5  # secondes
        self.timeout = 300  # 5 minutes
        self.max_concurrent_uploads = 2
    
    def is_valid(self) -> bool:
        """Vérifie si la configuration est valide"""
        return (
            bool(self.api_key) and 
            len(self.api_key) > 10 and
            bool(self.library_id) and 
            self.library_id.isdigit() and
            bool(self.cdn_hostname) and 
            '.' in self.cdn_hostname
        )


class UploadStatus:
    """États possibles d'un upload"""
    PENDING = 'pending'
    UPLOADING = 'uploading' 
    PROCESSING = 'processing'
    COMPLETED = 'completed'
    FAILED = 'failed'
    RETRYING = 'retrying'


class UploadTask:
    """Tâche d'upload avec métadonnées"""
    
    def __init__(self, local_path: str, title: str = None, metadata: Dict = None):
        self.id = f"upload_{int(time.time())}_{hashlib.md5(local_path.encode()).hexdigest()[:8]}"
        self.local_path = local_path
        self.title = title or Path(local_path).stem
        self.metadata = metadata or {}
        
        self.status = UploadStatus.PENDING
        self.retries = 0
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        
        self.bunny_video_id = None
        self.bunny_url = None
        self.error_message = None
        
        # Pour suivi de progression
        self.bytes_uploaded = 0
        self.total_bytes = 0
        
        # Lock pour thread safety
        self._lock = threading.Lock()
    
    def update_status(self, status: str, error: str = None):
        """Met à jour le statut de manière thread-safe"""
        with self._lock:
            self.status = status
            if error:
                self.error_message = error
            if status == UploadStatus.UPLOADING and not self.started_at:
                self.started_at = datetime.now()
            elif status == UploadStatus.COMPLETED:
                self.completed_at = datetime.now()
    
    def increment_retry(self):
        """Incrémente le compteur de retry"""
        with self._lock:
            self.retries += 1
    
    def get_file_size(self) -> int:
        """Retourne la taille du fichier"""
        if not hasattr(self, '_file_size'):
            try:
                self._file_size = Path(self.local_path).stat().st_size
            except:
                self._file_size = 0
        return self._file_size


class BunnyStorageService:
    """Service de gestion du stockage vidéo sur Bunny Stream CDN optimisé"""
    
    def __init__(self):
        """Initialise le service de stockage Bunny Stream"""
        self.config = BunnyStorageConfig()
        
        if not self.config.is_valid():
            logger.error("❌ Configuration Bunny CDN invalide")
            raise ValueError("Configuration Bunny CDN invalide")
        
        # Queue et workers
        self.upload_queue = Queue()
        self.active_uploads: Dict[str, UploadTask] = {}
        self.completed_uploads: Dict[str, UploadTask] = {}
        
        # Thread management
        self.executor = ThreadPoolExecutor(
            max_workers=self.config.max_concurrent_uploads,
            thread_name_prefix="BunnyUpload"
        )
        self.is_running = True
        self._lock = threading.RLock()
        
        # Statistiques
        self.stats = {
            'uploads_started': 0,
            'uploads_completed': 0,
            'uploads_failed': 0,
            'bytes_uploaded': 0
        }
        
        # Démarrer le worker
        self._start_workers()
        
        logger.info(f"✅ Service Bunny Storage initialisé (Library: {self.config.library_id})")
    
    def _start_workers(self):
        """Démarre les workers d'upload"""
        for i in range(self.config.max_concurrent_uploads):
            self.executor.submit(self._upload_worker, f"worker_{i}")
    
    def _upload_worker(self, worker_name: str):
        """Worker qui traite les uploads en continu"""
        logger.info(f"🚀 Worker {worker_name} démarré")
        
        while self.is_running:
            try:
                # Récupérer la prochaine tâche (timeout pour permettre shutdown)
                task = self.upload_queue.get(timeout=5)
                
                if task is None:  # Signal d'arrêt
                    break
                
                logger.info(f"📤 {worker_name} commence upload: {task.title}")
                self._process_upload(task, worker_name)
                
                self.upload_queue.task_done()
                
            except Empty:
                continue  # Timeout normal, continuer
            except Exception as e:
                logger.error(f"❌ Erreur worker {worker_name}: {e}")
                time.sleep(1)
    
    def _process_upload(self, task: UploadTask, worker_name: str):
        """Traite un upload individuel avec retry automatique"""
        
        with self._lock:
            self.active_uploads[task.id] = task
            self.stats['uploads_started'] += 1
        
        success = False
        
        while task.retries <= self.config.max_retries and not success:
            try:
                if task.retries > 0:
                    task.update_status(UploadStatus.RETRYING)
                    delay = self.config.retry_delay * (2 ** task.retries)  # Backoff exponentiel
                    logger.info(f"⏳ Retry {task.retries}/{self.config.max_retries} dans {delay}s: {task.title}")
                    time.sleep(delay)
                
                task.update_status(UploadStatus.UPLOADING)
                success = self._upload_file_to_bunny(task, worker_name)
                
                if success:
                    task.update_status(UploadStatus.COMPLETED)
                    logger.info(f"✅ Upload réussi: {task.title} -> {task.bunny_url}")
                    
                    with self._lock:
                        self.stats['uploads_completed'] += 1
                        self.stats['bytes_uploaded'] += task.get_file_size()
                    
                    # ⚠️ DISABLED: Database update now handled by recording routes
                    # to prevent duplicate video records
                    # self._update_database(task)
                    logger.info(f"📝 Bunny video ID: {task.bunny_video_id} (handled by recording route)")
                    
                    
                else:
                    task.increment_retry()
                    
            except Exception as e:
                logger.error(f"❌ Erreur upload {task.title}: {e}")
                task.update_status(UploadStatus.FAILED, str(e))
                task.increment_retry()
        
        if not success:
            task.update_status(UploadStatus.FAILED, f"Échec après {self.config.max_retries} tentatives")
            logger.error(f"❌ Upload définitivement échoué: {task.title}")
            
            with self._lock:
                self.stats['uploads_failed'] += 1
        
        # Déplacer vers completed
        with self._lock:
            if task.id in self.active_uploads:
                del self.active_uploads[task.id]
            self.completed_uploads[task.id] = task
    
    def _upload_file_to_bunny(self, task: UploadTask, worker_name: str) -> bool:
        """Upload effectif vers Bunny CDN avec gestion des chunks"""
        
        try:
            # Vérifier que le fichier existe
            if not Path(task.local_path).exists():
                task.error_message = "Fichier introuvable"
                return False
            
            task.total_bytes = task.get_file_size()
            
            # 1. Créer la vidéo sur Bunny Stream
            logger.debug(f"📝 {worker_name}: Création vidéo Bunny: {task.title}")
            
            create_response = requests.post(
                f"{self.config.api_base_url}/videos",
                headers=self.config.headers,
                json={"title": task.title},
                timeout=30
            )
            
            if create_response.status_code not in [200, 201]:
                task.error_message = f"Erreur création: {create_response.status_code} - {create_response.text}"
                return False
            
            video_data = create_response.json()
            task.bunny_video_id = video_data.get("guid")
            
            if not task.bunny_video_id:
                task.error_message = "Pas d'ID vidéo retourné"
                return False
            
            # 2. Upload du fichier
            logger.debug(f"📤 {worker_name}: Upload fichier {task.local_path}")
            
            upload_headers = {
                "AccessKey": self.config.api_key,
                "Content-Type": "application/octet-stream"
            }
            
            upload_url = f"{self.config.api_base_url}/videos/{task.bunny_video_id}"
            
            with open(task.local_path, 'rb') as file:
                # Upload avec monitoring de progression
                upload_response = requests.put(
                    upload_url,
                    headers=upload_headers,
                    data=self._file_iterator(file, task),
                    timeout=self.config.timeout
                )
            
            if upload_response.status_code not in [200, 201, 204]:
                task.error_message = f"Erreur upload: {upload_response.status_code} - {upload_response.text}"
                return False
            
            # 3. Générer l'URL finale
            task.bunny_url = f"https://{self.config.cdn_hostname}/{task.bunny_video_id}/play.mp4"
            
            return True
            
        except requests.exceptions.RequestException as e:
            task.error_message = f"Erreur réseau: {str(e)}"
            return False
        except Exception as e:
            task.error_message = f"Erreur inattendue: {str(e)}"
            return False
    
    def _file_iterator(self, file, task: UploadTask):
        """Itérateur de fichier avec suivi de progression"""
        while True:
            chunk = file.read(self.config.chunk_size)
            if not chunk:
                break
            
            task.bytes_uploaded += len(chunk)
            
            # Log de progression (tous les 10MB)
            if task.bytes_uploaded % (10 * 1024 * 1024) == 0:
                progress = (task.bytes_uploaded / task.total_bytes) * 100
                logger.debug(f"📊 Upload {task.title}: {progress:.1f}%")
            
            yield chunk
    
    def _update_database(self, task: UploadTask):
        """Met à jour la base de données avec l'URL Bunny - Version corrigée"""
        if 'video_id' not in task.metadata:
            logger.warning("⚠️ video_id manquant dans metadata - création nouvelle vidéo")
            return self._create_new_video_record(task)
        
        try:
            # Import local pour éviter les dépendances circulaires
            import sys
            sys.path.append(os.path.dirname(os.path.dirname(__file__)))
            
            from flask import Flask
            from models.database import db
            from models.user import Video
            
            # Créer un contexte d'application minimal
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            
            db.init_app(app)
            
            with app.app_context():
                video_id = task.metadata['video_id']
                
                # CORRECTION: Vérifier si video_id est valide avant la requête
                if not video_id or video_id == 'None' or video_id is None:
                    logger.warning("⚠️ video_id est None - création nouvelle vidéo")
                    return self._create_new_video_record(task)
                
                try:
                    video = Video.query.get(video_id)
                    
                    if video:
                        video.file_url = task.bunny_url
                        video.bunny_video_id = task.bunny_video_id
                        video.status = "completed"
                        video.uploaded_at = datetime.utcnow()
                        db.session.commit()
                        logger.info(f"✅ URL vidéo {video_id} mise à jour: {task.bunny_url}")
                    else:
                        logger.warning(f"⚠️ Vidéo {video_id} non trouvée en BDD - création nouvelle")
                        return self._create_new_video_record(task)
                        
                except Exception as db_error:
                    logger.error(f"❌ Erreur requête BDD: {db_error}")
                    return self._create_new_video_record(task)
                    
        except Exception as e:
            logger.error(f"❌ Erreur mise à jour BDD: {e}")
            return self._create_new_video_record(task)
    
    def _create_new_video_record(self, task: UploadTask):
        """Crée un nouvel enregistrement vidéo quand video_id est NULL ou invalide"""
        try:
            logger.info("🆕 Création nouveau record vidéo en BDD")
            
            # Import local
            import sys
            sys.path.append(os.path.dirname(os.path.dirname(__file__)))
            
            from flask import Flask
            from models.database import db
            from models.user import Video
            
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            
            db.init_app(app)
            
            with app.app_context():
                # Générer titre basé sur filename
                filename = os.path.basename(task.local_path)
                title = filename.replace('.mp4', '').replace('_', ' ').title()
                
                new_video = Video(
                    title=title,
                    description=f"Enregistrement automatique - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                    file_url=task.bunny_url,
                    user_id=task.metadata.get('user_id', 1),
                    court_id=task.metadata.get('court_id', 1),
                    duration=task.metadata.get('duration', 0),
                    file_size=os.path.getsize(task.local_path) if os.path.exists(task.local_path) else 0,
                    recorded_at=datetime.utcnow(),
                    created_at=datetime.utcnow()
                )
                
                db.session.add(new_video)
                db.session.commit()
                
                logger.info(f"✅ Nouvelle vidéo créée: ID={new_video.id}, URL={new_video.file_url}")
                
                return {
                    'success': True,
                    'video_id': new_video.id,
                    'url': new_video.file_url
                }
                
        except Exception as e:
            logger.error(f"❌ Erreur création nouveau record: {e}")
            return {'success': False, 'error': str(e)}
    
    # API publique
    
    def queue_upload(self, local_path: str, title: str = None, metadata: Dict = None) -> str:
        """
        Ajoute un fichier à la queue d'upload.
        
        Args:
            local_path: Chemin local du fichier
            title: Titre de la vidéo
            metadata: Métadonnées (ex: video_id pour BDD)
        
        Returns:
            ID de la tâche d'upload
        """
        
        if not Path(local_path).exists():
            raise FileNotFoundError(f"Fichier introuvable: {local_path}")
        
        task = UploadTask(local_path, title, metadata)
        self.upload_queue.put(task)
        
        logger.info(f"📋 Tâche ajoutée à la queue: {task.title} (ID: {task.id})")
        return task.id
    
    def upload_immediately(self, local_path: str, title: str = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Upload synchrone immédiat d'un fichier.
        
        Returns:
            Tuple (success, video_id, video_url)
        """
        task = UploadTask(local_path, title)
        
        if self._upload_file_to_bunny(task, "immediate"):
            return True, task.bunny_video_id, task.bunny_url
        else:
            return False, None, task.error_message
    
    def get_upload_status(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Retourne le statut d'un upload"""
        
        # Chercher dans les uploads actifs
        if upload_id in self.active_uploads:
            task = self.active_uploads[upload_id]
        elif upload_id in self.completed_uploads:
            task = self.completed_uploads[upload_id]
        else:
            return None
        
        progress = 0
        if task.total_bytes > 0:
            progress = (task.bytes_uploaded / task.total_bytes) * 100
        
        return {
            'id': task.id,
            'status': task.status,
            'title': task.title,
            'progress': progress,
            'retries': task.retries,
            'bunny_video_id': task.bunny_video_id,
            'bunny_url': task.bunny_url,
            'error_message': task.error_message,
            'created_at': task.created_at.isoformat(),
            'started_at': task.started_at.isoformat() if task.started_at else None,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du service"""
        with self._lock:
            return {
                **self.stats,
                'active_uploads': len(self.active_uploads),
                'queue_size': self.upload_queue.qsize(),
                'completed_uploads': len(self.completed_uploads)
            }
    
    def shutdown(self):
        """Arrête proprement le service"""
        logger.info("🛑 Arrêt du service Bunny Storage...")
        
        self.is_running = False
        
        # Arrêter les workers
        for _ in range(self.config.max_concurrent_uploads):
            self.upload_queue.put(None)  # Signal d'arrêt
        
        # Attendre la fin des uploads en cours
        self.executor.shutdown(wait=True)
        
        logger.info("✅ Service Bunny Storage arrêté")


# Instance globale du service
bunny_storage_service = BunnyStorageService()
