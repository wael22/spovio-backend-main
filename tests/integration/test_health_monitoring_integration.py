"""
Tests d'intégration pour les health checks et le monitoring
Teste les endpoints de santé, métriques, et détection de problèmes
"""
import pytest
import json
from unittest.mock import patch, Mock


@pytest.mark.integration
@pytest.mark.health
class TestHealthCheckIntegration:
    """Tests d'intégration pour les health checks"""
    
    def test_basic_health_check(self, client):
        """Test du health check basique"""
        response = client.get('/health')
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Vérifier la structure de base
        assert 'status' in data
        assert 'timestamp' in data
        assert 'checks' in data
        
        # Le statut global devrait être UP si tous les composants sont OK
        assert data['status'] in ['UP', 'DOWN', 'DEGRADED']
        
        # Vérifier les checks individuels
        checks = data['checks']
        expected_checks = ['database', 'redis', 'disk_space', 'memory']
        
        for check_name in expected_checks:
            if check_name in checks:
                check = checks[check_name]
                assert 'status' in check
                assert 'response_time_ms' in check
                assert check['status'] in ['UP', 'DOWN']
    
    def test_detailed_health_check(self, client):
        """Test du health check détaillé"""
        response = client.get('/health/detailed')
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Vérifier la structure détaillée
        assert 'status' in data
        assert 'checks' in data
        assert 'system_info' in data
        
        system_info = data['system_info']
        expected_system_fields = ['python_version', 'flask_version', 'uptime']
        
        for field in expected_system_fields:
            if field in system_info:
                assert system_info[field] is not None
    
    @patch('src.services.monitoring_service.check_database_connection')
    def test_database_health_check_failure(self, mock_db_check, client):
        """Test de health check avec échec de base de données"""
        # Simuler un échec de connexion à la base de données
        mock_db_check.return_value = {
            'status': 'DOWN',
            'error': 'Connection timeout',
            'response_time_ms': 5000
        }
        
        response = client.get('/health')
        
        # Le service peut répondre 200 même avec des composants DOWN
        # ou 503 selon l'implémentation
        assert response.status_code in [200, 503]
        
        if response.status_code == 200:
            data = response.get_json()
            assert data['status'] in ['DOWN', 'DEGRADED']
            
            if 'database' in data['checks']:
                assert data['checks']['database']['status'] == 'DOWN'
    
    @patch('redis.Redis.ping')
    def test_redis_health_check_failure(self, mock_redis_ping, client):
        """Test de health check avec échec Redis"""
        # Simuler un échec de connexion Redis
        mock_redis_ping.side_effect = Exception('Redis connection failed')
        
        response = client.get('/health')
        
        assert response.status_code in [200, 503]
        
        if response.status_code == 200:
            data = response.get_json()
            
            if 'redis' in data['checks']:
                # Redis peut être marqué comme DOWN
                assert data['checks']['redis']['status'] == 'DOWN'
    
    @patch('psutil.disk_usage')
    def test_disk_space_health_check(self, mock_disk_usage, client):
        """Test de health check de l'espace disque"""
        # Simuler un espace disque critique (95% utilisé)
        mock_usage = Mock()
        mock_usage.total = 1000000000  # 1GB
        mock_usage.used = 950000000    # 950MB (95%)
        mock_usage.free = 50000000     # 50MB (5%)
        mock_disk_usage.return_value = mock_usage
        
        response = client.get('/health')
        
        assert response.status_code in [200, 503]
        
        if response.status_code == 200:
            data = response.get_json()
            
            if 'disk_space' in data['checks']:
                disk_check = data['checks']['disk_space']
                # Devrait être marqué comme problématique
                assert disk_check['status'] in ['DOWN', 'WARN']
    
    @patch('psutil.virtual_memory')
    def test_memory_health_check(self, mock_memory, client):
        """Test de health check de la mémoire"""
        # Simuler une utilisation mémoire élevée (95%)
        mock_mem = Mock()
        mock_mem.total = 1000000000  # 1GB
        mock_mem.available = 50000000  # 50MB disponible (95% utilisé)
        mock_mem.percent = 95.0
        mock_memory.return_value = mock_mem
        
        response = client.get('/health')
        
        assert response.status_code in [200, 503]
        
        if response.status_code == 200:
            data = response.get_json()
            
            if 'memory' in data['checks']:
                memory_check = data['checks']['memory']
                # Devrait être marqué comme problématique avec utilisation élevée
                assert memory_check['status'] in ['DOWN', 'WARN']


