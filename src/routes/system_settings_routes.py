"""
Routes pour gérer les paramètres système (Super Admin uniquement)
"""
from flask import Blueprint, request, jsonify, session
from src.models.database import db
from src.models.system_settings import SystemSettings
from src.models.user import User, UserRole
import logging

logger = logging.getLogger(__name__)

system_settings_bp = Blueprint('system_settings', __name__, url_prefix='/api/admin')

def require_super_admin():
    """Vérifier que l'utilisateur est super admin"""
    user_id = session.get('user_id')
    if not user_id:
        return None, jsonify({'error': 'Non authentifié'}), 401
    
    user = User.query.get(user_id)
    if not user or user.role != UserRole.SUPER_ADMIN:
        return None, jsonify({'error': 'Accès super admin requis'}), 403
    
    return user, None, None

@system_settings_bp.route('/settings/public', methods=['GET'])
def get_public_settings():
    """Récupérer les paramètres publics (sans authentification)"""
    try:
        welcome_credits = SystemSettings.get_welcome_credits()
        return jsonify({'welcome_credits': welcome_credits}), 200
    except Exception as e:
        logger.error(f"Erreur récupération paramètres publics: {e}")
        return jsonify({'welcome_credits': 1}), 200  # Fallback to 1

@system_settings_bp.route('/settings', methods=['GET'])
def get_settings():
    """Récupérer les paramètres système"""
    user, error_response, status_code = require_super_admin()
    if error_response:
        return error_response, status_code
    
    try:
        settings = SystemSettings.get_instance()
        return jsonify(settings.to_dict()), 200
    except Exception as e:
        logger.error(f"Erreur récupération paramètres: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des paramètres'}), 500

@system_settings_bp.route('/settings', methods=['PUT'])
def update_settings():
    """Mettre à jour les paramètres système"""
    user, error_response, status_code = require_super_admin()
    if error_response:
        return error_response, status_code
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Données requises'}), 400
        
        # Valider welcome_credits
        welcome_credits = data.get('welcome_credits')
        if welcome_credits is not None:
            if not isinstance(welcome_credits, int):
                return jsonify({'error': 'welcome_credits doit être un nombre entier'}), 400
            
            if welcome_credits < 0 or welcome_credits > 100:
                return jsonify({'error': 'welcome_credits doit être entre 0 et 100'}), 400
            
            # Mettre à jour
            SystemSettings.set_welcome_credits(welcome_credits, user.id)
            logger.info(f"✅ Paramètres mis à jour par {user.email}: welcome_credits={welcome_credits}")
        
        # Récupérer et retourner les paramètres mis à jour
        settings = SystemSettings.get_instance()
        return jsonify({
            'message': 'Paramètres mis à jour avec succès',
            'settings': settings.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur mise à jour paramètres: {e}")
        return jsonify({'error': 'Erreur lors de la mise à jour des paramètres'}), 500
