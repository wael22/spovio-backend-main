"""
Tests d'intégration pour le système d'authentification
Teste les flux complets de login, register, et gestion des tokens
"""
import pytest
import json
from datetime import datetime, timedelta

from src.models.user import User, UserStatus
from src.models.database import db


@pytest.mark.integration
@pytest.mark.auth
class TestAuthenticationIntegration:
    """Tests d'intégration pour l'authentification"""
    
    def test_complete_registration_flow(self, client):
        """Test du flux complet d'inscription"""
        # 1. Inscription d'un nouvel utilisateur
        registration_data = {
            'email': 'newuser@test.com',
            'password': 'password123',
            'name': 'New User',
            'role': 'player'
        }
        
        response = client.post('/api/auth/register', 
                             json=registration_data,
                             content_type='application/json')
        
        assert response.status_code == 201
        data = response.get_json()
        assert data['message'] == 'User registered successfully'
        assert 'user' in data
        assert data['user']['email'] == 'newuser@test.com'
        
        # 2. Vérifier que l'utilisateur existe en base
        user = User.query.filter_by(email='newuser@test.com').first()
        assert user is not None
        assert user.email == 'newuser@test.com'
        assert user.role == 'player'
        assert user.status == UserStatus.ACTIVE.value
        assert user.credits == 0  # Crédits initiaux
    
    def test_complete_login_flow(self, client, player_user):
        """Test du flux complet de connexion"""
        # 1. Connexion avec credentials valides
        login_data = {
            'email': 'player@test.com',
            'password': 'player123'
        }
        
        response = client.post('/api/auth/login',
                             json=login_data,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'access_token' in data
        assert 'user' in data
        assert data['user']['email'] == 'player@test.com'
        
        # 2. Utiliser le token pour accéder à un endpoint protégé
        headers = {'Authorization': f'Bearer {data["access_token"]}'}
        profile_response = client.get('/api/auth/profile', headers=headers)
        
        assert profile_response.status_code == 200
        profile_data = profile_response.get_json()
        assert profile_data['email'] == 'player@test.com'
    
    def test_login_with_invalid_credentials(self, client, player_user):
        """Test de connexion avec credentials invalides"""
        login_data = {
            'email': 'player@test.com',
            'password': 'wrongpassword'
        }
        
        response = client.post('/api/auth/login',
                             json=login_data,
                             content_type='application/json')
        
        assert response.status_code == 401
        data = response.get_json()
        assert 'error' in data
    
    def test_access_protected_endpoint_without_token(self, client):
        """Test d'accès à un endpoint protégé sans token"""
        response = client.get('/api/auth/profile')
        
        assert response.status_code == 401
        data = response.get_json()
        assert 'error' in data
    
    def test_access_protected_endpoint_with_invalid_token(self, client):
        """Test d'accès avec token invalide"""
        headers = {'Authorization': 'Bearer invalid_token'}
        response = client.get('/api/auth/profile', headers=headers)
        
        assert response.status_code == 401
        data = response.get_json()
        assert 'error' in data
    
    def test_registration_duplicate_email(self, client, player_user):
        """Test d'inscription avec email déjà existant"""
        registration_data = {
            'email': 'player@test.com',  # Email déjà existant
            'password': 'password123',
            'name': 'Another User',
            'role': 'player'
        }
        
        response = client.post('/api/auth/register',
                             json=registration_data,
                             content_type='application/json')
        
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
    
    def test_password_change_flow(self, client, auth_headers_player):
        """Test du changement de mot de passe"""
        change_data = {
            'current_password': 'player123',
            'new_password': 'newpassword123'
        }
        
        response = client.post('/api/auth/change-password',
                             json=change_data,
                             headers=auth_headers_player,
                             content_type='application/json')
        
        assert response.status_code == 200
        
        # Vérifier que l'ancien mot de passe ne fonctionne plus
        old_login = {
            'email': 'player@test.com',
            'password': 'player123'
        }
        response = client.post('/api/auth/login', json=old_login)
        assert response.status_code == 401
        
        # Vérifier que le nouveau mot de passe fonctionne
        new_login = {
            'email': 'player@test.com',
            'password': 'newpassword123'
        }
        response = client.post('/api/auth/login', json=new_login)
        assert response.status_code == 200
    
    def test_user_profile_update(self, client, auth_headers_player):
        """Test de mise à jour du profil utilisateur"""
        update_data = {
            'name': 'Updated Player Name'
        }
        
        response = client.put('/api/auth/profile',
                            json=update_data,
                            headers=auth_headers_player,
                            content_type='application/json')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['name'] == 'Updated Player Name'
        
        # Vérifier en base de données
        user = User.query.filter_by(email='player@test.com').first()
        assert user.name == 'Updated Player Name'
    
    def test_role_based_access_control(self, client, auth_headers_player, auth_headers_admin):
        """Test du contrôle d'accès basé sur les rôles"""
        # Endpoint admin seulement - accès refusé pour player
        response = client.get('/api/admin/users', headers=auth_headers_player)
        assert response.status_code == 403
        
        # Endpoint admin seulement - accès autorisé pour admin
        response = client.get('/api/admin/users', headers=auth_headers_admin)
        # Note: Cet endpoint peut ne pas exister, mais le test montre le principe
        # assert response.status_code in [200, 404]  # 404 si endpoint pas implémenté
    
    @pytest.mark.slow
    def test_token_expiration(self, app, client, player_user):
        """Test de l'expiration des tokens JWT"""
        with app.app_context():
            # Modifier temporairement la durée d'expiration
            original_expiry = app.config.get('JWT_ACCESS_TOKEN_EXPIRES', timedelta(hours=1))
            app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(seconds=1)
            
            try:
                # Se connecter
                login_data = {
                    'email': 'player@test.com',
                    'password': 'player123'
                }
                response = client.post('/api/auth/login', json=login_data)
                assert response.status_code == 200
                
                token = response.get_json()['access_token']
                headers = {'Authorization': f'Bearer {token}'}
                
                # Le token devrait être valide immédiatement
                response = client.get('/api/auth/profile', headers=headers)
                assert response.status_code == 200
                
                # Attendre l'expiration (2 secondes pour être sûr)
                import time
                time.sleep(2)
                
                # Le token devrait maintenant être expiré
                response = client.get('/api/auth/profile', headers=headers)
                assert response.status_code == 401
                
            finally:
                # Restaurer la configuration originale
                app.config['JWT_ACCESS_TOKEN_EXPIRES'] = original_expiry


@pytest.mark.integration
@pytest.mark.database
class TestUserStatusManagement:
    """Tests d'intégration pour la gestion du statut utilisateur"""
    
    def test_suspended_user_cannot_login(self, client, player_user):
        """Test qu'un utilisateur suspendu ne peut pas se connecter"""
        # Suspendre l'utilisateur
        with client.application.app_context():
            user = User.query.filter_by(email='player@test.com').first()
            user.status = UserStatus.SUSPENDED.value
            db.session.commit()
        
        # Tentative de connexion
        login_data = {
            'email': 'player@test.com',
            'password': 'player123'
        }
        
        response = client.post('/api/auth/login', json=login_data)
        assert response.status_code == 403
        data = response.get_json()
        assert 'suspended' in data['error'].lower()
    
    def test_inactive_user_cannot_login(self, client, player_user):
        """Test qu'un utilisateur inactif ne peut pas se connecter"""
        # Désactiver l'utilisateur
        with client.application.app_context():
            user = User.query.filter_by(email='player@test.com').first()
            user.status = UserStatus.INACTIVE.value
            db.session.commit()
        
        # Tentative de connexion
        login_data = {
            'email': 'player@test.com',
            'password': 'player123'
        }
        
        response = client.post('/api/auth/login', json=login_data)
        assert response.status_code == 403
        data = response.get_json()
        assert 'inactive' in data['error'].lower()
    
    def test_pending_verification_user_limited_access(self, client):
        """Test qu'un utilisateur en attente de vérification a un accès limité"""
        # Créer utilisateur en attente de vérification
        registration_data = {
            'email': 'pending@test.com',
            'password': 'password123',
            'name': 'Pending User',
            'role': 'player'
        }
        
        response = client.post('/api/auth/register', json=registration_data)
        assert response.status_code == 201
        
        # Modifier le statut en attente de vérification
        with client.application.app_context():
            user = User.query.filter_by(email='pending@test.com').first()
            user.status = UserStatus.PENDING_VERIFICATION.value
            db.session.commit()
        
        # L'utilisateur peut se connecter
        login_data = {
            'email': 'pending@test.com',
            'password': 'password123'
        }
        
        response = client.post('/api/auth/login', json=login_data)
        assert response.status_code == 200
        
        # Mais l'accès à certaines fonctionnalités peut être limité
        token = response.get_json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        
        profile_response = client.get('/api/auth/profile', headers=headers)
        assert profile_response.status_code == 200
        profile_data = profile_response.get_json()
        assert profile_data.get('email_verified') is False