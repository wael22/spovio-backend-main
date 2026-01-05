# src/services/payment_service.py

"""
Service de paiement Stripe pour PadelVar
Gère l'achat de crédits, les sessions de paiement et les webhooks
"""

import os
import stripe
import uuid
import logging
from datetime import datetime, timedelta
from flask import url_for, current_app
from sqlalchemy.exc import SQLAlchemyError

from ..models.database import db
from ..models.user import User, Transaction, TransactionStatus
from ..tasks.notification_tasks import send_notification

logger = logging.getLogger(__name__)

# Configuration des packages de crédits
CREDIT_PACKAGES = {
    'pack_10': {
        'credits': 10,
        'price_cents': 500,  # 5.00 EUR en centimes
        'currency': 'eur',
        'name': 'Pack Découverte',
        'description': '10 crédits pour débuter'
    },
    'pack_50': {
        'credits': 50,
        'price_cents': 2000,  # 20.00 EUR
        'currency': 'eur',
        'name': 'Pack Standard',
        'description': '50 crédits pour joueurs réguliers'
    },
    'pack_100': {
        'credits': 100,
        'price_cents': 3500,  # 35.00 EUR
        'currency': 'eur',
        'name': 'Pack Avancé',
        'description': '100 crédits avec remise'
    },
    'pack_500': {
        'credits': 500,
        'price_cents': 15000,  # 150.00 EUR
        'currency': 'eur',
        'name': 'Pack Club',
        'description': '500 crédits pour les clubs'
    }
}

