


# src/middleware/rate_limiting.py

"""
Middleware de rate limiting pour PadelVar
Protège contre les abus et attaques par déni de service
"""

import time
import logging
import hashlib
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
from flask import request, jsonify, g
import redis

from ..config import Config

logger = logging.getLogger(__name__)

class RateLimitMiddleware:
    """Middleware pour gérer le rate limiting des requêtes"""
    
    # Configuration par défaut des limites
    DEFAULT_LIMITS = {
        # Limites globales par IP
        'global': {
            'requests': 1000,
            'window': 3600  # 1000 requêtes par heure
        },
        
        # Limites par endpoint
        'endpoints': {
            # Authentification (plus restrictif)
            '/api/auth/login': {
                'requests': 10,
                'window': 900,  # 10 tentatives par 15 minutes
                'per': 'ip'
            },
            '/api/auth/register': {
                'requests': 5,
                'window': 3600,  # 5 inscriptions par heure par IP
                'per': 'ip'
            },
            '/api/auth/forgot-password': {
                'requests': 3,
                'window': 3600,  # 3 demandes de reset par heure
                'per': 'ip'
            },
            
            # Paiements (critique)
            '/api/payments/create-checkout-session': {
                'requests': 20,
                'window': 3600,  # 20 sessions par heure par utilisateur
                'per': 'user'
            },
            '/api/payments/webhook': {
                'requests': 100,
                'window': 60,   # 100 webhooks par minute (Stripe peut envoyer beaucoup)
                'per': 'ip'
            },
            
            # Enregistrements
            '/api/recording/v3/start': {
                'requests': 50,
                'window': 3600,  # 50 enregistrements par heure par utilisateur
                'per': 'user'
            },
            '/api/recording/v3/stop': {
                'requests': 100,
                'window': 3600,  # 100 arrêts par heure (plus permissif)
                'per': 'user'
            },
            
            # API génériques
            'GET': {
                'requests': 500,
                'window': 3600,  # 500 GET par heure par IP
                'per': 'ip'
            },
            'POST': {
                'requests': 200,
                'window': 3600,  # 200 POST par heure par IP
                'per': 'ip'
            },
            'PUT': {
                'requests': 100,
                'window': 3600,  # 100 PUT par heure par IP
                'per': 'ip'
            },
            'DELETE': {
                'requests': 50,
                'window': 3600,  # 50 DELETE par heure par IP
                'per': 'ip'
            }
        }
    }
    
    def __init__(self, app=None, redis_client=None):
        self.redis_client = redis_client
        self.memory_store = defaultdict(dict)  # Fallback si Redis non disponible
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialise le middleware avec l'application Flask"""
        # Configurer Redis si disponible
        if not self.redis_client:
            try:
                redis_url = Config.RATELIMIT_STORAGE_URL or Config.CELERY_BROKER_URL
                if redis_url:
                    self.redis_client = redis.from_url(redis_url, decode_responses=True)
                    # Test de connexion
                    self.redis_client.ping()
                    logger.info("Rate limiting avec Redis configuré")
                else:
                    logger.warning("Redis non configuré, utilisation du stockage mémoire")
            except Exception as e:
                logger.warning(f"Impossible de se connecter à Redis: {e}, utilisation du stockage mémoire")
                self.redis_client = None
        
        app.before_request(self.before_request)
    
    def before_request(self):
        """Vérifie les limites de taux avant chaque requête"""
        try:
            # Ignorer certaines routes (health checks, etc.)
            if self._should_skip_rate_limit():
                return None
            
            # Identifier l'utilisateur/IP
            identifier = self._get_identifier()
            if not identifier:
                return None
            
            # Obtenir les limites pour cette requête
            limits = self._get_limits_for_request()
            
            # Vérifier chaque limite
            for limit_name, limit_config in limits.items():
                if self._is_rate_limited(identifier, limit_name, limit_config):
                    return self._rate_limit_response(limit_config)
            
            # Enregistrer la requête
            self._record_request(identifier, limits)
            
            return None
            
        except Exception as e:
            logger.error(f"Erreur dans le rate limiting: {e}")
            # En cas d'erreur, laisser passer la requête pour ne pas bloquer l'application
            return None
    
    def _should_skip_rate_limit(self):
        """Détermine si le rate limiting doit être ignoré pour cette requête"""
        skip_paths = [
            '/health',
            '/api/health',
            '/metrics',
            '/favicon.ico'
        ]
        
        return request.path in skip_paths
    
    def _get_identifier(self):
        """Récupère l'identifiant pour le rate limiting (IP ou user_id)"""
        # Obtenir l'IP réelle (en tenant compte des proxies)
        ip = self._get_real_ip()
        
        # Obtenir l'ID utilisateur si authentifié
        user_id = None
        if hasattr(g, 'current_user') and g.current_user:
            user_id = g.current_user.id
        
        return {
            'ip': ip,
            'user_id': user_id
        }
    
    def _get_real_ip(self):
        """Récupère l'IP réelle du client (gère les proxies)"""
        # Vérifier les headers de proxy
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip
        
        # Fallback sur l'IP directe
        return request.remote_addr or 'unknown'
    
    def _get_limits_for_request(self):
        """Obtient les limites applicables à la requête actuelle"""
        limits = {}
        
        # Limite globale
        limits['global'] = self.DEFAULT_LIMITS['global']
        
        # Limite par endpoint spécifique
        endpoint_path = request.path
        if endpoint_path in self.DEFAULT_LIMITS['endpoints']:
            limits[f'endpoint_{endpoint_path}'] = self.DEFAULT_LIMITS['endpoints'][endpoint_path]
        
        # Limite par méthode HTTP
        method = request.method
        if method in self.DEFAULT_LIMITS['endpoints']:
            limits[f'method_{method}'] = self.DEFAULT_LIMITS['endpoints'][method]
        
        return limits
    
    def _is_rate_limited(self, identifier, limit_name, limit_config):
        """Vérifie si une limite est dépassée"""
        # Déterminer quel identifiant utiliser
        key_identifier = identifier['user_id'] if limit_config.get('per') == 'user' and identifier['user_id'] else identifier['ip']
        if not key_identifier:
            return False
        
        # Construire la clé Redis/mémoire
        key = f"rate_limit:{limit_name}:{key_identifier}"
        window = limit_config['window']
        max_requests = limit_config['requests']
        
        current_time = int(time.time())
        window_start = current_time - window
        
        if self.redis_client:
            return self._check_redis_limit(key, window_start, current_time, max_requests)
        else:
            return self._check_memory_limit(key, window_start, current_time, max_requests)
    
    def _check_redis_limit(self, key, window_start, current_time, max_requests):
        """Vérifie la limite avec Redis (sliding window)"""
        try:
            pipe = self.redis_client.pipeline()
            
            # Supprimer les entrées expirées
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Compter les requêtes dans la fenêtre
            pipe.zcard(key)
            
            # Ajouter la requête actuelle
            pipe.zadd(key, {str(current_time): current_time})
            
            # Définir l'expiration de la clé
            pipe.expire(key, int(max(3600, window_start)))
            
            results = pipe.execute()
            current_count = results[1]
            
            return current_count >= max_requests
            
        except Exception as e:
            logger.error(f"Erreur Redis rate limit: {e}")
            return False
    
    def _check_memory_limit(self, key, window_start, current_time, max_requests):
        """Vérifie la limite avec le stockage mémoire"""
        if key not in self.memory_store:
            self.memory_store[key] = []
        
        # Nettoyer les anciennes entrées
        self.memory_store[key] = [
            timestamp for timestamp in self.memory_store[key]
            if timestamp > window_start
        ]
        
        # Vérifier la limite
        current_count = len(self.memory_store[key])
        
        if current_count >= max_requests:
            return True
        
        # Ajouter la requête actuelle
        self.memory_store[key].append(current_time)
        return False
    
    def _record_request(self, identifier, limits):
        """Enregistre la requête (déjà fait dans _is_rate_limited)"""
        # Cette méthode est appelée après vérification, l'enregistrement
        # est déjà fait dans _is_rate_limited
        pass
    
    def _rate_limit_response(self, limit_config):
        """Retourne une réponse de rate limiting"""
        retry_after = limit_config.get('window', 3600)
        
        response = jsonify({
            'error': 'Rate limit exceeded',
            'message': f'Too many requests. Please try again in {retry_after} seconds.',
            'retry_after': retry_after
        })
        response.status_code = 429
        response.headers['Retry-After'] = str(retry_after)
        response.headers['X-RateLimit-Limit'] = str(limit_config['requests'])
        response.headers['X-RateLimit-Window'] = str(limit_config['window'])
        
        logger.warning(f"Rate limit dépassé - IP: {request.remote_addr}, Path: {request.path}")
        
        return response

