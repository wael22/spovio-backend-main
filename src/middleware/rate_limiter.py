# padelvar-backend/src/middleware/rate_limiter.py

from flask import request, jsonify
from functools import wraps
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Stockage en mémoire des tentatives de connexion
# Format: {ip_address: {'count': int, 'reset_time': datetime, 'blocked_until': datetime}}
login_attempts = {}

# Configuration
RATE_LIMIT_WINDOW = 60  # Fenêtre de 60 secondes
MAX_ATTEMPTS = 5  # Maximum 5 tentatives
BLOCK_DURATION = 300  # Bloquer pendant 5 minutes

def get_client_ip():
    """Récupère l'adresse IP du client"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr

def rate_limit(max_attempts=MAX_ATTEMPTS, window=RATE_LIMIT_WINDOW, block_duration=BLOCK_DURATION):
    """
    Décorateur pour limiter le taux de requêtes par IP
    
    Args:
        max_attempts: Nombre maximum de tentatives autorisées
        window: Fenêtre de temps en secondes
        block_duration: Durée du blocage en secondes après dépassement
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = get_client_ip()
            current_time = datetime.utcnow()
            
            # Nettoyer les anciennes entrées (plus de 1 heure)
            cleanup_old_attempts()
            
            # Vérifier si l'IP est bloquée
            if client_ip in login_attempts:
                attempt_data = login_attempts[client_ip]
                
                # Vérifier si l'IP est actuellement bloquée
                if 'blocked_until' in attempt_data and attempt_data['blocked_until'] > current_time:
                    remaining_seconds = int((attempt_data['blocked_until'] - current_time).total_seconds())
                    logger.warning(f"Tentative de connexion bloquée pour IP: {client_ip}")
                    return jsonify({
                        'error': f'Trop de tentatives échouées. Veuillez réessayer dans {remaining_seconds} secondes.',
                        'retry_after': remaining_seconds
                    }), 429
                
                # Vérifier si la fenêtre de temps est expirée
                if attempt_data['reset_time'] < current_time:
                    # Réinitialiser le compteur
                    login_attempts[client_ip] = {
                        'count': 0,
                        'reset_time': current_time + timedelta(seconds=window)
                    }
            else:
                # Nouvelle IP
                login_attempts[client_ip] = {
                    'count': 0,
                    'reset_time': current_time + timedelta(seconds=window)
                }
            
            # Incrémenter le compteur
            login_attempts[client_ip]['count'] += 1
            
            # Vérifier si la limite est dépassée
            if login_attempts[client_ip]['count'] > max_attempts:
                # Bloquer l'IP
                login_attempts[client_ip]['blocked_until'] = current_time + timedelta(seconds=block_duration)
                logger.warning(f"IP bloquée pour trop de tentatives: {client_ip}")
                return jsonify({
                    'error': f'Trop de tentatives échouées. Compte bloqué pour {block_duration} secondes.',
                    'retry_after': block_duration
                }), 429
            
            # Exécuter la fonction
            response = f(*args, **kwargs)
            
            # Si la connexion réussit (status 200), réinitialiser le compteur
            if hasattr(response, 'status_code') and response.status_code == 200:
                if client_ip in login_attempts:
                    del login_attempts[client_ip]
            
            return response
        
        return decorated_function
    return decorator

def cleanup_old_attempts():
    """Nettoie les tentatives de connexion expirées (plus de 1 heure)"""
    current_time = datetime.utcnow()
    one_hour_ago = current_time - timedelta(hours=1)
    
    # Liste des IPs à supprimer
    ips_to_remove = []
    
    for ip, data in login_attempts.items():
        if data['reset_time'] < one_hour_ago:
            ips_to_remove.append(ip)
    
    # Supprimer les anciennes entrées
    for ip in ips_to_remove:
        del login_attempts[ip]
