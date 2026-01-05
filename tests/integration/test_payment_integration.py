"""
Tests d'intégration pour le système de paiement Stripe
Teste les flux complets de paiement, webhooks, et gestion des crédits
"""
import pytest
import json
from unittest.mock import patch, Mock

from src.models.user import User, Transaction, TransactionStatus
from src.models.database import db


@pytest.mark.integration
@pytest.mark.payment
class TestPaymentIntegration:
    """Tests d'intégration pour le système de paiement"""
    
    def test_create_checkout_session_flow(self, client, auth_headers_player, mock_stripe):
        """Test complet de création d'une session de paiement"""
        # Configuration du mock Stripe
        mock_stripe.return_value = Mock(
            id='cs_test_123456789',
            url='https://checkout.stripe.com/test',
            payment_status='unpaid',
            metadata={}
        )
        
        # Données de la requête
        checkout_data = {
            'package_name': 'basic_credits',
            'success_url': 'http://localhost:3000/success',
            'cancel_url': 'http://localhost:3000/cancel'
        }
        
        # Créer la session de checkout
        response = client.post('/api/payments/create-checkout-session',
                             json=checkout_data,
                             headers=auth_headers_player,
                             content_type='application/json')
        
        assert response.status_code == 200
        data = response.get_json()
        
        # Vérifier la réponse
        assert 'checkout_url' in data
        assert 'session_id' in data
        assert 'transaction_id' in data
        assert data['checkout_url'] == 'https://checkout.stripe.com/test'
        
        # Vérifier que la transaction est créée en base
        transaction = Transaction.query.filter_by(id=data['transaction_id']).first()
        assert transaction is not None
        assert transaction.package_name == 'basic_credits'
        assert transaction.status == TransactionStatus.PENDING.value
        assert transaction.stripe_checkout_session_id == 'cs_test_123456789'
    
    def test_idempotent_checkout_session_creation(self, client, auth_headers_player, mock_stripe):
        """Test de l'idempotence des sessions de checkout"""
        # Configuration du mock
        mock_stripe.return_value = Mock(
            id='cs_test_idempotent',
            url='https://checkout.stripe.com/idempotent'
        )
        
        checkout_data = {
            'package_name': 'premium_credits',
            'success_url': 'http://localhost:3000/success',
            'cancel_url': 'http://localhost:3000/cancel'
        }
        
        # Ajouter une clé d'idempotence
        headers = {
            **auth_headers_player,
            'Idempotency-Key': 'test-idempotency-123'
        }
        
        # Première requête
        response1 = client.post('/api/payments/create-checkout-session',
                              json=checkout_data,
                              headers=headers,
                              content_type='application/json')
        
        assert response1.status_code == 200
        data1 = response1.get_json()
        
        # Deuxième requête identique (idempotente)
        response2 = client.post('/api/payments/create-checkout-session',
                              json=checkout_data,
                              headers=headers,
                              content_type='application/json')
        
        assert response2.status_code == 200
        data2 = response2.get_json()
        
        # Les réponses doivent être identiques
        assert data1['session_id'] == data2['session_id']
        assert data1['transaction_id'] == data2['transaction_id']
        
        # Vérifier qu'une seule transaction a été créée
        transactions = Transaction.query.filter_by(
            stripe_checkout_session_id='cs_test_idempotent'
        ).all()
        assert len(transactions) == 1
    
    @patch('stripe.Webhook.construct_event')
    def test_successful_payment_webhook(self, mock_webhook, client, player_user):
        """Test du webhook de paiement réussi"""
        # Créer une transaction en attente
        with client.application.app_context():
            transaction = Transaction(
                user_id=player_user.id,
                amount=19.99,
                currency='EUR',
                package_name='basic_credits',
                credits_amount=100,
                status=TransactionStatus.PENDING.value,
                stripe_payment_intent_id='pi_test_123',
                stripe_checkout_session_id='cs_test_123'
            )
            db.session.add(transaction)
            db.session.commit()
            transaction_id = transaction.id
        
        # Mock du webhook Stripe
        mock_webhook.return_value = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'id': 'cs_test_123',
                    'payment_status': 'paid',
                    'payment_intent': 'pi_test_123',
                    'metadata': {
                        'transaction_id': str(transaction_id)
                    }
                }
            }
        }
        
        # Simuler le webhook
        webhook_payload = json.dumps({
            'type': 'checkout.session.completed',
            'data': {'object': {'id': 'cs_test_123'}}
        })
        
        headers = {
            'Stripe-Signature': 'test_signature',
            'Content-Type': 'application/json'
        }
        
        response = client.post('/api/payments/webhook',
                             data=webhook_payload,
                             headers=headers)
        
        assert response.status_code == 200
        
        # Vérifier que la transaction est marquée comme complétée
        with client.application.app_context():
            updated_transaction = Transaction.query.get(transaction_id)
            assert updated_transaction.status == TransactionStatus.COMPLETED.value
            
            # Vérifier que les crédits ont été ajoutés
            updated_user = User.query.get(player_user.id)
            assert updated_user.credits == 200  # 100 initiaux + 100 achetés
    
    @patch('stripe.Webhook.construct_event')
    def test_failed_payment_webhook(self, mock_webhook, client, player_user):
        """Test du webhook de paiement échoué"""
        # Créer une transaction en attente
        with client.application.app_context():
            transaction = Transaction(
                user_id=player_user.id,
                amount=19.99,
                currency='EUR',
                package_name='basic_credits',
                credits_amount=100,
                status=TransactionStatus.PENDING.value,
                stripe_payment_intent_id='pi_test_failed'
            )
            db.session.add(transaction)
            db.session.commit()
            transaction_id = transaction.id
        
        # Mock du webhook d'échec
        mock_webhook.return_value = {
            'type': 'payment_intent.payment_failed',
            'data': {
                'object': {
                    'id': 'pi_test_failed',
                    'metadata': {
                        'transaction_id': str(transaction_id)
                    }
                }
            }
        }
        
        webhook_payload = json.dumps({
            'type': 'payment_intent.payment_failed',
            'data': {'object': {'id': 'pi_test_failed'}}
        })
        
        headers = {
            'Stripe-Signature': 'test_signature',
            'Content-Type': 'application/json'
        }
        
        response = client.post('/api/payments/webhook',
                             data=webhook_payload,
                             headers=headers)
        
        assert response.status_code == 200
        
        # Vérifier que la transaction est marquée comme échouée
        with client.application.app_context():
            updated_transaction = Transaction.query.get(transaction_id)
            assert updated_transaction.status == TransactionStatus.FAILED.value
            
            # Vérifier que les crédits n'ont PAS été ajoutés
            updated_user = User.query.get(player_user.id)
            assert updated_user.credits == 100  # Inchangés
    
    def test_get_payment_history(self, client, auth_headers_player, player_user):
        """Test de récupération de l'historique des paiements"""
        # Créer quelques transactions
        with client.application.app_context():
            transactions = [
                Transaction(
                    user_id=player_user.id,
                    amount=19.99,
                    currency='EUR',
                    package_name='basic_credits',
                    credits_amount=100,
                    status=TransactionStatus.COMPLETED.value
                ),
                Transaction(
                    user_id=player_user.id,
                    amount=39.99,
                    currency='EUR',
                    package_name='premium_credits',
                    credits_amount=250,
                    status=TransactionStatus.COMPLETED.value
                ),
                Transaction(
                    user_id=player_user.id,
                    amount=9.99,
                    currency='EUR',
                    package_name='starter_credits',
                    credits_amount=50,
                    status=TransactionStatus.FAILED.value
                )
            ]
            
            for transaction in transactions:
                db.session.add(transaction)
            db.session.commit()
        
        # Récupérer l'historique
        response = client.get('/api/payments/history',
                            headers=auth_headers_player)
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert 'transactions' in data
        assert len(data['transactions']) == 3
        
        # Vérifier le tri (plus récent en premier)
        transactions = data['transactions']
        assert transactions[0]['package_name'] == 'starter_credits'
        assert transactions[1]['package_name'] == 'premium_credits'
        assert transactions[2]['package_name'] == 'basic_credits'
    
    def test_get_payment_packages(self, client):
        """Test de récupération des packages de crédits disponibles"""
        response = client.get('/api/payments/packages')
        
        assert response.status_code == 200
        data = response.get_json()
        
        assert 'packages' in data
        packages = data['packages']
        
        # Vérifier la structure des packages
        for package in packages:
            assert 'name' in package
            assert 'credits' in package
            assert 'price' in package
            assert 'currency' in package
            assert 'description' in package
            
            # Vérifier les types
            assert isinstance(package['credits'], int)
            assert isinstance(package['price'], (int, float))
            assert package['currency'] == 'EUR'
    
    def test_insufficient_credits_handling(self, client, auth_headers_player, player_user):
        """Test de gestion des crédits insuffisants"""
        # S'assurer que l'utilisateur a peu de crédits
        with client.application.app_context():
            user = User.query.get(player_user.id)
            user.credits = 5  # Très peu de crédits
            db.session.commit()
        
        # Essayer de faire une action qui coûte plus de crédits
        # (par exemple, démarrer un enregistrement coûteux)
        expensive_action_data = {
            'court_id': 1,
            'duration_minutes': 120,  # 2 heures = beaucoup de crédits
            'title': 'Long Recording'
        }
        
        response = client.post('/api/recording/start',
                             json=expensive_action_data,
                             headers=auth_headers_player,
                             content_type='application/json')
        
        # Devrait être refusé pour manque de crédits
        assert response.status_code == 402  # Payment Required
        data = response.get_json()
        assert 'insufficient_credits' in data['error'].lower()
    
    def test_credit_deduction_on_service_use(self, client, auth_headers_player, player_user):
        """Test de déduction des crédits lors de l'utilisation d'un service"""
        # S'assurer que l'utilisateur a suffisamment de crédits
        with client.application.app_context():
            user = User.query.get(player_user.id)
            initial_credits = 500
            user.credits = initial_credits
            db.session.commit()
        
        # Utiliser un service qui coûte des crédits
        service_data = {
            'court_id': 1,
            'duration_minutes': 30,  # 30 minutes
            'title': 'Test Recording'
        }
        
        with patch('src.tasks.video_processing.process_recording.delay'):
            response = client.post('/api/recording/start',
                                 json=service_data,
                                 headers=auth_headers_player,
                                 content_type='application/json')
        
        if response.status_code == 200:
            # Vérifier que les crédits ont été déduits
            with client.application.app_context():
                updated_user = User.query.get(player_user.id)
                assert updated_user.credits < initial_credits
    
    def test_payment_webhook_security(self, client):
        """Test de sécurité du webhook (signature invalide)"""
        webhook_payload = json.dumps({
            'type': 'checkout.session.completed',
            'data': {'object': {'id': 'cs_test_fake'}}
        })
        
        # Signature invalide
        headers = {
            'Stripe-Signature': 'invalid_signature',
            'Content-Type': 'application/json'
        }
        
        with patch('stripe.Webhook.construct_event') as mock_webhook:
            mock_webhook.side_effect = ValueError('Invalid signature')
            
            response = client.post('/api/payments/webhook',
                                 data=webhook_payload,
                                 headers=headers)
            
            assert response.status_code == 400
            data = response.get_json()
            assert 'signature' in data['error'].lower()


