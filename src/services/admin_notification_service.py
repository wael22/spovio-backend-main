"""
Service helper pour créer des notifications système pour le Super Admin
"""
import logging

logger = logging.getLogger(__name__)

def notify_super_admin(title: str, message: str, link: str = None, app=None):
    """
    Crée une notification système pour tous les super admins
    
    Args:
        title: Titre de la notification
        message: Message détaillé
        link: Lien optionnel vers le problème
        app: Instance Flask (optionnel, utilisé si appelé hors contexte)
    """
    try:
        from flask import has_app_context
        from src.models.database import db
        from src.models.notification import Notification, NotificationType
        from src.models.user import User, UserRole
        
        # Si pas de contexte et pas d'app fournie, on ne peut rien faire
        if not has_app_context() and app is None:
            logger.warning("⚠️ Pas de contexte Flask disponible pour créer la notification")
            return
        
        # Si app fournie mais pas de contexte, créer un contexte
        if app and not has_app_context():
            with app.app_context():
                _create_notifications(title, message, link)
        else:
            # Déjà dans un contexte Flask
            _create_notifications(title, message, link)
            
    except Exception as e:
        logger.error(f"❌ Erreur création notification super admin: {e}")


def _create_notifications(title: str, message: str, link: str = None):
    """Fonction interne pour créer les notifications (doit être appelée dans un app context)"""
    from src.models.database import db
    from src.models.notification import Notification, NotificationType
    from src.models.user import User, UserRole
    
    try:
        # Trouver tous les super admins
        super_admins = User.query.filter_by(role=UserRole.SUPER_ADMIN).all()
        
        if not super_admins:
            logger.warning("⚠️ Aucun super admin trouvé pour la notification système")
            return
        
        # Créer une notification pour chaque super admin
        notifications_created = 0
        for admin in super_admins:
            notification = Notification.create_notification(
                user_id=admin.id,
                notification_type=NotificationType.SYSTEM_MAINTENANCE,
                title=title,
                message=message,
                link=link
            )
            notifications_created += 1
        
        # Commit toutes les notifications en une fois
        db.session.commit()
        
        logger.info(f"✅ {notifications_created} notifications système créées pour les super admins")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création des notifications: {e}")
        try:
            db.session.rollback()
        except:
            pass


def notify_admin_error(error_type: str, error_message: str, details: dict = None, app=None):
    """
    Crée une notification d'erreur système pour les super admins
    
    Args:
        error_type: Type d'erreur (ex: "Bunny Upload", "Database", etc.)
        error_message: Message d'erreur
        details: Détails supplémentaires (optionnel)
        app: Instance Flask (optionnel, utilisé si appelé hors contexte)
    """
    title = f"🚨 Erreur Système: {error_type}"
    
    message = f"{error_message}\n\n"
    
    if details:
        message += "Détails:\n"
        for key, value in details.items():
            message += f"  • {key}: {value}\n"
    
    notify_super_admin(title, message, app=app)