class PaymentService:
    """Service principal pour la gestion des paiements"""
    
    def __init__(self, stripe_api_key=None):
        self.stripe = stripe
        self.stripe.api_key = stripe_api_key or os.environ.get('STRIPE_SECRET_KEY')
        if not self.stripe.api_key:
            logger.warning("STRIPE_SECRET_KEY non configurée")
    
    def create_checkout_session(self, user_id, package_id, success_url=None, cancel_url=None):
        """
        Crée une session de paiement Stripe
        
        Args:
            user_id (int): ID de l'utilisateur
            package_id (str): ID du package de crédits
            success_url (str): URL de retour en cas de succès
            cancel_url (str): URL de retour en cas d'annulation
            
        Returns:
            dict: Résultat avec l'URL de paiement et les informations de transaction
        """
        try:
            # Validation du package
            if package_id not in CREDIT_PACKAGES:
                raise ValueError(f"Package {package_id} non trouvé")
            
            package = CREDIT_PACKAGES[package_id]
            
            # Vérifier que l'utilisateur existe
            user = User.query.get(user_id)
            if not user:
                raise ValueError(f"Utilisateur {user_id} non trouvé")
            
            # Générer une clé d'idempotence unique
            idempotency_key = str(uuid.uuid4())
            
            # Créer la transaction en base (statut pending)
            transaction = Transaction(
                idempotency_key=idempotency_key,
                user_id=user_id,
                transaction_type='credit_purchase',
                package_name=package_id,
                credits_amount=package['credits'],
                amount_cents=package['price_cents'],
                currency=package['currency'],
                status=TransactionStatus.PENDING,
                payment_gateway='stripe',
                description=f"Achat de {package['name']} - {package['credits']} crédits"
            )
            
            db.session.add(transaction)
            db.session.commit()
            
            # URLs par défaut si non fournies
            if not success_url:
                success_url = url_for('frontend.payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}'
            if not cancel_url:
                cancel_url = url_for('frontend.payment_cancel', _external=True)
            
            # Créer la session Stripe
            checkout_session = self.stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': package['currency'],
                        'product_data': {
                            'name': package['name'],
                            'description': package['description'],
                            'images': [url_for('static', filename='images/credits-icon.png', _external=True)]
                        },
                        'unit_amount': package['price_cents'],
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=user.email,
                metadata={
                    'transaction_id': str(transaction.id),
                    'user_id': str(user_id),
                    'package_id': package_id,
                    'idempotency_key': idempotency_key
                },
                # Configuration pour éviter les doublons
                payment_intent_data={
                    'metadata': {
                        'transaction_id': str(transaction.id),
                        'user_id': str(user_id)
                    }
                },
                expires_at=int((datetime.utcnow() + timedelta(minutes=30)).timestamp())  # Expire après 30 min
            )
            
            # Sauvegarder l'ID de session Stripe
            transaction.payment_gateway_id = checkout_session.id
            transaction.payment_intent_id = checkout_session.payment_intent
            db.session.commit()
            
            logger.info(f"Session de paiement créée - Transaction: {transaction.id}, Session: {checkout_session.id}")
            
            return {
                'success': True,
                'checkout_url': checkout_session.url,
                'session_id': checkout_session.id,
                'transaction_id': transaction.id,
                'package': package,
                'expires_at': checkout_session.expires_at
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Erreur Stripe lors de la création de session: {str(e)}")
            if 'transaction' in locals():
                transaction.status = TransactionStatus.FAILED
                transaction.failure_reason = f"Stripe error: {str(e)}"
                db.session.commit()
            
            return {
                'success': False,
                'error': f"Erreur de paiement: {str(e)}"
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la création de session de paiement: {str(e)}")
            db.session.rollback()
            
            return {
                'success': False,
                'error': f"Erreur interne: {str(e)}"
            }
    
    def handle_successful_payment(self, stripe_session_id):
        """
        Traite un paiement réussi (appelé par webhook Stripe)
        
        Args:
            stripe_session_id (str): ID de la session Stripe
            
        Returns:
            Transaction: L'objet transaction mis à jour
        """
        try:
            # Récupérer les informations de la session Stripe
            session = self.stripe.checkout.Session.retrieve(stripe_session_id)
            
            # Récupérer la transaction en base
            transaction = Transaction.query.filter_by(
                payment_gateway_id=stripe_session_id
            ).first()
            
            if not transaction:
                logger.error(f"Transaction non trouvée pour session Stripe {stripe_session_id}")
                raise ValueError(f"Transaction non trouvée pour session {stripe_session_id}")
            
            # Vérifier si déjà traitée (webhook en double)
            if transaction.status == TransactionStatus.COMPLETED:
                logger.info(f"Transaction {transaction.id} déjà traitée")
                return transaction
            
            # Vérifier le statut du paiement
            if session.payment_status != 'paid':
                logger.warning(f"Paiement non confirmé pour session {stripe_session_id}: {session.payment_status}")
                transaction.status = TransactionStatus.FAILED
                transaction.failure_reason = f"Payment status: {session.payment_status}"
                db.session.commit()
                return transaction
            
            # Récupérer l'utilisateur
            user = User.query.get(transaction.user_id)
            if not user:
                raise ValueError(f"Utilisateur {transaction.user_id} non trouvé")
            
            # AJOUTER LES CRÉDITS (transaction critique)
            old_balance = user.credits_balance
            user.credits_balance += transaction.credits_amount
            
            # Marquer la transaction comme complétée
            transaction.status = TransactionStatus.COMPLETED
            transaction.completed_at = datetime.utcnow()
            
            db.session.commit()
            
            logger.info(f"Paiement traité avec succès - Transaction: {transaction.id}, "
                       f"User: {user.id}, Crédits ajoutés: {transaction.credits_amount}, "
                       f"Nouveau solde: {user.credits_balance}")
            
            # Notification utilisateur (asynchrone)
            try:
                from ..tasks.notification_tasks import send_notification
                send_notification.delay(
                    user_id=user.id,
                    notification_type='credits_added',
                    title="Crédits ajoutés",
                    message=f"💰 {transaction.credits_amount} crédits ont été ajoutés à votre compte ! "
                           f"Nouveau solde: {user.credits_balance} crédits.",
                    related_resource_type="transaction",
                    related_resource_id=str(transaction.id),
                    priority="normal"
                )
            except Exception as notification_error:
                logger.warning(f"Erreur lors de l'envoi de notification: {notification_error}")
            
            return transaction
            
        except Exception as e:
            logger.error(f"Erreur lors du traitement du paiement réussi: {str(e)}")
            db.session.rollback()
            raise
    
    def handle_failed_payment(self, stripe_session_id, reason=None):
        """
        Traite un paiement échoué
        
        Args:
            stripe_session_id (str): ID de la session Stripe
            reason (str): Raison de l'échec
        """
        try:
            transaction = Transaction.query.filter_by(
                payment_gateway_id=stripe_session_id
            ).first()
            
            if transaction and transaction.status == TransactionStatus.PENDING:
                transaction.status = TransactionStatus.FAILED
                transaction.failure_reason = reason or "Payment failed"
                transaction.cancelled_at = datetime.utcnow()
                
                db.session.commit()
                
                logger.info(f"Paiement marqué comme échoué - Transaction: {transaction.id}")
                
                # Notification utilisateur
                try:
                    from ..tasks.notification_tasks import send_notification
                    send_notification.delay(
                        user_id=transaction.user_id,
                        notification_type='payment_failed',
                        title="Paiement échoué",
                        message="Votre paiement n'a pas pu être traité. Veuillez réessayer.",
                        priority="high"
                    )
                except Exception as notification_error:
                    logger.warning(f"Erreur lors de l'envoi de notification d'échec: {notification_error}")
                    
        except Exception as e:
            logger.error(f"Erreur lors du traitement du paiement échoué: {str(e)}")
            db.session.rollback()
    
    def verify_webhook_signature(self, payload, signature):
        """
        Vérifie la signature d'un webhook Stripe
        
        Args:
            payload (bytes): Corps de la requête webhook
            signature (str): Signature Stripe
            
        Returns:
            dict: Événement Stripe vérifié
        """
        webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
        
        if not webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET non configuré")
        
        try:
            event = self.stripe.Webhook.construct_event(
                payload, signature, webhook_secret
            )
            return event
        except ValueError:
            logger.error("Payload webhook invalide")
            raise
        except self.stripe.error.SignatureVerificationError:
            logger.error("Signature webhook invalide")
            raise
    
    def get_transaction_status(self, transaction_id):
        """
        Récupère le statut d'une transaction
        
        Args:
            transaction_id (int): ID de la transaction
            
        Returns:
            dict: Informations de statut
        """
        try:
            transaction = Transaction.query.get(transaction_id)
            if not transaction:
                return {'error': 'Transaction non trouvée'}
            
            result = {
                'transaction_id': transaction.id,
                'status': transaction.status.value,
                'package_name': transaction.package_name,
                'credits_amount': transaction.credits_amount,
                'amount_euros': transaction.amount_cents / 100.0 if transaction.amount_cents else None,
                'created_at': transaction.created_at.isoformat(),
                'completed_at': transaction.completed_at.isoformat() if transaction.completed_at else None
            }
            
            if transaction.status == TransactionStatus.FAILED and transaction.failure_reason:
                result['failure_reason'] = transaction.failure_reason
            
            return result
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du statut de transaction: {str(e)}")
            return {'error': 'Erreur interne'}
    
    def get_user_transactions(self, user_id, limit=10):
        """
        Récupère l'historique des transactions d'un utilisateur
        
        Args:
            user_id (int): ID de l'utilisateur
            limit (int): Nombre max de transactions à retourner
            
        Returns:
            list: Liste des transactions
        """
        try:
            transactions = Transaction.query.filter_by(
                user_id=user_id
            ).order_by(
                Transaction.created_at.desc()
            ).limit(limit).all()
            
            return [transaction.to_dict() for transaction in transactions]
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des transactions utilisateur: {str(e)}")
            return []

# Instance globale du service
payment_service = PaymentService(stripe_api_key=os.environ.get('STRIPE_SECRET_KEY'))