# src/tasks/notification_tasks.py

"""
Tâches Celery pour le système de notifications
Gère l'envoi de notifications en temps réel et par email
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from ..celery_app import celery_app
from ..models.database import db
from ..models.user import User, Notification, NotificationType

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def send_notification(self, user_id, notification_type, title, message, 
                     priority='normal', related_resource_type=None, 
                     related_resource_id=None, action_url=None, action_label=None,
                     expires_in_hours=24):
    """
    Envoie une notification à un utilisateur
    
    Args:
        user_id: ID de l'utilisateur destinataire
        notification_type: Type de notification (enum NotificationType)
        title: Titre de la notification
        message: Message de la notification
        priority: Priorité (low, normal, high, urgent)
        related_resource_type: Type de ressource liée (optionnel)
        related_resource_id: ID de la ressource liée (optionnel)
        action_url: URL d'action pour la notification (optionnel)
        action_label: Label du bouton d'action (optionnel)
        expires_in_hours: Nombre d'heures avant expiration
    """
    try:
        logger.info(f"Envoi notification à l'utilisateur {user_id}: {notification_type}")
        
        # Vérifier que l'utilisateur existe
        user = User.query.get(user_id)
        if not user:
            logger.error(f"Utilisateur {user_id} non trouvé")
            return {'status': 'error', 'message': 'User not found'}
        
        # Convertir le type de notification si c'est une string
        if isinstance(notification_type, str):
            try:
                notification_type = NotificationType(notification_type)
            except ValueError:
                logger.error(f"Type de notification invalide: {notification_type}")
                return {'status': 'error', 'message': 'Invalid notification type'}
        
        # Calculer la date d'expiration
        expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours) if expires_in_hours else None
        
        # Créer la notification
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            related_resource_type=related_resource_type,
            related_resource_id=related_resource_id,
            action_url=action_url,
            action_label=action_label,
            expires_at=expires_at
        )
        
        db.session.add(notification)
        db.session.commit()
        
        logger.info(f"Notification créée avec ID: {notification.id}")
        
        # TODO: Intégrer avec un système de push notifications (WebSocket, Firebase, etc.)
        # En attendant, on peut simuler l'envoi en temps réel
        
        # Si c'est une notification critique, on peut aussi envoyer par email
        if priority in ['high', 'urgent']:
            send_email_notification.delay(
                user_id=user_id,
                title=title,
                message=message,
                notification_id=notification.id
            )
        
        return {
            'status': 'sent',
            'notification_id': notification.id,
            'user_id': user_id,
            'type': notification_type.value
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de notification: {str(e)}")
        
        # Retry si possible
        if self.request.retries < self.max_retries:
            logger.info(f"Retry {self.request.retries + 1}/{self.max_retries}")
            raise self.retry(exc=e)
        
        return {'status': 'failed', 'error': str(e)}

@celery_app.task(bind=True, max_retries=2)
def send_email_notification(self, user_id, title, message, notification_id=None):
    """
    Envoie une notification par email (pour les notifications importantes)
    
    TODO: Intégrer avec un service d'email (SendGrid, SES, etc.)
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return {'status': 'error', 'message': 'User not found'}
        
        logger.info(f"Envoi email de notification à {user.email}")
        
        # TODO: Implémenter l'envoi d'email réel
        # Pour l'instant, on simule l'envoi
        email_content = f"""
        Bonjour {user.name},
        
        {title}
        
        {message}
        
        Cordialement,
        L'équipe Spovio
        """
        
        logger.info(f"Email simulé envoyé à {user.email}: {title}")
        
        return {
            'status': 'sent',
            'recipient': user.email,
            'title': title
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi d'email: {str(e)}")
        return {'status': 'failed', 'error': str(e)}

@celery_app.task(bind=True)
def send_bulk_notification(self, user_ids, notification_type, title, message, **kwargs):
    """
    Envoie une notification à plusieurs utilisateurs
    """
    try:
        logger.info(f"Envoi de notification en masse à {len(user_ids)} utilisateurs")
        
        results = []
        for user_id in user_ids:
            result = send_notification.delay(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                message=message,
                **kwargs
            )
            results.append({'user_id': user_id, 'task_id': result.id})
        
        return {
            'status': 'scheduled',
            'total_users': len(user_ids),
            'tasks': results
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi en masse: {str(e)}")
        return {'status': 'failed', 'error': str(e)}

@celery_app.task
def notify_recording_reminder(session_id, minutes_before_end=10):
    """
    Envoie un rappel avant la fin d'un enregistrement
    """
    try:
        from ..models.user import RecordingSession
        
        session = RecordingSession.query.filter_by(recording_id=session_id).first()
        if not session or session.status != 'active':
            return {'status': 'skipped', 'reason': 'session_not_active'}
        
        remaining = session.get_remaining_minutes()
        if remaining <= minutes_before_end:
            send_notification.delay(
                user_id=session.user_id,
                notification_type=NotificationType.RECORDING_STARTED.value,  # Temporary, à créer RECORDING_REMINDER
                title=f"Enregistrement bientôt terminé",
                message=f"Il reste {remaining} minutes à votre enregistrement sur le terrain {session.court.name}.",
                priority='normal',
                related_resource_type="recording_session",
                related_resource_id=session_id
            )
            
            return {'status': 'sent', 'remaining_minutes': remaining}
        
        return {'status': 'skipped', 'remaining_minutes': remaining}
        
    except Exception as e:
        logger.error(f"Erreur lors du rappel d'enregistrement: {e}")
        return {'status': 'failed', 'error': str(e)}

@celery_app.task
def notify_system_maintenance(start_time, end_time, description):
    """
    Notifie tous les utilisateurs actifs d'une maintenance système
    """
    try:
        from ..models.user import UserStatus
        
        # Récupérer tous les utilisateurs actifs
        active_users = User.query.filter_by(status=UserStatus.ACTIVE).all()
        
        if not active_users:
            return {'status': 'no_users', 'total': 0}
        
        user_ids = [user.id for user in active_users]
        
        # Envoyer la notification en masse
        result = send_bulk_notification.delay(
            user_ids=user_ids,
            notification_type=NotificationType.SYSTEM_MAINTENANCE.value,
            title="Maintenance système programmée",
            message=f"Maintenance prévue du {start_time} au {end_time}. {description}",
            priority='high',
            expires_in_hours=48
        )
        
        return {
            'status': 'scheduled',
            'total_users': len(user_ids),
            'bulk_task_id': result.id
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de la notification de maintenance: {e}")
        return {'status': 'failed', 'error': str(e)}