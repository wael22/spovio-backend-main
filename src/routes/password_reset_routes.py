from flask import Blueprint, request, jsonify
from ..services.password_reset_service import request_password_reset, reset_password
import logging

# Configuration d'un logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Créer un blueprint pour les routes de réinitialisation de mot de passe
password_reset_bp = Blueprint('password_reset', __name__)

@password_reset_bp.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Route pour demander une réinitialisation de mot de passe"""
    try:
        # Récupérer les données de la requête
        data = request.json
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email requis'}), 400
        
        # Importer le service utilisateur ici pour éviter les imports circulaires
        from ..services.user_service import UserService
        user_service = UserService()
        
        # Traiter la demande de réinitialisation
        result = request_password_reset(email, user_service)
        
        # Toujours retourner un succès pour éviter les fuites d'information
        return jsonify({
            'success': True, 
            'message': 'Si votre email est enregistré, vous recevrez un lien de réinitialisation.'
        })
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la demande de réinitialisation: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Une erreur est survenue lors du traitement de votre demande.'
        }), 500

@password_reset_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password_route():
    """Route pour réinitialiser un mot de passe avec un token"""
    try:
        # Récupérer les données de la requête
        data = request.json
        token = data.get('token')
        new_password = data.get('password')
        
        if not token or not new_password:
            return jsonify({
                'success': False, 
                'message': 'Token et nouveau mot de passe requis'
            }), 400
        
        # Vérifier la complexité du mot de passe
        if len(new_password) < 8:
            return jsonify({
                'success': False, 
                'message': 'Le mot de passe doit contenir au moins 8 caractères'
            }), 400
        
        # Importer le service utilisateur ici pour éviter les imports circulaires
        from ..services.user_service import UserService
        user_service = UserService()
        
        # Réinitialiser le mot de passe
        result = reset_password(token, new_password, user_service)
        
        if result:
            return jsonify({
                'success': True, 
                'message': 'Mot de passe réinitialisé avec succès'
            })
        else:
            return jsonify({
                'success': False, 
                'message': 'Token invalide ou expiré'
            }), 400
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la réinitialisation du mot de passe: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Une erreur est survenue lors de la réinitialisation du mot de passe.'
        }), 500

@password_reset_bp.route('/api/auth/verify-reset-token', methods=['POST'])
def verify_reset_token_route():
    """Route pour vérifier la validité d'un token de réinitialisation"""
    try:
        # Récupérer les données de la requête
        data = request.json
        token = data.get('token')
        
        if not token:
            return jsonify({
                'success': False, 
                'message': 'Token requis'
            }), 400
        
        # Importer ici pour éviter les imports circulaires
        from ..services.password_reset_service import verify_reset_token
        
        # Vérifier le token
        token_data = verify_reset_token(token)
        
        if token_data:
            return jsonify({
                'success': True, 
                'message': 'Token valide',
                'email': token_data['email']
            })
        else:
            return jsonify({
                'success': False, 
                'message': 'Token invalide ou expiré'
            }), 400
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification du token: {str(e)}")
        return jsonify({
            'success': False, 
            'message': 'Une erreur est survenue lors de la vérification du token.'
        }), 500
