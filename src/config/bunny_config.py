"""
Configuration centralisée pour Bunny CDN
Gère les paramètres de connexion et les optimisations
"""

import os
from typing import Dict, Any


class BunnyConfig:
    """Configuration Bunny CDN avec validation et optimisations"""
    
    # Configuration par défaut (sync avec bunny_storage_service.py L27-29)
    DEFAULT_CONFIG = {
        'api_key': '4771e914-172d-4abf-aac6e0518b34-44f2-48cd',  # Updated 2026-01-13
        'library_id': '579861',  # Updated 2026-01-13
        'cdn_hostname': 'vz-cc4565cd-4e9.b-cdn.net',  # Updated 2026-01-14
        'storage_zone': 'padel-videos',
        'timeout': 300,  # 5 minutes
        'max_retries': 3,
        'chunk_size': 8 * 1024 * 1024,  # 8MB
        'max_concurrent_uploads': 2
    }
    
    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """Charge la configuration depuis les variables d'environnement"""
        config = {}
        
        # Charger depuis l'environnement avec fallback
        config['api_key'] = os.environ.get('BUNNY_API_KEY', cls.DEFAULT_CONFIG['api_key'])
        config['library_id'] = os.environ.get('BUNNY_LIBRARY_ID', cls.DEFAULT_CONFIG['library_id'])
        config['cdn_hostname'] = os.environ.get('BUNNY_CDN_HOSTNAME', cls.DEFAULT_CONFIG['cdn_hostname'])
        config['storage_zone'] = os.environ.get('BUNNY_STORAGE_ZONE', cls.DEFAULT_CONFIG['storage_zone'])
        
        # Paramètres numériques avec validation
        try:
            config['timeout'] = int(os.environ.get('BUNNY_TIMEOUT', cls.DEFAULT_CONFIG['timeout']))
        except (ValueError, TypeError):
            config['timeout'] = cls.DEFAULT_CONFIG['timeout']
            
        try:
            config['max_retries'] = int(os.environ.get('BUNNY_MAX_RETRIES', cls.DEFAULT_CONFIG['max_retries']))
        except (ValueError, TypeError):
            config['max_retries'] = cls.DEFAULT_CONFIG['max_retries']
            
        try:
            config['chunk_size'] = int(os.environ.get('BUNNY_CHUNK_SIZE', cls.DEFAULT_CONFIG['chunk_size']))
        except (ValueError, TypeError):
            config['chunk_size'] = cls.DEFAULT_CONFIG['chunk_size']
            
        try:
            config['max_concurrent_uploads'] = int(os.environ.get('BUNNY_MAX_CONCURRENT', cls.DEFAULT_CONFIG['max_concurrent_uploads']))
        except (ValueError, TypeError):
            config['max_concurrent_uploads'] = cls.DEFAULT_CONFIG['max_concurrent_uploads']
        
        return config
    
    @classmethod
    def validate_config(cls, config: Dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Valide la configuration Bunny CDN
        
        Returns:
            Tuple (is_valid, errors)
        """
        errors = []
        
        # Vérifier API key
        api_key = config.get('api_key', '')
        if not api_key or len(api_key) < 10:
            errors.append("API key manquante ou invalide")
        
        # Vérifier Library ID
        library_id = config.get('library_id', '')
        if not library_id or not str(library_id).isdigit():
            errors.append("Library ID manquant ou invalide")
        
        # Vérifier CDN hostname
        cdn_hostname = config.get('cdn_hostname', '')
        if not cdn_hostname or '.' not in cdn_hostname:
            errors.append("CDN hostname manquant ou invalide")
        
        # Vérifier les valeurs numériques
        numeric_fields = ['timeout', 'max_retries', 'chunk_size', 'max_concurrent_uploads']
        for field in numeric_fields:
            value = config.get(field, 0)
            if not isinstance(value, int) or value <= 0:
                errors.append(f"{field} doit être un entier positif")
        
        return len(errors) == 0, errors
    
    @classmethod
    def get_api_headers(cls, config: Dict[str, Any]) -> Dict[str, str]:
        """Retourne les headers pour l'API Bunny"""
        return {
            "AccessKey": config['api_key'],
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
    
    @classmethod
    def get_upload_headers(cls, config: Dict[str, Any]) -> Dict[str, str]:
        """Retourne les headers pour l'upload de fichiers"""
        return {
            "AccessKey": config['api_key'],
            "Content-Type": "application/octet-stream"
        }
    
    @classmethod
    def get_api_url(cls, config: Dict[str, Any], endpoint: str = "") -> str:
        """Construit l'URL de l'API"""
        base_url = f"https://video.bunnycdn.com/library/{config['library_id']}"
        if endpoint:
            return f"{base_url}/{endpoint.lstrip('/')}"
        return base_url
    
    @classmethod
    def get_video_url(cls, config: Dict[str, Any], video_id: str) -> str:
        """Construit l'URL de visualisation d'une vidéo"""
        return f"https://{config['cdn_hostname']}/{video_id}/play.mp4"
    
    @classmethod
    def generate_signed_url(cls, config: Dict[str, Any], video_id: str, 
                           expiration_time: int = 3600, 
                           security_key: str = None) -> str:
        """
        Génère une URL signée pour le téléchargement sécurisé depuis Bunny CDN
        
        Args:
            config: Configuration Bunny
            video_id: ID de la vidéo Bunny
            expiration_time: Durée de validité en secondes (défaut: 1 heure)
            security_key: Clé de sécurité Token Authentication (optionnel)
                         Si None, essaie BUNNY_TOKEN_SECURITY_KEY depuis l'environnement
        
        Returns:
            URL signée avec token d'authentification
        """
        import hashlib
        import time
        from urllib.parse import quote
        
        # Récupérer la clé de sécurité
        if security_key is None:
            security_key = os.environ.get('BUNNY_TOKEN_SECURITY_KEY', '')
        
        # Si pas de clé de sécurité, retourner l'URL sans signature
        if not security_key:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning("⚠️ BUNNY_TOKEN_SECURITY_KEY not configured, using unsigned URL")
            return cls.get_video_url(config, video_id)
        
        # Calculer le timestamp d'expiration
        expires = int(time.time()) + expiration_time
        
        # Construire l'URL de base
        base_path = f"/{video_id}/play.mp4"
        
        # Créer la chaîne à signer: security_key + path + expires
        sign_string = f"{security_key}{base_path}{expires}"
        
        # Générer le hash MD5 (Bunny utilise MD5 pour les tokens)
        token = hashlib.md5(sign_string.encode()).hexdigest()
        
        # Construire l'URL signée
        signed_url = f"https://{config['cdn_hostname']}{base_path}?token={token}&expires={expires}"
        
        return signed_url


# Configuration globale chargée au démarrage
BUNNY_CONFIG = BunnyConfig.load_config()
is_valid, validation_errors = BunnyConfig.validate_config(BUNNY_CONFIG)

if not is_valid:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️ Configuration Bunny CDN invalide: {validation_errors}")
