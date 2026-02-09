"""
Helper utilitaire pour générer des URLs de téléchargement MP4 direct depuis Bunny Stream.

Bunny Stream permet l'accès direct aux fichiers MP4 avec ce format:
https://[cdn-hostname]/[video-guid]/play_[resolution].mp4

Résolutions disponibles avec MP4 fallback activé:
- play_360p.mp4  (360p)
- play_480p.mp4  (480p)
- play_720p.mp4  (720p - max avec MP4 fallback standard)
- play_1080p.mp4 (si encodé en 1080p+)
"""
import os
import logging

logger = logging.getLogger(__name__)


class BunnyMP4UrlHelper:
    """Helper pour générer des URLs MP4 directes depuis Bunny Stream"""
    
    # Résolutions supportées (ordre de meilleure à moindre qualité)
    RESOLUTIONS = ['1080p', '720p', '480p', '360p']
    DEFAULT_RESOLUTION = '720p'  # Défaut basé sur MP4 fallback activé
    
    def __init__(self):
        """Initialiser avec le hostname CDN depuis les variables d'environnement"""
        from src.config.bunny_config import BunnyConfig
        bunny_config = BunnyConfig.load_config()
        self.cdn_hostname = bunny_config.get('cdn_hostname', 'vz-9b857324-07d.b-cdn.net')
        logger.info(f"🔧 BunnyMP4UrlHelper initialisé avec hostname: {self.cdn_hostname}")
    
    def get_mp4_download_url(self, bunny_video_id: str, resolution: str = None) -> str:
        """
        Génère l'URL de téléchargement MP4 direct pour une vidéo Bunny Stream.
        
        Args:
            bunny_video_id: GUID de la vidéo sur Bunny Stream
            resolution: Résolution souhaitée (360p, 480p, 720p, 1080p)
                       Si None, utilise la résolution par défaut (720p)
        
        Returns:
            URL complète du fichier MP4 sur Bunny CDN
            
        Example:
            >>> helper = BunnyMP4UrlHelper()
            >>> url = helper.get_mp4_download_url('abc-123-def', '720p')
            >>> print(url)
            'https://vz-cc4565cd-4e9.b-cdn.net/abc-123-def/play_720p.mp4'
        """
        if not bunny_video_id:
            raise ValueError("bunny_video_id est requis")
        
        # Valider et normaliser la résolution
        resolution = self._validate_resolution(resolution)
        
        # Construire l'URL MP4
        mp4_url = f"https://{self.cdn_hostname}/{bunny_video_id}/play_{resolution}.mp4"
        
        logger.debug(f"📥 URL MP4 générée: {mp4_url}")
        return mp4_url
    
    def get_all_resolutions_urls(self, bunny_video_id: str) -> dict:
        """
        Génère toutes les URLs MP4 disponibles pour une vidéo.
        
        Args:
            bunny_video_id: GUID de la vidéo sur Bunny Stream
            
        Returns:
            Dictionnaire {résolution: url} pour toutes les résolutions disponibles
            
        Example:
            >>> helper = BunnyMP4UrlHelper()
            >>> urls = helper.get_all_resolutions_urls('abc-123-def')
            >>> print(urls)
            {
                '1080p': 'https://...play_1080p.mp4',
                '720p': 'https://...play_720p.mp4',
                '480p': 'https://...play_480p.mp4',
                '360p': 'https://...play_360p.mp4'
            }
        """
        if not bunny_video_id:
            raise ValueError("bunny_video_id est requis")
        
        urls = {}
        for resolution in self.RESOLUTIONS:
            urls[resolution] = self.get_mp4_download_url(bunny_video_id, resolution)
        
        return urls
    
    def _validate_resolution(self, resolution: str = None) -> str:
        """
        Valide et normalise la résolution demandée.
        
        Args:
            resolution: Résolution brute (peut contenir 'p' ou non)
            
        Returns:
            Résolution normalisée (ex: '720p')
        """
        # Si pas de résolution, utiliser la par défaut
        if not resolution:
            return self.DEFAULT_RESOLUTION
        
        # Normaliser (enlever 'p' si présent, puis rajouter)
        resolution = resolution.lower().replace('p', '') + 'p'
        
        # Vérifier que c'est une résolution valide
        if resolution not in self.RESOLUTIONS:
            logger.warning(f"⚠️ Résolution invalide '{resolution}', utilisation de {self.DEFAULT_RESOLUTION}")
            return self.DEFAULT_RESOLUTION
        
        return resolution


# Instance singleton pour utilisation directe
_mp4_helper = None

def get_mp4_url_helper() -> BunnyMP4UrlHelper:
    """Retourne l'instance singleton du helper"""
    global _mp4_helper
    if _mp4_helper is None:
        _mp4_helper = BunnyMP4UrlHelper()
    return _mp4_helper
