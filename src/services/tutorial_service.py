# padelvar-backend/src/services/tutorial_service.py

from src.models.user import User
from src.models.database import db
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TutorialService:
    """Service pour gérer le système de tutoriel"""
    
    @staticmethod
    def get_tutorial_status(user_id):
        """
        Récupérer le statut du tutoriel pour un utilisateur
        
        Args:
            user_id (int): ID de l'utilisateur
            
        Returns:
            dict: Statut du tutoriel
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return {'error': 'Utilisateur introuvable'}, 404
            
            return {
                'tutorial_completed': user.tutorial_completed,
                'tutorial_step': user.tutorial_step,
                'total_steps': 10
            }, 200
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du statut du tutoriel: {e}")
            return {'error': 'Erreur serveur'}, 500
    
    @staticmethod
    def update_tutorial_step(user_id, step):
        """
        Mettre à jour l'étape actuelle du tutoriel
        
        Args:
            user_id (int): ID de l'utilisateur
            step (int): Numéro de l'étape (1-10)
            
        Returns:
            dict: Statut mis à jour
        """
        try:
            # Validation
            if not isinstance(step, int) or step < 1 or step > 10:
                return {'error': 'L\'étape doit être entre 1 et 10'}, 400
            
            user = User.query.get(user_id)
            if not user:
                return {'error': 'Utilisateur introuvable'}, 404
            
            # Mettre à jour l'étape
            user.tutorial_step = step
            user.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Tutoriel mis à jour pour l'utilisateur {user_id} - Étape {step}")
            
            return {
                'tutorial_completed': user.tutorial_completed,
                'tutorial_step': user.tutorial_step,
                'total_steps': 10
            }, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors de la mise à jour de l'étape du tutoriel: {e}")
            return {'error': 'Erreur serveur'}, 500
    
    @staticmethod
    def complete_tutorial(user_id):
        """
        Marquer le tutoriel comme complété
        
        Args:
            user_id (int): ID de l'utilisateur
            
        Returns:
            dict: Confirmation
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return {'error': 'Utilisateur introuvable'}, 404
            
            # Marquer comme complété
            user.tutorial_completed = True
            user.tutorial_step = None  # Réinitialiser l'étape
            user.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Tutoriel complété pour l'utilisateur {user_id}")
            
            return {
                'message': 'Tutoriel complété avec succès',
                'tutorial_completed': True
            }, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors de la complétion du tutoriel: {e}")
            return {'error': 'Erreur serveur'}, 500
    
    @staticmethod
    def reset_tutorial(user_id):
        """
        Réinitialiser le tutoriel pour permettre de le relancer
        
        Args:
            user_id (int): ID de l'utilisateur
            
        Returns:
            dict: Confirmation
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return {'error': 'Utilisateur introuvable'}, 404
            
            # Réinitialiser
            user.tutorial_completed = False
            user.tutorial_step = 1  # Commencer à l'étape 1
            user.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Tutoriel réinitialisé pour l'utilisateur {user_id}")
            
            return {
                'message': 'Tutoriel réinitialisé',
                'tutorial_completed': False,
                'tutorial_step': 1
            }, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors de la réinitialisation du tutoriel: {e}")
            return {'error': 'Erreur serveur'}, 500
    
    @staticmethod
    def skip_tutorial(user_id):
        """
        Passer le tutoriel (marque comme complété sans le faire)
        
        Args:
            user_id (int): ID de l'utilisateur
            
        Returns:
            dict: Confirmation
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return {'error': 'Utilisateur introuvable'}, 404
            
            # Marquer comme complété
            user.tutorial_completed = True
            user.tutorial_step = None
            user.updated_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Tutoriel passé pour l'utilisateur {user_id}")
            
            return {
                'message': 'Tutoriel passé',
                'tutorial_completed': True
            }, 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors du passage du tutoriel: {e}")
            return {'error': 'Erreur serveur'}, 500
