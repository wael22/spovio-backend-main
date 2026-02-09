# src/routes/notifications.py

"""
Routes API pour le système de notifications
Gère les notifications utilisateur temps réel
"""

import logging
from flask import Blueprint, request, jsonify, session
from datetime import datetime, timedelta
from sqlalchemy import and_, or_

from ..models.database import db
from ..models.user import User
from ..models.notification import Notification, NotificationType  # FIX: Importer depuis notification.py
from ..routes.auth import require_auth
# from ..tasks.notification_tasks import send_notification, send_bulk_notification

logger = logging.getLogger(__name__)

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')

@notifications_bp.route('', methods=['GET'])
@require_auth
def get_user_notifications():
    """
    Récupère les notifications de l'utilisateur
    
    Query params:
    - limit: nombre de notifications (default: 20, max: 100)
    - offset: décalage pour pagination (default: 0)
    - unread_only: true pour ne récupérer que les non lues (default: false)
    - type: filtrer par type de notification (optionnel)
    - include_archived: true pour inclure les archivées (default: false)
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        # Paramètres de requête
        limit = min(int(request.args.get('limit', 20)), 100)
        offset = int(request.args.get('offset', 0))
        unread_only = request.args.get('unread_only', 'false').lower() == 'true'
        notification_type = request.args.get('type')
        include_archived = request.args.get('include_archived', 'false').lower() == 'true'
        
        # Construire la requête
        query = Notification.query.filter_by(user_id=user_id)
        
        # DEBUG
        logger.info(f"[NOTIF DEBUG] user_id from session: {user_id}")
        logger.info(f"[NOTIF DEBUG] Total notifications in DB for user {user_id}: {Notification.query.filter_by(user_id=user_id).count()}")
        
        # Filtres
        if unread_only:
            query = query.filter_by(is_read=False)
        
        if notification_type:
            try:
                type_enum = NotificationType(notification_type)
                query = query.filter_by(notification_type=type_enum)
            except ValueError:
                return jsonify({'error': f'Invalid notification type: {notification_type}'}), 400
        
        # Appliquer la pagination et l'ordre (plus récentes en premier)
        notifications = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
        
        # DEBUG
        logger.info(f"[NOTIF DEBUG] Query returned {len(notifications)} notifications")
        
        # Compter le total pour la pagination
        total = query.count()
        
        # Statistiques rapides
        unread_count = Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).count()
        
        result = {
            'notifications': [notification.to_dict() for notification in notifications],
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': offset + limit < total
            },
            'stats': {
                'unread_count': unread_count
            }
        }
        
        return jsonify(result), 200
        
    except ValueError as e:
        return jsonify({'error': 'Invalid parameters'}), 400
    
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des notifications: {str(e)}")
        return jsonify({
            'error': 'Failed to retrieve notifications'
        }), 500

@notifications_bp.route('/<int:notification_id>/mark-read', methods=['POST'])
@require_auth
def mark_notification_read(notification_id):
    """
    Marque une notification comme lue
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=user_id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        if notification.is_read:
            return jsonify({
                'status': 'already_read',
                'notification_id': notification_id
            }), 200
        
        # Marquer comme lue
        notification.is_read = True
        db.session.commit()
        
        logger.info(f"Notification {notification_id} marquée comme lue pour utilisateur {user_id}")
        
        return jsonify({
            'status': 'marked_read',
            'notification_id': notification_id
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du marquage de lecture: {str(e)}")
        return jsonify({
            'error': 'Failed to mark notification as read'
        }), 500

@notifications_bp.route('/mark-all-read', methods=['POST'])
@require_auth
def mark_all_notifications_read():
    """
    Marque toutes les notifications non lues comme lues
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        current_time = datetime.utcnow()
        
        # Récupérer toutes les notifications non lues de l'utilisateur
        unread_notifications = Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).all()
        
        if not unread_notifications:
            return jsonify({
                'status': 'no_unread_notifications',
                'marked_count': 0
            }), 200
        
        # Marquer toutes comme lues
        for notification in unread_notifications:
            notification.is_read = True
        
        db.session.commit()
        
        marked_count = len(unread_notifications)
        logger.info(f"{marked_count} notifications marquées comme lues pour utilisateur {user_id}")
        
        return jsonify({
            'status': 'all_marked_read',
            'marked_count': marked_count
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du marquage en masse: {str(e)}")
        return jsonify({
            'error': 'Failed to mark all notifications as read'
        }), 500

@notifications_bp.route('/<int:notification_id>/archive', methods=['POST'])
@require_auth
def archive_notification(current_user, notification_id):
    """
    Archive une notification
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=user_id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        # Marquer comme lue (on retire le champ is_archived pour l'instant)
        if not notification.is_read:
            notification.is_read = True
        
        db.session.commit()
        
        return jsonify({
            'status': 'archived',
            'notification_id': notification_id
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'archivage: {str(e)}")
        return jsonify({
            'error': 'Failed to archive notification'
        }), 500

@notifications_bp.route('/<int:notification_id>', methods=['DELETE'])
@require_auth
def delete_notification(current_user, notification_id):
    """
    Supprime une notification
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        notification = Notification.query.filter_by(
            id=notification_id,
            user_id=user_id
        ).first()
        
        if not notification:
            return jsonify({'error': 'Notification not found'}), 404
        
        db.session.delete(notification)
        db.session.commit()
        
        logger.info(f"Notification {notification_id} supprimée pour utilisateur {user_id}")
        
        return jsonify({
            'status': 'deleted',
            'notification_id': notification_id
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la suppression: {str(e)}")
        return jsonify({
            'error': 'Failed to delete notification'
        }), 500

@notifications_bp.route('/stats', methods=['GET'])
@require_auth
def get_notification_stats(current_user):
    """
    Récupère les statistiques des notifications de l'utilisateur
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        current_time = datetime.utcnow()
        
        # Compter par statut (sans les champs qui n'existent pas encore)
        total = Notification.query.filter_by(user_id=user_id).count()
        
        unread = Notification.query.filter_by(
            user_id=user_id,
            is_read=False
        ).count()
        
        # Compter par type (derniers 30 jours)
        last_month = current_time - timedelta(days=30)
        type_counts = {}
        
        recent_notifications = Notification.query.filter(
            Notification.user_id == user_id,
            Notification.created_at >= last_month
        ).all()
        
        for notification in recent_notifications:
            type_name = notification.notification_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        result = {
            'total_notifications': total,
            'unread_count': unread,
            'read_count': total - unread,
            'by_type_last_30_days': type_counts,
            'last_updated': current_time.isoformat()
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des stats: {str(e)}")
        return jsonify({
            'error': 'Failed to retrieve notification stats'
        }), 500

@notifications_bp.route('/test', methods=['POST'])
@require_auth
def send_test_notification(current_user):
    """
    Envoie une notification de test (pour développement/debug)
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        # Vérifier que l'utilisateur est admin ou en mode développement
        from ..models.user import UserRole
        from ..config import Config
        
        if current_user.role != UserRole.SUPER_ADMIN and not Config.DEBUG:
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json() or {}
        
        # Paramètres par défaut
        title = data.get('title', 'Notification de test')
        message = data.get('message', 'Ceci est une notification de test du système MySmash.')
        notification_type = data.get('type', NotificationType.SYSTEM_MAINTENANCE.value)
        
        # Créer la notification directement en DB
        notification = Notification.create_notification(
            user_id=user_id,
            notification_type=NotificationType(notification_type),
            title=title,
            message=message
        )
        
        return jsonify({
            'status': 'test_notification_sent',
            'notification_id': notification.id,
            'user_id': user_id,
            'type': notification_type
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de notification test: {str(e)}")
        return jsonify({
            'error': 'Failed to send test notification'
        }), 500

# Routes administrateur

@notifications_bp.route('/admin/send', methods=['POST'])
@require_auth
def send_admin_notification(current_user):
    """
    Envoie une notification à un utilisateur ou groupe d'utilisateurs (admin uniquement)
    
    Body:
    {
        "user_ids": [1, 2, 3],  // Optionnel, si absent = tous les utilisateurs actifs
        "title": "Titre de la notification",
        "message": "Message de la notification",
        "type": "system"
    }
    """
    try:
        # Récupérer user_id depuis la session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        
        # Vérifier les droits admin
        from ..models.user import UserRole, UserStatus
        if current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
        
        # Validation des paramètres obligatoires
        title = data.get('title')
        message = data.get('message')
        notification_type = data.get('type', 'system')
        
        if not title:
            return jsonify({'error': 'title is required'}), 400
        
        if not message:
            return jsonify({'error': 'message is required'}), 400
        
        # Paramètres optionnels
        user_ids = data.get('user_ids')
        
        # Si pas d'utilisateurs spécifiés, envoyer à tous les utilisateurs actifs
        if not user_ids:
            active_users = User.query.filter_by(status=UserStatus.ACTIVE).all()
            user_ids = [user.id for user in active_users]
        
        if not user_ids:
            return jsonify({
                'status': 'no_recipients',
                'message': 'No users to notify'
            }), 400
        
        # Créer les notifications directement en DB pour chaque utilisateur
        created_count = 0
        for uid in user_ids:
            try:
                Notification.create_notification(
                    user_id=uid,
                    notification_type=NotificationType(notification_type),
                    title=title,
                    message=message
                )
                created_count += 1
            except Exception as e:
                logger.error(f"Erreur création notification pour user {uid}: {str(e)}")
        
        logger.info(f"Notification admin envoyée par {user_id} à {created_count} utilisateurs")
        
        return jsonify({
            'status': 'notifications_created',
            'recipient_count': created_count,
            'type': notification_type
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi admin: {str(e)}")
        return jsonify({
            'error': 'Failed to send admin notification'
        }), 500

@notifications_bp.route('/admin/stats', methods=['GET'])
@require_auth
def get_admin_notification_stats():
    """
    Récupère les statistiques globales des notifications (admin uniquement)
    """
    try:
        # Vérifier les droits admin
        from ..models.user import UserRole
        if current_user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Admin access required'}), 403
        
        current_time = datetime.utcnow()
        last_24h = current_time - timedelta(hours=24)
        last_week = current_time - timedelta(days=7)
        
        # Statistiques générales
        total_notifications = Notification.query.count()
        notifications_24h = Notification.query.filter(Notification.created_at >= last_24h).count()
        notifications_week = Notification.query.filter(Notification.created_at >= last_week).count()
        
        # Notifications non lues (toute la plateforme)
        total_unread = Notification.query.filter_by(is_read=False).count()
        
        # Par type (dernière semaine)
        type_counts = {}
        recent_notifications = Notification.query.filter(Notification.created_at >= last_week).all()
        
        for notification in recent_notifications:
            type_name = notification.notification_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        # Par priorité (dernière semaine)
        priority_counts = {}
        for notification in recent_notifications:
            priority = notification.priority
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        
        # Utilisateurs avec le plus de notifications non lues
        from sqlalchemy import func
        top_unread_users = db.session.query(
            User.id,
            User.name,
            User.email,
            func.count(Notification.id).label('unread_count')
        ).join(
            Notification, User.id == Notification.user_id
        ).filter(
            Notification.is_read == False
        ).group_by(
            User.id, User.name, User.email
        ).order_by(
            func.count(Notification.id).desc()
        ).limit(10).all()
        
        result = {
            'global_stats': {
                'total_notifications': total_notifications,
                'sent_last_24h': notifications_24h,
                'sent_last_week': notifications_week,
                'total_unread': total_unread
            },
            'by_type_last_week': type_counts,
            'by_priority_last_week': priority_counts,
            'top_unread_users': [
                {
                    'user_id': user.id,
                    'name': user.name,
                    'email': user.email,
                    'unread_count': user.unread_count
                }
                for user in top_unread_users
            ],
            'last_updated': current_time.isoformat()
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des stats admin: {str(e)}")
        return jsonify({
            'error': 'Failed to retrieve admin notification stats'
        }), 500