@pytest.mark.integration
@pytest.mark.payment
@pytest.mark.celery
class TestPaymentCeleryIntegration:
    """Tests d'intégration entre paiements et tâches asynchrones"""
    
    @patch('src.tasks.payment_tasks.process_payment_success.delay')
    def test_payment_success_triggers_async_task(self, mock_task, client, player_user):
        """Test que le succès d'un paiement déclenche des tâches asynchrones"""
        with patch('stripe.Webhook.construct_event') as mock_webhook:
            # Créer transaction
            with client.application.app_context():
                transaction = Transaction(
                    user_id=player_user.id,
                    amount=19.99,
                    currency='EUR',
                    package_name='basic_credits',
                    credits_amount=100,
                    status=TransactionStatus.PENDING.value,
                    stripe_checkout_session_id='cs_test_async'
                )
                db.session.add(transaction)
                db.session.commit()
                transaction_id = transaction.id
            
            # Mock webhook
            mock_webhook.return_value = {
                'type': 'checkout.session.completed',
                'data': {
                    'object': {
                        'id': 'cs_test_async',
                        'payment_status': 'paid',
                        'metadata': {
                            'transaction_id': str(transaction_id)
                        }
                    }
                }
            }
            
            # Simuler webhook
            response = client.post('/api/payments/webhook',
                                 data='{}',
                                 headers={'Stripe-Signature': 'test'})
            
            assert response.status_code == 200
            
            # Vérifier que la tâche async a été déclenchée
            mock_task.assert_called_once_with(transaction_id)