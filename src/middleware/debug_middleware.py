# padelvar-backend/src/middleware/debug_middleware.py

import os
from flask import jsonify
from functools import wraps

def require_debug_mode(f):
    """
    Décorateur pour protéger les endpoints de debug
    Ne permet l'accès qu'en mode développement
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Vérifier si on est en mode debug
        debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
        env = os.environ.get('FLASK_ENV', 'production')
        
        # Permettre seulement en développement local
        if not debug_mode or env == 'production':
            return jsonify({
                'error': 'Endpoint non disponible en production',
                'message': 'Cette fonctionnalité est réservée au développement'
            }), 404
            
        return f(*args, **kwargs)
    return decorated_function

class DebugConfig:
    """Configuration pour les endpoints de debug"""
    
    @staticmethod
    def is_debug_enabled():
        """Vérifie si le mode debug est activé"""
        debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
        env = os.environ.get('FLASK_ENV', 'production')
        return debug_mode and env != 'production'
    
    @staticmethod
    def get_debug_info():
        """Retourne les informations de debug sécurisées"""
        if not DebugConfig.is_debug_enabled():
            return {'debug': False, 'message': 'Debug non disponible'}
            
        return {
            'debug': True,
            'flask_env': os.environ.get('FLASK_ENV', 'production'),
            'flask_debug': os.environ.get('FLASK_DEBUG', 'false'),
            'debug_endpoints_enabled': True
        }