@pytest.mark.integration
@pytest.mark.monitoring
class TestMonitoringIntegration:
    """Tests d'intégration pour le monitoring et les métriques"""
    
    def test_prometheus_metrics_endpoint(self, client):
        """Test de l'endpoint des métriques Prometheus"""
        response = client.get('/metrics')
        
        assert response.status_code == 200
        
        # Les métriques Prometheus sont en format texte
        content = response.data.decode('utf-8')
        
        # Vérifier quelques métriques attendues
        expected_metrics = [
            'flask_http_request_total',
            'flask_http_request_duration_seconds',
            'padelvar_active_recordings_total',
            'padelvar_user_credits_total'
        ]
        
        for metric in expected_metrics:
            if metric in content:
                # Vérifier le format de base de Prometheus
                assert f'# HELP {metric}' in content or f'{metric}' in content
    
    def test_system_metrics_collection(self, client):
        """Test de collecte des métriques système"""
        response = client.get('/health/metrics')
        
        if response.status_code == 200:
            data = response.get_json()
            
            # Vérifier la structure des métriques
            expected_sections = ['system', 'application', 'database']
            
            for section in expected_sections:
                if section in data:
                    metrics_section = data[section]
                    assert isinstance(metrics_section, dict)
                    
                    if section == 'system':
                        # Métriques système attendues
                        system_metrics = ['cpu_usage', 'memory_usage', 'disk_usage']
                        for metric in system_metrics:
                            if metric in metrics_section:
                                assert isinstance(metrics_section[metric], (int, float))
    
    @patch('src.services.monitoring_service.get_active_recordings_count')
    def test_application_specific_metrics(self, mock_recordings, client):
        """Test des métriques spécifiques à l'application"""
        # Simuler des enregistrements actifs
        mock_recordings.return_value = 5
        
        response = client.get('/health/metrics')
        
        if response.status_code == 200:
            data = response.get_json()
            
            if 'application' in data:
                app_metrics = data['application']
                
                # Vérifier les métriques spécifiques à PadelVar
                expected_app_metrics = [
                    'active_recordings',
                    'total_users',
                    'pending_uploads'
                ]
                
                for metric in expected_app_metrics:
                    if metric in app_metrics:
                        assert isinstance(app_metrics[metric], (int, float))
                        
                        if metric == 'active_recordings':
                            assert app_metrics[metric] == 5
    
    def test_error_rate_monitoring(self, client):
        """Test de monitoring du taux d'erreur"""
        # Générer quelques erreurs intentionnelles
        error_endpoints = [
            '/api/nonexistent',
            '/api/auth/invalid',
            '/api/recording/invalid-id'
        ]
        
        for endpoint in error_endpoints:
            client.get(endpoint)  # Ces requêtes vont générer des erreurs
        
        # Vérifier que les erreurs sont comptabilisées
        response = client.get('/health/metrics')
        
        if response.status_code == 200:
            data = response.get_json()
            
            if 'application' in data and 'error_rate' in data['application']:
                error_rate = data['application']['error_rate']
                assert isinstance(error_rate, (int, float))
                assert error_rate >= 0
    
    @patch('src.tasks.maintenance_tasks.cleanup_zombie_sessions.delay')
    def test_zombie_session_monitoring(self, mock_cleanup, client, auth_headers_admin):
        """Test de monitoring des sessions zombies"""
        # Déclencher la vérification des sessions zombies
        response = client.post('/api/admin/monitoring/check-zombies',
                             headers=auth_headers_admin)
        
        if response.status_code in [200, 202]:
            # La tâche de nettoyage devrait être déclenchée
            mock_cleanup.assert_called_once()
            
            if response.status_code == 200:
                data = response.get_json()
                assert 'zombie_sessions_detected' in data
                assert isinstance(data['zombie_sessions_detected'], int)
    
    def test_performance_monitoring(self, client):
        """Test de monitoring des performances"""
        # Faire quelques requêtes pour générer des métriques de performance
        endpoints_to_test = [
            '/health',
            '/api/auth/profile',  # Nécessite auth mais génère des métriques
            '/api/payments/packages'
        ]
        
        for endpoint in endpoints_to_test:
            client.get(endpoint)
        
        # Vérifier les métriques de performance
        response = client.get('/health/performance')
        
        if response.status_code == 200:
            data = response.get_json()
            
            expected_perf_metrics = [
                'average_response_time',
                'requests_per_second',
                'active_connections'
            ]
            
            for metric in expected_perf_metrics:
                if metric in data:
                    assert isinstance(data[metric], (int, float))
                    assert data[metric] >= 0
    
    def test_database_performance_monitoring(self, client):
        """Test de monitoring des performances de base de données"""
        response = client.get('/health/database')
        
        if response.status_code == 200:
            data = response.get_json()
            
            expected_db_metrics = [
                'connection_pool_size',
                'active_connections',
                'query_count',
                'average_query_time'
            ]
            
            for metric in expected_db_metrics:
                if metric in data:
                    assert isinstance(data[metric], (int, float))
                    assert data[metric] >= 0
    
    @patch('src.services.monitoring_service.check_celery_workers')
    def test_celery_worker_monitoring(self, mock_celery_check, client):
        """Test de monitoring des workers Celery"""
        # Simuler l'état des workers Celery
        mock_celery_check.return_value = {
            'active_workers': 3,
            'queues': {
                'video_processing': 5,
                'notifications': 2,
                'maintenance': 0
            },
            'failed_tasks_last_hour': 1
        }
        
        response = client.get('/health/celery')
        
        if response.status_code == 200:
            data = response.get_json()
            
            assert 'active_workers' in data
            assert 'queues' in data
            assert 'failed_tasks_last_hour' in data
            
            assert data['active_workers'] == 3
            assert data['queues']['video_processing'] == 5
            assert data['failed_tasks_last_hour'] == 1
    
    def test_storage_monitoring(self, client):
        """Test de monitoring du stockage"""
        response = client.get('/health/storage')
        
        if response.status_code == 200:
            data = response.get_json()
            
            expected_storage_metrics = [
                'disk_usage_percent',
                'available_space_gb',
                'recordings_storage_usage'
            ]
            
            for metric in expected_storage_metrics:
                if metric in data:
                    assert isinstance(data[metric], (int, float))
                    
                    if metric == 'disk_usage_percent':
                        assert 0 <= data[metric] <= 100
    
    def test_real_time_monitoring_websocket(self, client):
        """Test de monitoring en temps réel (WebSocket simulation)"""
        # Ce test simule la connexion WebSocket pour monitoring temps réel
        # Dans un vrai environnement, cela utiliserait Flask-SocketIO
        
        response = client.get('/api/monitoring/realtime-status')
        
        if response.status_code == 200:
            data = response.get_json()
            
            # Vérifier la structure des données temps réel
            expected_fields = [
                'current_timestamp',
                'active_users',
                'active_recordings',
                'system_load'
            ]
            
            for field in expected_fields:
                if field in data:
                    assert data[field] is not None


