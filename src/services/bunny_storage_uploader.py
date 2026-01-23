"""
Service pour uploader des fichiers vers Bunny Storage
Utilisé pour les clips MP4 téléchargeables (en complément de Bunny Stream)
"""

import os
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BunnyStorageUploader:
    """Upload de fichiers vers Bunny Storage via l'API"""
    
    def __init__(self):
        # Credentials depuis variables d'environnement
        self.storage_zone = os.environ.get('BUNNY_STORAGE_ZONE', 'mysmash-2026')
        self.hostname = "storage.bunnycdn.com"
        self.access_key = os.environ.get('BUNNY_STORAGE_PASSWORD')
        
        # Validation
        if not self.access_key:
            raise ValueError("BUNNY_STORAGE_PASSWORD manquant dans .env!")
        
        # Base URL pour l'API Storage
        self.base_url = f"https://{self.hostname}/{self.storage_zone}"
    
    def upload_clip(self, file_path: str, filename: str) -> str:
        """
        Upload un clip MP4 vers Bunny Storage
        
        Args:
            file_path: Chemin local du fichier
            filename: Nom du fichier de destination
            
        Returns:
            str: URL publique CDN du fichier uploadé
            
        Raises:
            Exception: Si l'upload échoue
        """
        try:
            # Créer le chemin de destination (dossier clips/)
            remote_path = f"clips/{filename}"
            upload_url = f"{self.base_url}/{remote_path}"
            
            logger.info(f"📤 Uploading to Bunny Storage: {remote_path}")
            
            # Lire le fichier
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            # Headers pour l'authentification
            headers = {
                'AccessKey': self.access_key,
                'Content-Type': 'application/octet-stream'
            }
            
            # Upload via PUT request avec timeout augmenté à 2h (comme vidéos)
            timeout = int(os.environ.get('BUNNY_UPLOAD_TIMEOUT', '7200'))
            response = requests.put(
                upload_url,
                headers=headers,
                data=file_data,
                timeout=timeout
            )
            
            response.raise_for_status()
            
            # Construire l'URL publique CDN
            # Format: https://mysmash-2026.b-cdn.net/clips/filename.mp4
            cdn_url = f"https://{self.storage_zone}.b-cdn.net/{remote_path}"
            
            logger.info(f"✅ Upload successful: {cdn_url}")
            return cdn_url
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Bunny Storage upload failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise Exception(f"Failed to upload to Bunny Storage: {str(e)}")
    
    def delete_clip(self, filename: str) -> bool:
        """
        Supprime un clip de Bunny Storage
        
        Args:
            filename: Nom du fichier à supprimer
            
        Returns:
            bool: True si succès
        """
        try:
            remote_path = f"clips/{filename}"
            delete_url = f"{self.base_url}/{remote_path}"
            
            headers = {
                'AccessKey': self.access_key
            }
            
            response = requests.delete(delete_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            logger.info(f"🗑️ Deleted from Bunny Storage: {remote_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to delete from Bunny Storage: {e}")
            return False


# Instance globale
bunny_storage_uploader = BunnyStorageUploader()


def upload_clip_to_storage(file_path: str, filename: str) -> str:
    """Helper function pour uploader un clip"""
    return bunny_storage_uploader.upload_clip(file_path, filename)


def delete_clip_from_storage(filename: str) -> bool:
    """Helper function pour supprimer un clip"""
    return bunny_storage_uploader.delete_clip(filename)
