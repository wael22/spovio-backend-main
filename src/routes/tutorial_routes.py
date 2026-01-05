# padelvar-backend/src/routes/tutorial_routes.py

from flask import Blueprint, request, jsonify
from ..routes.auth import require_auth
from src.services.tutorial_service import TutorialService
import logging

logger = logging.getLogger(__name__)

tutorial_bp = Blueprint('tutorial', __name__)

@tutorial_bp.route('/status', methods=['GET'])
@require_auth
def get_tutorial_status():
    """Récupérer le statut du tutoriel de l'utilisateur connecté"""
    try:
        from ..routes.auth import get_current_user
        current_user = get_current_user()
        result, status_code = TutorialService.get_tutorial_status(current_user.id)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Erreur dans get_tutorial_status: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500

@tutorial_bp.route('/step', methods=['POST'])
@require_auth
def update_tutorial_step():
    """Mettre à jour l'étape actuelle du tutoriel"""
    try:
        from ..routes.auth import get_current_user
        current_user = get_current_user()
        data = request.get_json()
        
        if 'step' not in data:
            return jsonify({'error': 'Le champ step est requis'}), 400
        
        step = data.get('step')
        result, status_code = TutorialService.update_tutorial_step(current_user.id, step)
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Erreur dans update_tutorial_step: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500

@tutorial_bp.route('/complete', methods=['POST'])
@require_auth
def complete_tutorial():
    """Marquer le tutoriel comme complété"""
    try:
        from ..routes.auth import get_current_user
        current_user = get_current_user()
        result, status_code = TutorialService.complete_tutorial(current_user.id)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Erreur dans complete_tutorial: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500

@tutorial_bp.route('/reset', methods=['POST'])
@require_auth
def reset_tutorial():
    """Réinitialiser le tutoriel pour le relancer"""
    try:
        from ..routes.auth import get_current_user
        current_user = get_current_user()
        result, status_code = TutorialService.reset_tutorial(current_user.id)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Erreur dans reset_tutorial: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500

@tutorial_bp.route('/skip', methods=['POST'])
@require_auth
def skip_tutorial():
    """Passer le tutoriel (marquer comme complété)"""
    try:
        from ..routes.auth import get_current_user
        current_user = get_current_user()
        result, status_code = TutorialService.skip_tutorial(current_user.id)
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"Erreur dans skip_tutorial: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500