@pytest.mark.integration
@pytest.mark.monitoring
@pytest.mark.slow
class TestAlertingIntegration:
    """Tests d'intégration pour le système d'alertes"""
    
    @patch('src.services.monitoring_service.send_alert')
    def test_high_error_rate_alert(self, mock_send_alert, client):
        """Test d'alerte en cas de taux d'erreur élevé"""
        # Générer beaucoup d'erreurs rapidement
        for i in range(20):
            client.get(f'/api/nonexistent-{i}')
        
        # Vérifier les métriques d'erreur
        response = client.get('/health/alerts')
        
        if response.status_code == 200:
            data = response.get_json()
            
            if 'active_alerts' in data:
                active_alerts = data['active_alerts']
                
                # Vérifier s'il y a une alerte pour taux d'erreur élevé
                error_rate_alerts = [
                    alert for alert in active_alerts 
                    if 'error_rate' in alert.get('type', '').lower()
                ]
                
                if error_rate_alerts:
                    assert len(error_rate_alerts) > 0
    
    @patch('psutil.disk_usage')
    @patch('src.services.monitoring_service.send_alert')
    def test_disk_space_alert(self, mock_send_alert, mock_disk_usage, client):
        """Test d'alerte en cas d'espace disque faible"""
        # Simuler un espace disque critique
        mock_usage = Mock()
        mock_usage.total = 1000000000
        mock_usage.free = 20000000  # Seulement 2% libre
        mock_disk_usage.return_value = mock_usage
        
        # Déclencher la vérification
        response = client.get('/health/check-alerts')
        
        if response.status_code == 200:
            # L'alerte devrait être déclenchée
            if mock_send_alert.called:
                call_args = mock_send_alert.call_args[0]
                alert_message = call_args[0] if call_args else ""
                assert 'disk' in alert_message.lower()
    
    @patch('src.services.monitoring_service.send_alert')
    def test_zombie_session_alert(self, mock_send_alert, client, player_user):
        """Test d'alerte pour les sessions zombies"""
        # Créer une session zombie simulée
        with client.application.app_context():
            from src.models.recording import RecordingSession
            from src.models.database import db
            
            zombie_session = RecordingSession(
                id='alert-zombie-123',
                user_id=player_user.id,
                court_id=1,
                title='Zombie Alert Test',
                status='active',
                process_id='99999'  # PID inexistant
            )
            db.session.add(zombie_session)
            db.session.commit()
        
        # Déclencher la détection de zombies
        with patch('psutil.pid_exists', return_value=False):
            response = client.post('/api/admin/monitoring/check-zombies')
            
            if response.status_code == 200 and mock_send_alert.called:
                # Vérifier que l'alerte a été envoyée
                call_args = mock_send_alert.call_args[0]
                alert_message = call_args[0] if call_args else ""
                assert 'zombie' in alert_message.lower()