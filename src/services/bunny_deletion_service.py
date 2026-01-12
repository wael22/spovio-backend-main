"""
Service pour la suppression de vidéos sur Bunny Stream CDN
Gère la suppression des vidéos depuis Bunny Stream API
"""

import os
import logging
import requests
from typing import Tuple, Optional

# Configuration du logger
logger = logging.getLogger(__name__)


class BunnyDeletionService:
    """Service de suppression de vidéos sur Bunny Stream CDN"""
    
    def __init__(self):
        """Initialise le service de suppression Bunny Stream"""
        self.api_key = os.environ.get('BUNNY_API_KEY', '1e962f55-b5f8-49e4-a11ee33c4216-2035-4b81')
        self.library_id = os.environ.get('BUNNY_LIBRARY_ID', '573234')
        
        # URLs API
        self.api_base_url = f"https://video.bunnycdn.com/library/{self.library_id}"
        
        # Headers API
        self.headers = {
            "AccessKey": self.api_key,
            "Accept": "application/json"
        }
        
        # Configuration
        self.timeout = 30  # 30 secondes
    
    def delete_video_from_bunny(self, bunny_video_id: str) -> Tuple[bool, Optional[str]]:
        """
        Supprime une vidéo depuis Bunny Stream CDN.
        
        Args:
            bunny_video_id: GUID de la vidéo sur Bunny Stream
        
        Returns:
            Tuple (success, error_message)
            - success: True si la suppression a réussi, False sinon
            - error_message: Message d'erreur si échec, None si succès
        """
        
        if not bunny_video_id:
            error_msg = "bunny_video_id est requis pour supprimer depuis Bunny CDN"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
        
        try:
            logger.info(f"🗑️ Suppression vidéo Bunny CDN: {bunny_video_id}")
            
            # URL de suppression
            delete_url = f"{self.api_base_url}/videos/{bunny_video_id}"
            
            # Requête DELETE vers Bunny Stream API
            response = requests.delete(
                delete_url,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # Vérifier le statut de la réponse
            # 200/204 = succès, 404 = vidéo déjà supprimée (on considère comme succès)
            if response.status_code in [200, 204, 404]:
                if response.status_code == 404:
                    logger.warning(f"⚠️ Vidéo {bunny_video_id} déjà supprimée de Bunny CDN")
                else:
                    logger.info(f"✅ Vidéo {bunny_video_id} supprimée de Bunny CDN")
                return True, None
            
            else:
                error_msg = f"Erreur Bunny API: {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                return False, error_msg
                
        except requests.exceptions.Timeout:
            error_msg = f"Timeout lors de la suppression de {bunny_video_id}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Erreur réseau: {str(e)}"
            logger.error(f"❌ Erreur suppression Bunny CDN: {error_msg}")
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Erreur inattendue: {str(e)}"
            logger.error(f"❌ Erreur suppression Bunny CDN: {error_msg}")
            return False, error_msg


# Instance globale du service
bunny_deletion_service = BunnyDeletionService()
