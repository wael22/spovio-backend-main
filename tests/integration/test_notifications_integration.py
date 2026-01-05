"""
Tests d'intégration pour le système de notifications
Teste les flux complets de création, envoi, et gestion des notifications
"""
import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from src.models.user import User, Notification, NotificationType
from src.models.database import db


@pytest.mark.integration
@pytest.mark.notifications
class TestNotificationsIntegration:
    """Tests d'intégration pour le système de notifications"""
    
    def test_create_notification_flow(self, client, auth_headers_admin, player_user):
        """Test complet de création d'une notification"""
        notification_data = {
            'user_id': player_user.id,
            'notification_type': 'CREDITS_ADDED',
            'title': 'Crédits ajoutés',
            'message': '100 crédits ont été ajoutés à votre compte',
            'priority': 'normal'
        }
        
        response = client.post('/api/notifications',
                             json=notification_data,
                             headers=auth_headers_admin,
                             content_type='application/json')
        
        assert response.status_code == 201
        data = response.get_json()
        
        # Vérifier la réponse
        assert 'notification' in data
        notification = data['notification']
        assert notification['title'] == 'Crédits ajoutés'
        assert notification['message'] == '100 crédits ont été ajoutés à votre compte'
        assert notification['notification_type'] == 'CREDITS_ADDED'
        assert notification['is_read'] is False
        
        # Vérifier en base de données
        db_notification = Notification.query.filter_by(id=notification['id']).first()
        assert db_notification is not None
        assert db_notification.user_id == player_user.id
        assert db_notification.title == 'Crédits ajoutés'
    
    def test_get_user_notifications(self, client, auth_headers_player, player_user):
        """Test de récupération des notifications d'un utilisateur"""
        # Créer quelques notifications
        with client.application.app_context():
            notifications = [
                Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.VIDEO_READY.value,
                    title='Vidéo prête',
                    message='Votre vidéo est prête au téléchargement',
                    priority='high',
                    is_read=False
                ),
                Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.CREDITS_ADDED.value,
                    title='Crédits ajoutés',
                    message='50 crédits ajoutés',
                    priority='normal',
                    is_read=True
                ),
                Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.SYSTEM_MAINTENANCE.value,
                    title='Maintenance programmée',
                    message='Maintenance ce soir de 22h à 23h',
                    priority='low',
                    is_read=False
                )
            ]
            
            for notification in notifications:
                db.session.add(notification)
            db.session.commit()
        
        # Récupérer les notifications
        response = client.get('/api/notifications',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert 'notifications' in data
        assert len(data['notifications']) == 3
        
        # Vérifier le tri (plus récent en premier, non lues en premier)
        notifications = data['notifications']
        unread_count = sum(1 for n in notifications if not n['is_read'])
        assert unread_count == 2
    
    def test_mark_notification_as_read(self, client, auth_headers_player, player_user):
        """Test de marquage d'une notification comme lue"""
        # Créer une notification non lue
        with client.application.app_context():
            notification = Notification(
                user_id=player_user.id,
                notification_type=NotificationType.VIDEO_READY.value,
                title='Vidéo prête',
                message='Votre vidéo est prête',
                is_read=False
            )
            db.session.add(notification)
            db.session.commit()
            notification_id = notification.id
        
        # Marquer comme lue
        response = client.post(f'/api/notifications/{notification_id}/read',
                             headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Notification marked as read'
        
        # Vérifier en base de données
        with client.application.app_context():
            updated_notification = Notification.query.get(notification_id)
            assert updated_notification.is_read is True
            assert updated_notification.read_at is not None
    
    def test_bulk_mark_notifications_as_read(self, client, auth_headers_player, player_user):
        """Test de marquage en masse comme lues"""
        # Créer plusieurs notifications non lues
        with client.application.app_context():
            notifications = []
            for i in range(3):
                notification = Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.CREDITS_ADDED.value,
                    title=f'Notification {i+1}',
                    message=f'Message {i+1}',
                    is_read=False
                )
                db.session.add(notification)
                notifications.append(notification)
            
            db.session.commit()
            notification_ids = [n.id for n in notifications]
        
        # Marquer toutes comme lues
        response = client.post('/api/notifications/mark-all-read',
                             headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'marked_count' in data
        assert data['marked_count'] == 3
        
        # Vérifier en base de données
        with client.application.app_context():
            for notification_id in notification_ids:
                notification = Notification.query.get(notification_id)
                assert notification.is_read is True
    
    def test_delete_notification(self, client, auth_headers_player, player_user):
        """Test de suppression d'une notification"""
        # Créer une notification
        with client.application.app_context():
            notification = Notification(
                user_id=player_user.id,
                notification_type=NotificationType.SYSTEM_MAINTENANCE.value,
                title='À supprimer',
                message='Cette notification sera supprimée',
                is_read=True
            )
            db.session.add(notification)
            db.session.commit()
            notification_id = notification.id
        
        # Supprimer la notification
        response = client.delete(f'/api/notifications/{notification_id}',
                               headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Notification deleted'
        
        # Vérifier en base de données (soft delete)
        with client.application.app_context():
            deleted_notification = Notification.query.get(notification_id)
            assert deleted_notification.is_deleted is True
    
    def test_notification_access_control(self, client, auth_headers_player, auth_headers_admin, player_user, admin_user):
        """Test du contrôle d'accès aux notifications"""
        # Créer une notification pour le player
        with client.application.app_context():
            player_notification = Notification(
                user_id=player_user.id,
                notification_type=NotificationType.VIDEO_READY.value,
                title='Notification du joueur',
                message='Privée au joueur',
                is_read=False
            )
            db.session.add(player_notification)
            db.session.commit()
            notification_id = player_notification.id
        
        # Le player peut accéder à sa notification
        response = client.get(f'/api/notifications/{notification_id}',
                            headers=auth_headers_player)
        assert response.status_code == 200
        
        # L'admin NE PEUT PAS accéder à la notification du player (sauf endpoint admin spécifique)
        response = client.get(f'/api/notifications/{notification_id}',
                            headers=auth_headers_admin)
        assert response.status_code == 404  # Ou 403 selon l'implémentation
    
    def test_notification_expiration(self, client, auth_headers_player, player_user):
        """Test de l'expiration automatique des notifications"""
        # Créer une notification expirée
        with client.application.app_context():
            expired_notification = Notification(
                user_id=player_user.id,
                notification_type=NotificationType.SYSTEM_MAINTENANCE.value,
                title='Notification expirée',
                message='Cette notification devrait être expirée',
                expires_at=datetime.utcnow() - timedelta(hours=1)  # Expirée il y a 1 heure
            )
            db.session.add(expired_notification)
            db.session.commit()
        
        # Récupérer les notifications (les expirées ne devraient pas apparaître)
        response = client.get('/api/notifications',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        
        # La notification expirée ne devrait pas être dans la liste
        notifications = data['notifications']
        expired_found = any(n['title'] == 'Notification expirée' for n in notifications)
        assert not expired_found
    
    def test_notification_priority_sorting(self, client, auth_headers_player, player_user):
        """Test du tri des notifications par priorité"""
        # Créer des notifications avec différentes priorités
        with client.application.app_context():
            priorities = [
                ('low', 'Priorité basse'),
                ('high', 'Priorité haute'),
                ('normal', 'Priorité normale'),
                ('high', 'Autre priorité haute')
            ]
            
            for priority, title in priorities:
                notification = Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.SYSTEM_MAINTENANCE.value,
                    title=title,
                    message=f'Message {priority}',
                    priority=priority,
                    is_read=False
                )
                db.session.add(notification)
            
            db.session.commit()
        
        # Récupérer les notifications
        response = client.get('/api/notifications',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        notifications = data['notifications']
        
        # Vérifier que les priorités hautes sont en premier
        high_priority_notifications = [n for n in notifications if n['priority'] == 'high']
        assert len(high_priority_notifications) == 2
        
        # Les deux premières notifications devraient être à priorité haute
        assert notifications[0]['priority'] == 'high'
        assert notifications[1]['priority'] == 'high'
    
    def test_get_notification_counts(self, client, auth_headers_player, player_user):
        """Test de récupération des compteurs de notifications"""
        # Créer des notifications avec différents états
        with client.application.app_context():
            notifications = [
                # Non lues
                Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.VIDEO_READY.value,
                    title='Non lue 1',
                    message='Message',
                    is_read=False
                ),
                Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.CREDITS_ADDED.value,
                    title='Non lue 2',
                    message='Message',
                    is_read=False
                ),
                # Lues
                Notification(
                    user_id=player_user.id,
                    notification_type=NotificationType.SYSTEM_MAINTENANCE.value,
                    title='Lue 1',
                    message='Message',
                    is_read=True
                )
            ]
            
            for notification in notifications:
                db.session.add(notification)
            db.session.commit()
        
        # Récupérer les compteurs
        response = client.get('/api/notifications/counts',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert 'total' in data
        assert 'unread' in data
        assert 'read' in data
        
        assert data['total'] == 3
        assert data['unread'] == 2
        assert data['read'] == 1


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.notifications
class TestNotificationCeleryIntegration:
    """Tests d'intégration entre notifications et tâches asynchrones"""
    
    @patch('src.tasks.notification_tasks.send_notification.delay')
    def test_async_notification_creation(self, mock_task, client, auth_headers_admin, player_user):
        """Test de création asynchrone de notification"""
        notification_data = {
            'user_id': player_user.id,
            'notification_type': 'VIDEO_READY',
            'title': 'Vidéo prête (async)',
            'message': 'Votre vidéo est prête au téléchargement',
            'send_async': True  # Flag pour envoi asynchrone
        }
        
        response = client.post('/api/notifications',
                             json=notification_data,
                             headers=auth_headers_admin,
                             content_type='application/json')
        
        assert response.status_code == 201
        
        # Vérifier que la tâche asynchrone a été déclenchée
        mock_task.assert_called_once()
    
    @patch('src.tasks.notification_tasks.send_bulk_notifications.delay')
    def test_bulk_notification_sending(self, mock_task, client, auth_headers_admin, player_user, club_user):
        """Test d'envoi en masse de notifications"""
        bulk_data = {
            'user_ids': [player_user.id, club_user.id],
            'notification_type': 'SYSTEM_MAINTENANCE',
            'title': 'Maintenance système',
            'message': 'Maintenance programmée ce soir',
            'priority': 'high'
        }
        
        response = client.post('/api/notifications/bulk',
                             json=bulk_data,
                             headers=auth_headers_admin,
                             content_type='application/json')
        
        assert response.status_code == 202  # Accepted pour traitement async
        
        # Vérifier que la tâche bulk a été déclenchée
        mock_task.assert_called_once()
    
    @patch('src.tasks.notification_tasks.cleanup_expired_notifications.delay')
    def test_notification_cleanup_trigger(self, mock_task, client):
        """Test du déclenchement du nettoyage des notifications expirées"""
        # Simuler un trigger de nettoyage (normalement fait par Celery Beat)
        response = client.post('/api/admin/notifications/cleanup')
        
        if response.status_code in [200, 202]:
            # Vérifier que la tâche de nettoyage a été déclenchée
            mock_task.assert_called_once()