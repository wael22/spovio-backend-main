# padelvar-backend/src/models/system_configuration.py

from datetime import datetime
from .database import db
from enum import Enum
import logging
import base64
from cryptography.fernet import Fernet
import os

logger = logging.getLogger(__name__)


class ConfigType(Enum):
    """Types de configuration système"""
    BUNNY_CDN = "bunny_cdn"
    SMTP = "smtp"
    GENERAL = "general"
    PAYMENT = "payment"


class SystemConfiguration(db.Model):
    """Modèle pour stocker les configurations système"""
    __tablename__ = 'system_configuration'
    
    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    config_value = db.Column(db.Text, nullable=True)
    config_type = db.Column(db.Enum(ConfigType), nullable=False, default=ConfigType.GENERAL)
    is_encrypted = db.Column(db.Boolean, default=False)
    description = db.Column(db.String(255), nullable=True)
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Relations
    updated_by_user = db.relationship('User', foreign_keys=[updated_by], backref='config_updates')
    
    # Clé de chiffrement (stockée en variable d'environnement)
    ENCRYPTION_KEY = os.environ.get('CONFIG_ENCRYPTION_KEY', Fernet.generate_key().decode())
    
    def encrypt_value(self, value: str) -> str:
        """Chiffre une valeur sensible"""
        try:
            fernet = Fernet(self.ENCRYPTION_KEY.encode())
            encrypted = fernet.encrypt(value.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Erreur chiffrement: {e}")
            return value
    
    def decrypt_value(self, encrypted_value: str) -> str:
        """Déchiffre une valeur"""
        try:
            fernet = Fernet(self.ENCRYPTION_KEY.encode())
            decoded = base64.b64decode(encrypted_value.encode())
            decrypted = fernet.decrypt(decoded)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Erreur déchiffrement: {e}")
            return encrypted_value
    
    def set_value(self, value: str, encrypt: bool = None):
        """
        Définit la valeur de configuration
        
        Args:
            value: Valeur à stocker
            encrypt: Si True, chiffre la valeur. Si None, utilise self.is_encrypted
        """
        should_encrypt = encrypt if encrypt is not None else self.is_encrypted
        
        if should_encrypt and value:
            self.config_value = self.encrypt_value(value)
            self.is_encrypted = True
        else:
            self.config_value = value
            self.is_encrypted = False
    
    def get_value(self, decrypt: bool = True) -> str:
        """
        Récupère la valeur de configuration
        
        Args:
            decrypt: Si True, déchiffre la valeur si elle est chiffrée
        
        Returns:
            Valeur déchiffrée ou brute
        """
        if not self.config_value:
            return None
        
        if self.is_encrypted and decrypt:
            return self.decrypt_value(self.config_value)
        
        return self.config_value
    
    def to_dict(self, include_value: bool = True, decrypt: bool = False, mask_sensitive: bool = True):
        """
        Convertit en dictionnaire
        
        Args:
            include_value: Inclure la valeur
            decrypt: Déchiffrer la valeur
            mask_sensitive: Masquer les valeurs sensibles (affiche ****)
        """
        result = {
            'id': self.id,
            'config_key': self.config_key,
            'config_type': self.config_type.value,
            'is_encrypted': self.is_encrypted,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by': self.updated_by
        }
        
        if include_value:
            if self.is_encrypted and mask_sensitive and not decrypt:
                # Masquer les valeurs sensibles
                result['config_value'] = '********'
            elif decrypt:
                result['config_value'] = self.get_value(decrypt=True)
            else:
                result['config_value'] = self.config_value
        
        return result
    
    @staticmethod
    def get_config(key: str, default: str = None, decrypt: bool = True) -> str:
        """
        Récupère une configuration système par clé
        
        Args:
            key: Clé de configuration
            default: Valeur par défaut si non trouvée
            decrypt: Déchiffrer si chiffré
        
        Returns:
            Valeur de configuration ou default
        """
        config = SystemConfiguration.query.filter_by(config_key=key).first()
        if config:
            return config.get_value(decrypt=decrypt)
        return default
    
    @staticmethod
    def set_config(key: str, value: str, config_type: ConfigType = ConfigType.GENERAL, 
                   encrypt: bool = False, description: str = None, updated_by: int = None):
        """
        Définit ou met à jour une configuration système
        
        Args:
            key: Clé de configuration
            value: Valeur à stocker
            config_type: Type de configuration
            encrypt: Chiffrer la valeur
            description: Description
            updated_by: ID utilisateur qui met à jour
        
        Returns:
            Instance SystemConfiguration
        """
        config = SystemConfiguration.query.filter_by(config_key=key).first()
        
        if config:
            # Mise à jour
            config.set_value(value, encrypt=encrypt)
            config.config_type = config_type
            config.description = description or config.description
            config.updated_by = updated_by
            config.updated_at = datetime.utcnow()
        else:
            # Création
            config = SystemConfiguration(
                config_key=key,
                config_type=config_type,
                description=description,
                updated_by=updated_by
            )
            config.set_value(value, encrypt=encrypt)
            db.session.add(config)
        
        db.session.commit()
        return config
    
    @staticmethod
    def get_bunny_cdn_config() -> dict:
        """
        Récupère la configuration Bunny CDN complète
        
        Returns:
            Dictionnaire avec les paramètres Bunny CDN
        """
        return {
            'api_key': SystemConfiguration.get_config('bunny_cdn_api_key'),
            'library_id': SystemConfiguration.get_config('bunny_cdn_library_id'),
            'cdn_hostname': SystemConfiguration.get_config('bunny_cdn_hostname'),
            'storage_zone': SystemConfiguration.get_config('bunny_cdn_storage_zone', 'padel-videos'),
        }
    
    @staticmethod
    def set_bunny_cdn_config(api_key: str = None, library_id: str = None, 
                            cdn_hostname: str = None, storage_zone: str = None,
                            updated_by: int = None):
        """
        Définit la configuration Bunny CDN
        
        Args:
            api_key: Clé API Bunny
            library_id: ID de la bibliothèque
            cdn_hostname: Nom d'hôte CDN
            storage_zone: Zone de stockage
            updated_by: ID utilisateur
        """
        if api_key:
            SystemConfiguration.set_config(
                'bunny_cdn_api_key', api_key, 
                ConfigType.BUNNY_CDN, encrypt=True,
                description='Bunny CDN API Key',
                updated_by=updated_by
            )
        
        if library_id:
            SystemConfiguration.set_config(
                'bunny_cdn_library_id', library_id,
                ConfigType.BUNNY_CDN, encrypt=False,
                description='Bunny CDN Library ID',
                updated_by=updated_by
            )
        
        if cdn_hostname:
            SystemConfiguration.set_config(
                'bunny_cdn_hostname', cdn_hostname,
                ConfigType.BUNNY_CDN, encrypt=False,
                description='Bunny CDN Hostname',
                updated_by=updated_by
            )
        
        if storage_zone:
            SystemConfiguration.set_config(
                'bunny_cdn_storage_zone', storage_zone,
                ConfigType.BUNNY_CDN, encrypt=False,
                description='Bunny CDN Storage Zone',
                updated_by=updated_by
            )
