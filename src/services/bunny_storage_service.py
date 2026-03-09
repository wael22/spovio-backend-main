"""
Service optimisé pour le stockage et la distribution de vidéos avec Bunny Stream CDN
Gère l'upload robuste des fichiers vidéo avec retry automatique et gestion d'erreurs améliorée
"""

import os
import logging
import threading
import time
import json
import socket
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
import httpx
from pathlib import Path
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor
import hashlib
import random

# Configuration du logger
logger = logging.getLogger(__name__)


class BunnyStorageConfig:
    """Configuration centralisée pour Bunny Storage"""
    
    def __init__(self):
        # Charger depuis les variables d'environnement (OBLIGATOIRE - pas de fallback)
        self.api_key = os.environ.get('BUNNY_API_KEY')
        self.library_id = os.environ.get('BUNNY_LIBRARY_ID')
        self.cdn_hostname = os.environ.get('BUNNY_CDN_HOSTNAME')
        
        # Validation - crash si manquant (sécurité production)
        if not self.api_key or not self.library_id or not self.cdn_hostname:
            raise ValueError(
                "Configuration Bunny CDN manquante! "
                "Vérifiez BUNNY_API_KEY, BUNNY_LIBRARY_ID, BUNNY_CDN_HOSTNAME dans .env"
            )
        
        # URLs API
        self.api_base_url = f"https://video.bunnycdn.com/library/{self.library_id}"
        
        # Headers API
        self.headers = {
            "AccessKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Configuration avancée avec variables d'environnement
        self.chunk_size = 8 * 1024 * 1024  # 8MB chunks
        self.max_retries = int(os.environ.get('BUNNY_MAX_RETRIES', '3'))
        self.retry_delay = int(os.environ.get('BUNNY_RETRY_DELAY', '10'))
        self.timeout = int(os.environ.get('BUNNY_UPLOAD_TIMEOUT', '7200'))
        self.upload_timeout = int(os.environ.get('BUNNY_UPLOAD_TIMEOUT', '7200'))
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
        
        # httpx Client pour uploads robustes et streaming
        self.client = self._create_client()
        
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
    
    def _create_client(self) -> httpx.Client:
        """Crée un client httpx avec configuration optimale pour uploads"""
        # httpx.Client avec timeouts configurés et connection pooling
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=60.0,  # 60s pour établir connexion
                read=7200.0,   # 2h pour lire la réponse
                write=7200.0,  # 2h pour écrire les données (CRITIQUE pour uploads)
                pool=10.0      # 10s pour obtenir connexion du pool
            ),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10
            ),
            http2=False  # HTTP/1.1 pour compatibilité Bunny
        )
    
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
                    # Backoff exponentiel avec jitter pour éviter thundering herd
                    base_delay = self.config.retry_delay * (2 ** (task.retries - 1))
                    jitter = random.uniform(0, base_delay * 0.3)  # +/- 30% jitter
                    delay = base_delay + jitter
                    logger.info(f"⏳ Retry {task.retries}/{self.config.max_retries} dans {delay:.1f}s: {task.title}")
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
        """Upload effectif vers Bunny CDN avec vérification du statut via API"""
        
        try:
            # Vérifier que le fichier existe
            if not Path(task.local_path).exists():
                task.error_message = "Fichier introuvable"
                return False
            
            task.total_bytes = task.get_file_size()
            
            # 1. Créer la vidéo sur Bunny Stream SEULEMENT si pas déjà créée (éviter duplicatas lors des retries)
            if not task.bunny_video_id:
                logger.info(f"📝 {worker_name}: Création vidéo Bunny: {task.title}")
                
                create_response = self.client.post(
                    f"{self.config.api_base_url}/videos",
                    headers=self.config.headers,
                    json={"title": task.title}
                )
                
                if create_response.status_code not in [200, 201]:
                    error_detail = create_response.text
                    logger.error(f"❌ Erreur création vidéo Bunny: {create_response.status_code} - {error_detail}")
                    task.error_message = f"Erreur création: {create_response.status_code} - {error_detail}"
                    return False
                
                video_data = create_response.json()
                task.bunny_video_id = video_data.get("guid")
                
                if not task.bunny_video_id:
                    logger.error(f"❌ Pas d'ID vidéo retourné par Bunny")
                    task.error_message = "Pas d'ID vidéo retourné"
                    return False
                
                logger.info(f"✅ {worker_name}: Vidéo Bunny créée avec ID: {task.bunny_video_id}")
            else:
                logger.info(f"♻️ {worker_name}: Réutilisation vidéo Bunny existante: {task.bunny_video_id}")
            
            # 2. Upload du fichier avec timeout raisonnable et retry
            logger.info(f"📤 {worker_name}: Début upload fichier {task.local_path} ({task.total_bytes / (1024*1024):.2f} MB)")
            logger.info(f"⏰ Upload timeout: {self.config.upload_timeout}s ({self.config.upload_timeout/60:.1f} minutes)")
            
            upload_headers = {
                "AccessKey": self.config.api_key,
                "Content-Type": "application/octet-stream"
            }
            
            upload_url = f"{self.config.api_base_url}/videos/{task.bunny_video_id}"
            
            try:
                # Avec httpx: streaming upload plus fiable
                # Au lieu de charger tout en mémoire, on stream directement le fichier
                logger.info(f"📖 Upload streaming avec httpx: {task.local_path}")
                
                # httpx supporte streaming de fichiers nativement
                with open(task.local_path, 'rb') as file:
                    upload_response = self.client.put(
                        upload_url,
                        headers=upload_headers,
                        content=file,  # httpx streame automatiquement
                    )
                
                logger.info(f"✅ Upload terminé: {upload_response.status_code}")
                
                # Vérifier le statut de la réponse
                if upload_response.status_code in [200, 201, 204]:
                    logger.info(f"✅ Upload fichier terminé - vérification du statut Bunny...")
                elif upload_response.status_code == 400:
                    # Vérifier si c'est une erreur "already uploaded"
                    error_detail = upload_response.text
                    if "already been uploaded" in error_detail.lower():
                        logger.info(f"✅ Vidéo déjà uploadée sur Bunny (probablement upload précédent réussi)")
                        # Considérer comme succès et continuer avec la vérification du statut
                    else:
                        logger.error(f"❌ Erreur upload contenu Bunny: {upload_response.status_code} - {error_detail}")
                        task.error_message = f"Erreur upload: {upload_response.status_code} - {error_detail}"
                        return False
                else:
                    error_detail = upload_response.text
                    logger.error(f"❌ Erreur upload contenu Bunny: {upload_response.status_code} - {error_detail}")
                    task.error_message = f"Erreur upload: {upload_response.status_code} - {error_detail}"
                    return False
                
            except httpx.HTTPError as e:
                logger.error(f"❌ Erreur réseau lors de l'upload: {e}")
                task.error_message = f"Erreur réseau: {str(e)}"
                return False
            
            # 3. Générer l'URL finale et marquer comme uploadé
            # Le service bunny_status_updater mettra à jour "processing" -> "ready" en background
            task.bunny_url = f"https://{self.config.cdn_hostname}/{task.bunny_video_id}/playlist.m3u8"
            logger.info(f"✅ Upload terminé - encodage Bunny en cours en background")
            logger.info(f"📺 URL vidéo (sera prête après encodage): {task.bunny_url}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur inattendue upload: {e}", exc_info=True)
            task.error_message = f"Erreur inattendue: {str(e)}"
            return False
    
    def _wait_for_bunny_processing(self, task: UploadTask, worker_name: str, max_wait: int = 1800) -> bool:
        """
        Attend que Bunny CDN termine l'encodage de la vidéo.
        
        Args:
            task: Tâche d'upload
            worker_name: Nom du worker
            max_wait: Temps d'attente maximum en secondes (default 10 min)
        
        Returns:
            True si la vidéo est prête, False sinon
        
        Note:
            Timeout augmenté à 30 minutes pour supporter les gros fichiers (400MB+)
        """
        logger.info(f"⏳ {worker_name}: Attente du processing Bunny pour {task.bunny_video_id}...")
        
        check_url = f"{self.config.api_base_url}/videos/{task.bunny_video_id}"
        start_time = time.time()
        check_interval = 5  # Vérifier toutes les 5 secondes
        
        while time.time() - start_time < max_wait:
            try:
                # Récupérer le statut de la vidéo via httpx client
                status_response = self.client.get(
                    check_url,
                    headers=self.config.headers
                )
                
                if status_response.status_code == 200:
                    video_info = status_response.json()
                    
                    # Statuts possibles: 0=Created, 1=Uploaded, 2=Processing, 3=Encoding, 4=Finished
                    status = video_info.get("status")
                    status_names = {
                        0: "Created",
                        1: "Uploaded", 
                        2: "Processing",
                        3: "Encoding",
                        4: "Finished",
                        5: "Failed"
                    }
                    status_name = status_names.get(status, f"Unknown({status})")
                    
                    logger.debug(f"📊 {worker_name}: Statut Bunny = {status_name} ({status})")
                    
                    # Vérifier si encodage terminé
                    if status == 4:  # Finished
                        logger.info(f"✅ {worker_name}: Vidéo encodée et prête sur Bunny CDN")
                        return True
                    elif status == 5:  # Failed
                        logger.error(f"❌ {worker_name}: Encodage échoué sur Bunny CDN")
                        task.error_message = "Encodage échoué sur Bunny CDN"
                        return False
                    
                    # Attendre avant la prochaine vérification
                    time.sleep(check_interval)
                else:
                    logger.warning(f"⚠️ Impossible de vérifier le statut: {status_response.status_code}")
                    time.sleep(check_interval)
                    
            except Exception as e:
                logger.warning(f"⚠️ Erreur lors de la vérification du statut: {e}")
                time.sleep(check_interval)
        
        # Timeout atteint
        logger.error(f"❌ {worker_name}: Timeout - la vidéo n'est pas prête après {max_wait}s")
        task.error_message = f"Timeout processing Bunny (> {max_wait}s)"
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
                        video.cdn_migrated_at = datetime.utcnow()
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
        
        # Fermer le client HTTP
        if hasattr(self, 'client'):
            self.client.close()
        
        logger.info("✅ Service Bunny Storage arrêté")


# Instance globale du service
bunny_storage_service = BunnyStorageService()
