"""
Gestionnaire d'upload pour Bunny Stream/Storage
Interface abstraite avec implémentations concrètes
"""
import os
import requests
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoUploader(ABC):
    """Interface abstraite pour l'upload de vidéos"""
    
    @abstractmethod
    def upload(self, file_path: str, 
               metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Upload un fichier vidéo et retourne les informations"""
        pass
    
    @abstractmethod
    def delete(self, video_id: str) -> bool:
        """Supprime une vidéo uploadée"""
        pass


class LocalUploader(VideoUploader):
    """Uploader local (pour développement/fallback)"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip('/')
    
    def upload(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Simule un upload local"""
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Fichier non trouvé: {file_path}")
            
            # Générer une URL locale
            filename = file_path.name
            video_url = f"{self.base_url}/videos/{filename}"
            
            logger.info(f"Upload local simulé: {video_url}")
            
            return {
                'success': True,
                'video_id': filename.stem,
                'video_url': video_url,
                'thumbnail_url': f"{self.base_url}/thumbnails/{filename.stem}.jpg",
                'file_size': file_path.stat().st_size,
                'upload_time': time.time()
            }
            
        except Exception as e:
            logger.error(f"Erreur upload local: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def delete(self, video_id: str) -> bool:
        """Suppression locale (no-op pour le développement)"""
        logger.info(f"Suppression locale simulée: {video_id}")
        return True


class BunnyStreamUploader(VideoUploader):
    """Uploader pour Bunny Stream"""
    
    def __init__(self, api_key: str, library_id: str, 
                 base_url: str = "https://video.bunnycdn.com"):
        self.api_key = api_key
        self.library_id = library_id
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'AccessKey': api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })
    
    def upload(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Upload vers Bunny Stream avec retry automatique"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                result = self._upload_attempt(file_path, metadata)
                if result['success']:
                    return result
                    
                logger.warning(f"Tentative {attempt + 1} échouée: {result.get('error')}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))  # Backoff exponentiel
                    
            except Exception as e:
                logger.error(f"Erreur tentative {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
        
        return {
            'success': False,
            'error': f'Upload échoué après {max_retries} tentatives'
        }
    
    def _upload_attempt(self, file_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Une tentative d'upload vers Bunny Stream"""
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                raise FileNotFoundError(f"Fichier non trouvé: {file_path}")
            
            # Étape 1: Créer la vidéo dans Bunny Stream
            video_data = {
                'title': metadata.get('title', file_path.stem),
                'collectionId': metadata.get('collection_id', ''),
                'thumbnailTime': metadata.get('thumbnail_time', 10)
            }
            
            create_url = f"{self.base_url}/library/{self.library_id}/videos"
            response = self.session.post(create_url, json=video_data)
            response.raise_for_status()
            
            video_info = response.json()
            video_id = video_info['guid']
            
            logger.info(f"Vidéo créée dans Bunny Stream: {video_id}")
            
            # Étape 2: Upload du fichier
            upload_url = f"{self.base_url}/library/{self.library_id}/videos/{video_id}"
            
            with open(file_path, 'rb') as f:
                files = {'file': f}
                upload_response = self.session.put(
                    upload_url,
                    files=files,
                    headers={'AccessKey': self.api_key}  # Remplace Content-Type
                )
                upload_response.raise_for_status()
            
            logger.info(f"Fichier uploadé vers Bunny Stream: {video_id}")
            
            # Étape 3: Récupérer les informations finales
            final_info = self._get_video_info(video_id)
            
            return {
                'success': True,
                'video_id': video_id,
                'video_url': final_info.get('video_url', ''),
                'thumbnail_url': final_info.get('thumbnail_url', ''),
                'embed_url': final_info.get('embed_url', ''),
                'file_size': file_path.stat().st_size,
                'upload_time': time.time(),
                'bunny_info': video_info
            }
            
        except requests.RequestException as e:
            error_msg = f"Erreur HTTP Bunny Stream: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg += f" - {error_detail}"
                except:  # noqa: E722
                    error_msg += f" - Status: {e.response.status_code}"
            
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }
            
        except Exception as e:
            logger.error(f"Erreur upload Bunny Stream: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_video_info(self, video_id: str) -> Dict[str, Any]:
        """Récupère les informations d'une vidéo Bunny Stream"""
        try:
            info_url = f"{self.base_url}/library/{self.library_id}/videos/{video_id}"
            response = self.session.get(info_url)
            response.raise_for_status()
            
            video_info = response.json()
            
            return {
                'video_url': video_info.get('videoLibraryId', ''),
                'thumbnail_url': video_info.get('thumbnailUrl', ''),
                'embed_url': f"https://iframe.mediadelivery.net/embed/{self.library_id}/{video_id}",
                'status': video_info.get('status', 0),
                'duration': video_info.get('length', 0)
            }
            
        except Exception as e:
            logger.error(f"Erreur récupération info vidéo {video_id}: {e}")
            return {}
    
    def delete(self, video_id: str) -> bool:
        """Supprime une vidéo de Bunny Stream"""
        try:
            delete_url = f"{self.base_url}/library/{self.library_id}/videos/{video_id}"
            response = self.session.delete(delete_url)
            response.raise_for_status()
            
            logger.info(f"Vidéo supprimée de Bunny Stream: {video_id}")
            return True
            
        except Exception as e:
            logger.error(f"Erreur suppression Bunny Stream {video_id}: {e}")
            return False
    
    def get_upload_progress(self, video_id: str) -> float:
        """Retourne le progrès d'upload/traitement (0.0 à 1.0)"""
        try:
            video_info = self._get_video_info(video_id)
            status = video_info.get('status', 0)
            
            # Statuts Bunny Stream: 0=uploading, 1=processing, 2=finished, 3=failed
            if status >= 2:
                return 1.0
            elif status == 1:
                return 0.8  # En traitement
            else:
                return 0.5  # En upload
                
        except Exception:
            return 0.0


def create_uploader(upload_type: str = 'local', **kwargs) -> VideoUploader:
    """Factory pour créer l'uploader approprié"""
    
    if upload_type.lower() == 'bunny':
        api_key = kwargs.get('api_key') or os.getenv('BUNNY_API_KEY')
        library_id = kwargs.get('library_id') or os.getenv('BUNNY_LIBRARY_ID')
        
        if not api_key or not library_id:
            logger.warning("Bunny credentials manquantes, fallback vers local")
            return LocalUploader()
        
        return BunnyStreamUploader(
            api_key=api_key,
            library_id=library_id,
            base_url=kwargs.get('base_url', 'https://video.bunnycdn.com')
        )
    
    else:
        return LocalUploader(
            base_url=kwargs.get('base_url', 'http://localhost:5000')
        )