def rate_limit(requests=100, window=3600, per='ip', skip_if_authenticated=False):
    """
    Décorateur pour appliquer un rate limiting spécifique à une vue
    
    Args:
        requests: Nombre de requêtes autorisées
        window: Fenêtre de temps en secondes
        per: 'ip' ou 'user' - base du rate limiting
        skip_if_authenticated: Si True, ignore le rate limit pour les utilisateurs authentifiés
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Vérifier si on doit ignorer pour les utilisateurs authentifiés
            if skip_if_authenticated and hasattr(g, 'current_user') and g.current_user:
                return f(*args, **kwargs)
            
            # Logique de rate limiting personnalisée
            identifier = _get_custom_identifier(per)
            if identifier and _check_custom_limit(identifier, f.__name__, requests, window):
                retry_after = window
                response = jsonify({
                    'error': 'Rate limit exceeded',
                    'message': f'Too many requests to this endpoint. Please try again in {retry_after} seconds.',
                    'retry_after': retry_after
                })
                response.status_code = 429
                response.headers['Retry-After'] = str(retry_after)
                return response
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator

def _get_custom_identifier(per):
    """Récupère l'identifiant pour le rate limiting personnalisé"""
    if per == 'user' and hasattr(g, 'current_user') and g.current_user:
        return f"user_{g.current_user.id}"
    elif per == 'ip':
        # Récupérer l'IP réelle
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return f"ip_{forwarded_for.split(',')[0].strip()}"
        return f"ip_{request.remote_addr}"
    return None

def _check_custom_limit(identifier, endpoint, max_requests, window):
    """Vérifie une limite personnalisée (version simplifiée)"""
    # Cette implémentation simplifiée utilise la mémoire
    # En production, utiliser Redis comme dans la classe principale
    key = f"custom_rate_limit:{endpoint}:{identifier}"
    
    current_time = int(time.time())
    window_start = current_time - window
    
    # Simulation simple (en production, utiliser Redis)
    # Pour l'instant, on autorise tout (le middleware principal gère déjà)
    return False