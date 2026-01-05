# src/routes/payment.py

"""
Routes API pour la gestion des paiements Stripe
Gère l'achat de crédits, les webhooks et l'historique des transactions
"""

import logging
import stripe
from flask import Blueprint, request, jsonify, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from ..services.payment_service import payment_service, CREDIT_PACKAGES
from ..models.user import User, Transaction
from ..middleware.rate_limiting import limiter
from .auth import require_auth, get_current_user

logger = logging.getLogger(__name__)

payment_bp = Blueprint('payment', __name__)

@payment_bp.route('/packages', methods=['GET'])
def get_credit_packages():
    """
    Retourne la liste des packages de crédits disponibles
    """
    try:
        packages = []
        for package_id, package_data in CREDIT_PACKAGES.items():
            packages.append({
                'id': package_id,
                'name': package_data['name'],
                'description': package_data['description'],
                'credits': package_data['credits'],
                'price_euros': package_data['price_cents'] / 100.0,
                'currency': package_data['currency'],
                'price_per_credit': round(package_data['price_cents'] / 100.0 / package_data['credits'], 2)
            })
        
        return jsonify({
            'success': True,
            'packages': packages
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des packages: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500

@payment_bp.route('/create-checkout-session', methods=['POST'])
@require_auth
@limiter.limit("10 per minute")  # Protection contre le spam
def create_checkout_session():
    """
    Crée une session de paiement Stripe
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Données JSON requises'
            }), 400
        
        package_id = data.get('package_id')
        if not package_id:
            return jsonify({
                'success': False,
                'error': 'package_id requis'
            }), 400
        
        if package_id not in CREDIT_PACKAGES:
            return jsonify({
                'success': False,
                'error': f'Package {package_id} non valide'
            }), 400
        
        user = get_current_user()
        if not user:
            return jsonify({
                'success': False,
                'error': 'Utilisateur non authentifié'
            }), 401
        
        # URLs de retour personnalisées (optionnelles)
        success_url = data.get('success_url')
        cancel_url = data.get('cancel_url')
        
        # Créer la session de paiement
        result = payment_service.create_checkout_session(
            user_id=user.id,
            package_id=package_id,
            success_url=success_url,
            cancel_url=cancel_url
        )
        
        if result['success']:
            logger.info(f"Session de paiement créée pour utilisateur {user.id}, package {package_id}")
            return jsonify(result), 200
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Erreur lors de la création de session de paiement: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500

@payment_bp.route('/webhook', methods=['POST'])
@limiter.exempt  # Les webhooks Stripe ne doivent pas être limités
def stripe_webhook():
    """
    Endpoint webhook Stripe sécurisé
    Traite les événements de paiement
    """
    payload = request.get_data()
    signature = request.headers.get('Stripe-Signature')
    
    if not signature:
        logger.warning("Webhook reçu sans signature")
        return jsonify({'error': 'Signature manquante'}), 400
    
    try:
        # Vérification de la signature
        event = payment_service.verify_webhook_signature(payload, signature)
        
        logger.info(f"Webhook Stripe reçu: {event['type']}")
        
        # Traitement selon le type d'événement
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            
            try:
                # Traiter le paiement réussi
                transaction = payment_service.handle_successful_payment(session['id'])
                
                logger.info(f"Paiement traité avec succès - Transaction: {transaction.id}")
                
            except Exception as e:
                logger.error(f"Erreur lors du traitement du paiement réussi: {str(e)}")
                return jsonify({'error': 'Erreur de traitement'}), 500
        
        elif event['type'] == 'checkout.session.expired':
            session = event['data']['object']
            payment_service.handle_failed_payment(session['id'], "Session expirée")
            
        elif event['type'] == 'payment_intent.payment_failed':
            payment_intent = event['data']['object']
            # Récupérer la session associée via les métadonnées
            if 'transaction_id' in payment_intent.get('metadata', {}):
                payment_service.handle_failed_payment(
                    payment_intent['metadata']['transaction_id'],
                    "Paiement échoué"
                )
        
        else:
            logger.info(f"Événement webhook non traité: {event['type']}")
        
        return jsonify({'status': 'success'}), 200
        
    except ValueError:
        logger.error("Payload webhook invalide")
        return jsonify({'error': 'Payload invalide'}), 400
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement du webhook: {str(e)}")
        return jsonify({'error': 'Erreur de traitement'}), 500

@payment_bp.route('/transaction/<int:transaction_id>/status', methods=['GET'])
@require_auth
def get_transaction_status(transaction_id):
    """
    Récupère le statut d'une transaction
    """
    try:
        user = get_current_user()
        
        # Vérifier que la transaction appartient à l'utilisateur
        transaction = Transaction.query.filter_by(
            id=transaction_id,
            user_id=user.id
        ).first()
        
        if not transaction:
            return jsonify({
                'success': False,
                'error': 'Transaction non trouvée'
            }), 404
        
        status = payment_service.get_transaction_status(transaction_id)
        
        return jsonify({
            'success': True,
            'transaction': status
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500

@payment_bp.route('/transactions', methods=['GET'])
@require_auth
def get_user_transactions():
    """
    Récupère l'historique des transactions de l'utilisateur
    """
    try:
        user = get_current_user()
        limit = request.args.get('limit', 10, type=int)
        
        # Limiter le nombre de transactions retournées
        if limit > 50:
            limit = 50
        
        transactions = payment_service.get_user_transactions(user.id, limit)
        
        return jsonify({
            'success': True,
            'transactions': transactions,
            'user': {
                'id': user.id,
                'credits_balance': user.credits_balance
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des transactions: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500

@payment_bp.route('/user/credits', methods=['GET'])
@require_auth
def get_user_credits():
    """
    Récupère le solde de crédits de l'utilisateur
    """
    try:
        user = get_current_user()
        
        return jsonify({
            'success': True,
            'user_id': user.id,
            'credits_balance': user.credits_balance,
            'email': user.email,
            'name': user.name
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des crédits: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500

# Route pour tester la configuration Stripe (développement seulement)
@payment_bp.route('/test-config', methods=['GET'])
def test_stripe_config():
    """
    Teste la configuration Stripe (développement uniquement)
    """
    if current_app.config.get('FLASK_ENV') != 'development':
        return jsonify({'error': 'Endpoint disponible uniquement en développement'}), 403
    
    try:
        stripe_key = current_app.config.get('STRIPE_SECRET_KEY')
        webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
        
        config_status = {
            'stripe_secret_key_configured': bool(stripe_key),
            'stripe_webhook_secret_configured': bool(webhook_secret),
            'packages_count': len(CREDIT_PACKAGES)
        }
        
        return jsonify({
            'success': True,
            'config': config_status
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500