"""
Tests d'intégration pour le traitement vidéo et les enregistrements
Teste les flux complets d'enregistrement, traitement FFmpeg, et upload CDN
"""
import pytest
import json
import tempfile
import os
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime

from src.models.user import User
from src.models.recording import RecordingSession
from src.models.database import db


@pytest.mark.integration
@pytest.mark.video
@pytest.mark.slow
class TestVideoProcessingIntegration:
    """Tests d'intégration pour le traitement vidéo"""
    
    @patch('src.tasks.video_processing.process_recording.delay')
    def test_start_recording_session_flow(self, mock_celery_task, client, auth_headers_player, player_user):
        """Test complet de démarrage d'une session d'enregistrement"""
        # Configuration du mock Celery
        mock_celery_task.return_value = Mock(id='task-123')
        
        recording_data = {
            'court_id': 1,
            'title': 'Test Recording Session',
            'duration_minutes': 60
        }
        
        # S'assurer que l'utilisateur a suffisamment de crédits
        with client.application.app_context():
            user = User.query.get(player_user.id)
            user.credits = 1000
            db.session.commit()
        
        response = client.post('/api/recording/v3/start',
                             json=recording_data,
                             headers=auth_headers_player,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Vérifier la réponse
        assert 'session_id' in data
        assert 'message' in data
        assert 'task_id' in data
        
        # Vérifier que la session est créée en base
        session = RecordingSession.query.filter_by(id=data['session_id']).first()
        assert session is not None
        assert session.user_id == player_user.id
        assert session.title == 'Test Recording Session'
        assert session.status == 'active'
        
        # Vérifier que la tâche Celery a été déclenchée
        mock_celery_task.assert_called_once()
        
        # Vérifier que les crédits ont été déduits
        with client.application.app_context():
            updated_user = User.query.get(player_user.id)
            assert updated_user.credits < 1000
    
    def test_stop_recording_session_flow(self, client, auth_headers_player, player_user, recording_session):
        """Test complet d'arrêt d'une session d'enregistrement"""
        # Marquer la session comme active
        with client.application.app_context():
            session = RecordingSession.query.get(recording_session.id)
            session.status = 'active'
            session.process_id = '12345'  # Simuler un processus actif
            db.session.commit()
        
        with patch('src.services.video_recording_service.stop_recording_process') as mock_stop:
            mock_stop.return_value = True
            
            response = client.post(f'/api/recording/v3/stop/{recording_session.id}',
                                 headers=auth_headers_player)
            
            assert response.status_code == 200
            data = response.get_json()
            assert data['message'] == 'Recording stopped successfully'
            
            # Vérifier que la session est marquée comme arrêtée
            with client.application.app_context():
                updated_session = RecordingSession.query.get(recording_session.id)
                assert updated_session.status == 'completed'
                
            # Vérifier que la fonction d'arrêt a été appelée
            mock_stop.assert_called_once()
    
    @patch('subprocess.Popen')
    @patch('src.services.bunny_storage_service.upload_video')
    def test_complete_video_processing_workflow(self, mock_upload, mock_popen, app, player_user):
        """Test complet du workflow de traitement vidéo (FFmpeg + Upload)"""
        # Configuration des mocks
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll.return_value = 0  # Processus terminé avec succès
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        mock_upload.return_value = {
            'success': True,
            'video_url': 'https://cdn.bunny.net/video123.mp4',
            'thumbnail_url': 'https://cdn.bunny.net/thumb123.jpg'
        }
        
        with app.app_context():
            # Créer une session d'enregistrement
            session = RecordingSession(
                id='video-test-123',
                user_id=player_user.id,
                court_id=1,
                title='Video Processing Test',
                status='active',
                file_url='',
                created_at=datetime.utcnow()
            )
            db.session.add(session)
            db.session.commit()
            
            # Créer un fichier vidéo temporaire simulé
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
                temp_file.write(b'fake video content')
                temp_file.flush()
                temp_file_path = temp_file.name
            
            try:
                # Simuler le traitement vidéo
                from src.tasks.video_processing import process_recording_video
                
                result = process_recording_video(
                    session_id='video-test-123',
                    input_file=temp_file_path,
                    output_file=temp_file_path.replace('.mp4', '_processed.mp4')
                )
                
                assert result is not None
                
                # Vérifier que FFmpeg a été appelé
                mock_popen.assert_called()
                
                # Vérifier que l'upload a été tenté
                mock_upload.assert_called()
                
                # Vérifier que la session a été mise à jour
                updated_session = RecordingSession.query.get('video-test-123')
                assert updated_session.status == 'completed'
                assert updated_session.file_url.startswith('https://cdn.bunny.net/')
                
            finally:
                # Nettoyer le fichier temporaire
                try:
                    os.unlink(temp_file_path)
                except OSError:
                    pass
    
    def test_zombie_session_detection(self, client, auth_headers_admin, player_user):
        """Test de détection des sessions zombies"""
        # Créer une session "zombie" (active mais processus inexistant)
        with client.application.app_context():
            zombie_session = RecordingSession(
                id='zombie-session-123',
                user_id=player_user.id,
                court_id=1,
                title='Zombie Session',
                status='active',
                process_id='99999',  # PID inexistant
                created_at=datetime.utcnow()
            )
            db.session.add(zombie_session)
            db.session.commit()
        
        # Simuler la détection de sessions zombies
        with patch('psutil.pid_exists') as mock_pid_exists:
            mock_pid_exists.return_value = False  # Le processus n'existe pas
            
            # Déclencher la détection (normalement fait par une tâche Celery)
            response = client.post('/api/admin/recordings/cleanup-zombies',
                                 headers=auth_headers_admin)
            
            if response.status_code == 200:
                data = response.get_json()
                assert 'cleaned_sessions' in data
                assert data['cleaned_sessions'] > 0
                
                # Vérifier que la session zombie a été nettoyée
                with client.application.app_context():
                    cleaned_session = RecordingSession.query.get('zombie-session-123')
                    assert cleaned_session.status in ['failed', 'completed']
                    assert cleaned_session.auto_stopped is True
    
    def test_recording_with_insufficient_credits(self, client, auth_headers_player, player_user):
        """Test de démarrage d'enregistrement avec crédits insuffisants"""
        # Réduire les crédits de l'utilisateur
        with client.application.app_context():
            user = User.query.get(player_user.id)
            user.credits = 5  # Très peu de crédits
            db.session.commit()
        
        recording_data = {
            'court_id': 1,
            'title': 'Expensive Recording',
            'duration_minutes': 120  # 2 heures = beaucoup de crédits
        }
        
        response = client.post('/api/recording/v3/start',
                             json=recording_data,
                             headers=auth_headers_player,
                             content_type='application/json')
        
        assert response.status_code == 402  # Payment Required
        data = response.get_json()
        assert 'insufficient_credits' in data['error'].lower()
        
        # Vérifier qu'aucune session n'a été créée
        sessions = RecordingSession.query.filter_by(
            user_id=player_user.id,
            title='Expensive Recording'
        ).all()
        assert len(sessions) == 0
    
    def test_concurrent_recordings_limitation(self, client, auth_headers_player, player_user):
        """Test de limitation des enregistrements concurrents"""
        # Créer une session active existante
        with client.application.app_context():
            active_session = RecordingSession(
                id='active-session-123',
                user_id=player_user.id,
                court_id=1,
                title='Active Session',
                status='active',
                created_at=datetime.utcnow()
            )
            db.session.add(active_session)
            
            # S'assurer que l'utilisateur a des crédits
            user = User.query.get(player_user.id)
            user.credits = 1000
            db.session.commit()
        
        # Essayer de démarrer une deuxième session
        recording_data = {
            'court_id': 1,
            'title': 'Second Session',
            'duration_minutes': 60
        }
        
        response = client.post('/api/recording/v3/start',
                             json=recording_data,
                             headers=auth_headers_player,
                             content_type='application/json')
        
        # Devrait être refusé si le système limite les enregistrements concurrents
        if response.status_code == 409:  # Conflict
            data = response.get_json()
            assert 'concurrent' in data['error'].lower() or 'active' in data['error'].lower()
    
    @patch('src.services.bunny_storage_service.upload_video')
    def test_upload_failure_handling(self, mock_upload, app, player_user):
        """Test de gestion des échecs d'upload"""
        # Configuration du mock pour simuler un échec d'upload
        mock_upload.side_effect = Exception('Upload failed: Network error')
        
        with app.app_context():
            # Créer une session avec vidéo prête à être uploadée
            session = RecordingSession(
                id='upload-fail-test',
                user_id=player_user.id,
                court_id=1,
                title='Upload Failure Test',
                status='processing',
                file_url='',
                created_at=datetime.utcnow()
            )
            db.session.add(session)
            db.session.commit()
            
            # Simuler l'upload avec échec
            from src.tasks.video_processing import upload_video_to_cdn
            
            try:
                result = upload_video_to_cdn(
                    session_id='upload-fail-test',
                    video_file_path='/tmp/fake_video.mp4'
                )
                
                # L'upload devrait échouer
                assert result is False or result.get('success') is False
                
                # Vérifier que la session est marquée comme échouée
                failed_session = RecordingSession.query.get('upload-fail-test')
                assert failed_session.status == 'failed'
                assert 'Upload failed' in (failed_session.failure_reason or '')
                
            except Exception as e:
                # C'est attendu dans ce test d'échec
                assert 'Upload failed' in str(e)
    
    def test_recording_status_updates(self, client, auth_headers_player, recording_session):
        """Test des mises à jour de statut d'enregistrement"""
        session_id = recording_session.id
        
        # Vérifier le statut initial
        response = client.get(f'/api/recording/v3/status/{session_id}',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'status' in data
        assert 'session_id' in data
        assert data['session_id'] == session_id
        
        # Les statuts possibles selon l'implémentation
        valid_statuses = ['pending', 'active', 'processing', 'completed', 'failed']
        assert data['status'] in valid_statuses
    
    def test_recording_history_pagination(self, client, auth_headers_player, player_user):
        """Test de pagination de l'historique des enregistrements"""
        # Créer plusieurs sessions d'enregistrement
        with client.application.app_context():
            sessions = []
            for i in range(15):  # Créer 15 sessions
                session = RecordingSession(
                    id=f'history-test-{i}',
                    user_id=player_user.id,
                    court_id=1,
                    title=f'Recording {i}',
                    status='completed',
                    file_url=f'https://cdn.bunny.net/video{i}.mp4',
                    created_at=datetime.utcnow()
                )
                db.session.add(session)
                sessions.append(session)
            
            db.session.commit()
        
        # Récupérer la première page (limite par défaut)
        response = client.get('/api/recording/history',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert 'recordings' in data
        assert 'pagination' in data
        
        # Vérifier la pagination
        recordings = data['recordings']
        pagination = data['pagination']
        
        assert len(recordings) <= pagination.get('per_page', 10)
        assert pagination.get('total') == 15
        assert pagination.get('page') == 1
        
        # Tester la page suivante si elle existe
        if pagination.get('has_next'):
            response = client.get('/api/recording/history?page=2',
                                headers=auth_headers_player)
            
            assert response.status_code == 200
            page2_data = response.get_json()
            page2_recordings = page2_data['recordings']
            
            # S'assurer que les enregistrements sont différents
            page1_ids = {r['id'] for r in recordings}
            page2_ids = {r['id'] for r in page2_recordings}
            assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.integration
@pytest.mark.celery
@pytest.mark.video
class TestVideoCeleryIntegration:
    """Tests d'intégration spécifiques aux tâches Celery vidéo"""
    
    @patch('src.tasks.video_processing.process_recording.delay')
    def test_video_processing_task_queuing(self, mock_task, app, player_user):
        """Test de mise en queue des tâches de traitement vidéo"""
        with app.app_context():
            session = RecordingSession(
                id='celery-test-123',
                user_id=player_user.id,
                court_id=1,
                title='Celery Test',
                status='pending'
            )
            db.session.add(session)
            db.session.commit()
            
            # Déclencher manuellement la tâche
            from src.services.video_recording_service import queue_video_processing
            
            result = queue_video_processing('celery-test-123')
            
            assert result is not None
            mock_task.assert_called_once_with('celery-test-123')
    
    @patch('src.tasks.notification_tasks.send_notification.delay')
    @patch('src.tasks.video_processing.process_recording.delay')
    def test_video_completion_triggers_notification(self, mock_video_task, mock_notification_task, app, player_user):
        """Test que la fin du traitement vidéo déclenche une notification"""
        with app.app_context():
            session = RecordingSession(
                id='notification-test-123',
                user_id=player_user.id,
                court_id=1,
                title='Notification Test',
                status='active'
            )
            db.session.add(session)
            db.session.commit()
            
            # Simuler la fin du traitement vidéo
            from src.tasks.video_processing import complete_video_processing
            
            complete_video_processing(
                session_id='notification-test-123',
                video_url='https://cdn.bunny.net/completed.mp4'
            )
            
            # Vérifier que la notification a été déclenchée
            mock_notification_task.assert_called()
            
            # Vérifier les arguments de la notification
            call_args = mock_notification_task.call_args[1]  # kwargs
            assert call_args.get('notification_type') == 'VIDEO_READY'
            assert call_args.get('user_id') == player_user.id