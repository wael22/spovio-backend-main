
# Export for import in __init__.py
__all__ = [
    "IdempotenceMiddleware",
    "with_idempotence",
    "require_idempotence_key"
]

"""
Middleware d'idempotence pour les requêtes critiques
Évite les doublons lors de requêtes sensibles (paiements, enregistrements, etc.)
"""

import json
import logging
import uuid
import hashlib
from datetime import datetime, timedelta
from functools import wraps

from flask import request, jsonify, g
from sqlalchemy.exc import IntegrityError

from ..models.database import db
from ..models.user import IdempotencyKey

logger = logging.getLogger(__name__)

class IdempotenceMiddleware:
    """
    Middleware pour gérer l'idempotence des requêtes
    """
    
    DEFAULT_TTL_HOURS = 24  # TTL par défaut pour les clés d'idempotence
    
    @staticmethod
    def generate_key(user_id=None, endpoint=None, data=None):
        """
        Génère une clé d'idempotence unique
        
        Args:
            user_id (int): ID de l'utilisateur (optionnel)
            endpoint (str): Endpoint concerné
            data (dict): Données de la requête pour inclure dans la clé
            
        Returns:
            str: Clé d'idempotence unique
        """
        base_data = {
            'user_id': user_id,
            'endpoint': endpoint,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if data:
            # Inclure les données importantes dans la génération de clé
            base_data.update(data)
        
        # Génération d'UUID basé sur le contenu
        content_string = json.dumps(base_data, sort_keys=True)
        return str(uuid.uuid5(uuid.NAMESPACE_URL, content_string))
    
    @staticmethod
    def generate_key_from_content(content_data, user_id=None):
        """
        Génère une clé d'idempotence basée sur le contenu de la requête
        
        Args:
            content_data (dict): Données de contenu à hasher
            user_id (int): ID utilisateur optionnel
            
        Returns:
            str: Clé d'idempotence basée sur le contenu
        """
        # Créer un hash du contenu
        content_str = json.dumps(content_data, sort_keys=True)
        if user_id:
            content_str = f"{user_id}:{content_str}"
        
        # Générer un hash SHA-256
        content_hash = hashlib.sha256(content_str.encode('utf-8')).hexdigest()[:32]
        
        return f"content_{content_hash}"
    
    @staticmethod
    def store_response(key, user_id, endpoint, status_code, response_body, headers=None, ttl_hours=DEFAULT_TTL_HOURS):
        """
        Stocke la réponse pour une clé d'idempotence
        
        Args:
            key (str): Clé d'idempotence
            user_id (int): ID utilisateur
            endpoint (str): Endpoint
            status_code (int): Code de statut HTTP
            response_body (str): Corps de la réponse JSON
            headers (dict): Headers de la réponse
            ttl_hours (int): Durée de vie en heures
        """
        try:
            expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
            
            idempotency_record = IdempotencyKey(
                key=key,
                user_id=user_id,
                endpoint=endpoint,
                response_status_code=status_code,
                response_body=response_body,
                response_headers=json.dumps(headers) if headers else None,
                expires_at=expires_at
            )
            
            db.session.add(idempotency_record)
            db.session.commit()
            
            logger.info(f"Réponse stockée pour clé d'idempotence: {key}")
            
        except IntegrityError:
            # La clé existe déjà, ce qui est normal dans un contexte concurrent
            db.session.rollback()
            logger.debug(f"Clé d'idempotence déjà existante: {key}")
        except Exception as e:
            logger.error(f"Erreur lors du stockage de la réponse d'idempotence: {e}")
            db.session.rollback()
    
    @staticmethod
    def get_stored_response(key):
        """
        Récupère la réponse stockée pour une clé d'idempotence
        
        Args:
            key (str): Clé d'idempotence
            
        Returns:
            dict|None: Réponse stockée ou None si non trouvée/expirée
        """
        try:
            record = IdempotencyKey.query.filter_by(key=key).first()
            
            if not record:
                return None
            
            # Vérifier si la clé a expiré
            if record.is_expired():
                # Nettoyer la clé expirée
                db.session.delete(record)
                db.session.commit()
                logger.debug(f"Clé d'idempotence expirée supprimée: {key}")
                return None
            
            headers = {}
            if record.response_headers:
                try:
                    headers = json.loads(record.response_headers)
                except:
                    pass
            
            return {
                'status_code': record.response_status_code,
                'response_body': record.response_body,
                'headers': headers,
                'created_at': record.created_at
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la réponse d'idempotence: {e}")
            return None
    
    @staticmethod
    def cleanup_expired_keys():
        """
        Nettoie les clés d'idempotence expirées
        """
        try:
            expired_count = IdempotencyKey.query.filter(
                IdempotencyKey.expires_at < datetime.utcnow()
            ).delete()
            
            db.session.commit()
            
            if expired_count > 0:
                logger.info(f"Nettoyage: {expired_count} clés d'idempotence expirées supprimées")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des clés d'idempotence: {e}")
            db.session.rollback()
            return 0

def with_idempotence(ttl_hours=24, key_fields=None):
    """
    Décorateur pour rendre un endpoint idempotent
    
    Args:
        ttl_hours (int): Durée de vie de la clé en heures
        key_fields (list): Champs de la requête à inclure dans la génération de clé
        
    Usage:
        @with_idempotence(ttl_hours=1, key_fields=['amount', 'package_id'])
        @app.route('/payment', methods=['POST'])
        def create_payment():
            return jsonify({'status': 'success'})
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Vérifier si c'est une méthode qui nécessite l'idempotence
            if request.method not in ['POST', 'PUT', 'PATCH']:
                return f(*args, **kwargs)
            
            # Extraire l'utilisateur actuel s'il existe
            user_id = getattr(g, 'current_user_id', None) if hasattr(g, 'current_user_id') else None
            
            # Données pour la génération de clé
            key_data = {}
            if key_fields and request.is_json:
                request_data = request.get_json() or {}
                key_data = {field: request_data.get(field) for field in key_fields if field in request_data}
            
            # Générer la clé d'idempotence
            endpoint = f"{request.method}:{request.endpoint}"
            idempotence_key = IdempotenceMiddleware.generate_key(
                user_id=user_id,
                endpoint=endpoint,
                data=key_data
            )
            
            return f"{idempotence_key}:{str(uuid.uuid4())[:8]}"
            
            # Vérifier si une réponse existe déjà
            stored_response = IdempotenceMiddleware.get_stored_response(idempotence_key)
            
            if stored_response:
                logger.info(f"Réponse idempotente retournée pour clé: {idempotence_key}")
                
                # Retourner la réponse stockée
                response_body = stored_response['response_body']
                status_code = stored_response['status_code']
                
                try:
                    # Essayer de parser le JSON
                    json_response = json.loads(response_body)
                    response = jsonify(json_response)
                except:
                    # Si ce n'est pas du JSON, retourner tel quel
                    response = response_body
                
                response.status_code = status_code
                
                # Ajouter un header pour indiquer que c'est une réponse idempotente
                response.headers['X-Idempotent'] = 'true'
                response.headers['X-Idempotent-Key'] = idempotence_key
                
                return response
            
            # Stocker la clé pour traçabilité
            g.idempotence_key = idempotence_key
            
            # Exécuter la fonction originale
            try:
                result = f(*args, **kwargs)
                
                # Stocker la réponse si elle est réussie
                if hasattr(result, 'status_code') and result.status_code < 400:
                    response_body = result.get_data(as_text=True)
                    
                    IdempotenceMiddleware.store_response(
                        key=idempotence_key,
                        user_id=user_id,
                        endpoint=endpoint,
                        status_code=result.status_code,
                        response_body=response_body,
                        headers=dict(result.headers),
                        ttl_hours=ttl_hours
                    )
                    
                    # Ajouter des headers informatifs
                    result.headers['X-Idempotent-Key'] = idempotence_key
                
                return result
                
            except Exception as e:
                logger.error(f"Erreur lors de l'exécution de la fonction idempotente: {e}")
                raise
            
        return decorated_function
    return decorator

def require_idempotence_key():
    """
    Décorateur qui exige une clé d'idempotence dans les headers
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            idempotence_key = request.headers.get('Idempotency-Key')
            
            if not idempotence_key:
                return jsonify({
                    'error': 'Idempotency-Key header required',
                    'message': 'Cette requête nécessite une clé d\'idempotence dans le header Idempotency-Key'
                }), 400
            
            # Valider le format UUID
            try:
                uuid.UUID(idempotence_key)
            except ValueError:
                return jsonify({
                    'error': 'Invalid Idempotency-Key format',
                    'message': 'La clé d\'idempotence doit être un UUID valide'
                }), 400
            
            # Vérifier si la clé a déjà été utilisée
            stored_response = IdempotenceMiddleware.get_stored_response(idempotence_key)
            
            if stored_response:
                logger.info(f"Clé d'idempotence déjà utilisée: {idempotence_key}")
                
                response_body = stored_response['response_body']
                status_code = stored_response['status_code']
                
                try:
                    json_response = json.loads(response_body)
                    response = jsonify(json_response)
                except:
                    response = response_body
                
                response.status_code = status_code
                response.headers['X-Idempotent'] = 'true'
                response.headers['X-Idempotent-Key'] = idempotence_key
                
                return response
            
            # Stocker la clé pour utilisation dans la fonction
            g.idempotence_key = idempotence_key
            
            return f(*args, **kwargs)
            
        return decorated_function
    return decorator