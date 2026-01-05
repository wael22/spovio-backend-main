# src/tasks/payment_tasks.py

"""
Tâches Celery pour le traitement des paiements
Gère les transactions Stripe, les webhooks et l'attribution de crédits
"""

import logging
from datetime import datetime, timedelta

from ..celery_app import celery_app
from ..models.database import db
from ..models.user import User, Transaction, TransactionStatus, NotificationType
from ..tasks.notification_tasks import send_notification

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_successful_payment(self, payment_intent_id, transaction_id=None, idempotency_key=None):
    """
    Traite un paiement réussi depuis un webhook Stripe
    1. Vérifie la transaction
    2. Ajoute les crédits au compte utilisateur
    3. Met à jour le statut de la transaction
    4. Envoie une notification
    """
    try:
        logger.info(f"Traitement paiement réussi - PaymentIntent: {payment_intent_id}")
        
        # Chercher la transaction par payment_intent_id
        transaction = Transaction.query.filter_by(payment_intent_id=payment_intent_id).first()
        
        if not transaction:
            # Si pas de transaction_id fourni, on ne peut pas continuer
            if not transaction_id:
                logger.error(f"Transaction non trouvée pour PaymentIntent: {payment_intent_id}")
                return {'status': 'error', 'message': 'Transaction not found'}
            
            transaction = Transaction.query.get(transaction_id)
            if not transaction:
                logger.error(f"Transaction {transaction_id} non trouvée")
                return {'status': 'error', 'message': 'Transaction not found'}
        
        # Vérifier que la transaction n'est pas déjà complétée
        if transaction.status == TransactionStatus.COMPLETED:
            logger.warning(f"Transaction {transaction.id} déjà complétée")
            return {'status': 'already_completed', 'transaction_id': transaction.id}
        
        # Vérifier l'idempotence si fournie
        if idempotency_key and transaction.idempotency_key != idempotency_key:
            logger.warning(f"Clé d'idempotence différente pour transaction {transaction.id}")
            return {'status': 'error', 'message': 'Idempotency key mismatch'}
        
        # Récupérer l'utilisateur
        user = transaction.user
        if not user:
            logger.error(f"Utilisateur non trouvé pour transaction {transaction.id}")
            return {'status': 'error', 'message': 'User not found'}
        
        # Ajouter les crédits au compte utilisateur
        old_balance = user.credits_balance
        user.credits_balance += transaction.credits_amount
        new_balance = user.credits_balance
        
        # Mettre à jour la transaction
        transaction.status = TransactionStatus.COMPLETED
        transaction.completed_at = datetime.utcnow()
        
        # Sauvegarder les changements
        db.session.commit()
        
        logger.info(f"Crédits ajoutés - Utilisateur: {user.id}, Anciens: {old_balance}, Nouveaux: {new_balance}")
        
        # Envoyer une notification de succès
        send_notification.delay(
            user_id=user.id,
            notification_type=NotificationType.PAYMENT_SUCCESS.value,
            title="Paiement réussi",
            message=f"Votre achat de {transaction.credits_amount} crédits a été confirmé. Nouveau solde: {new_balance} crédits.",
            priority='normal',
            related_resource_type="transaction",
            related_resource_id=str(transaction.id)
        )
        
        # Notification supplémentaire pour les crédits
        send_notification.delay(
            user_id=user.id,
            notification_type=NotificationType.CREDITS_ADDED.value,
            title="Crédits ajoutés",
            message=f"{transaction.credits_amount} crédits ont été ajoutés à votre compte. Solde total: {new_balance} crédits.",
            priority='normal',
            related_resource_type="transaction",
            related_resource_id=str(transaction.id)
        )
        
        return {
            'status': 'completed',
            'transaction_id': transaction.id,
            'user_id': user.id,
            'credits_added': transaction.credits_amount,
            'new_balance': new_balance
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement du paiement {payment_intent_id}: {str(e)}")
        
        # Retry si possible
        if self.request.retries < self.max_retries:
            logger.info(f"Retry {self.request.retries + 1}/{self.max_retries}")
            raise self.retry(exc=e)
        
        # En cas d'échec définitif, marquer la transaction comme échouée
        try:
            if 'transaction' in locals() and transaction:
                transaction.status = TransactionStatus.FAILED
                transaction.failure_reason = str(e)
                db.session.commit()
        except Exception as cleanup_error:
            logger.error(f"Erreur lors du nettoyage: {cleanup_error}")
        
        return {'status': 'failed', 'error': str(e)}

@celery_app.task(bind=True, max_retries=2)
def process_failed_payment(self, payment_intent_id, failure_reason, transaction_id=None):
    """
    Traite un paiement échoué depuis un webhook Stripe
    """
    try:
        logger.info(f"Traitement paiement échoué - PaymentIntent: {payment_intent_id}")
        
        # Chercher la transaction
        transaction = Transaction.query.filter_by(payment_intent_id=payment_intent_id).first()
        
        if not transaction and transaction_id:
            transaction = Transaction.query.get(transaction_id)
        
        if not transaction:
            logger.error(f"Transaction non trouvée pour PaymentIntent: {payment_intent_id}")
            return {'status': 'error', 'message': 'Transaction not found'}
        
        # Mettre à jour la transaction
        transaction.status = TransactionStatus.FAILED
        transaction.failure_reason = failure_reason
        
        db.session.commit()
        
        # Envoyer une notification à l'utilisateur
        send_notification.delay(
            user_id=transaction.user_id,
            notification_type=NotificationType.PAYMENT_FAILED.value,
            title="Paiement échoué",
            message=f"Le paiement pour votre achat de {transaction.credits_amount} crédits a échoué. Veuillez réessayer.",
            priority='high',
            related_resource_type="transaction",
            related_resource_id=str(transaction.id),
            action_url="/credits/buy",
            action_label="Réessayer"
        )
        
        return {
            'status': 'processed',
            'transaction_id': transaction.id,
            'failure_reason': failure_reason
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement de l'échec: {str(e)}")
        return {'status': 'error', 'error': str(e)}

@celery_app.task(bind=True, max_retries=2)
def process_refund(self, payment_intent_id, refund_amount_cents, refund_id=None):
    """
    Traite un remboursement depuis Stripe
    """
    try:
        logger.info(f"Traitement remboursement - PaymentIntent: {payment_intent_id}")
        
        # Chercher la transaction originale
        original_transaction = Transaction.query.filter_by(payment_intent_id=payment_intent_id).first()
        
        if not original_transaction:
            logger.error(f"Transaction originale non trouvée: {payment_intent_id}")
            return {'status': 'error', 'message': 'Original transaction not found'}
        
        user = original_transaction.user
        if not user:
            return {'status': 'error', 'message': 'User not found'}
        
        # Calculer les crédits à retirer (proportionnellement)
        refund_ratio = refund_amount_cents / original_transaction.amount_cents
        credits_to_remove = int(original_transaction.credits_amount * refund_ratio)
        
        # Vérifier que l'utilisateur a assez de crédits
        if user.credits_balance < credits_to_remove:
            logger.warning(f"Utilisateur {user.id} n'a pas assez de crédits pour le remboursement")
            # On retire quand même ce qu'on peut
            credits_to_remove = user.credits_balance
        
        # Retirer les crédits
        old_balance = user.credits_balance
        user.credits_balance = max(0, user.credits_balance - credits_to_remove)
        new_balance = user.credits_balance
        
        # Créer une transaction de remboursement
        refund_transaction = Transaction(
            user_id=user.id,
            transaction_type='refund',
            credits_amount=-credits_to_remove,  # Négatif pour un remboursement
            amount_cents=refund_amount_cents,
            currency=original_transaction.currency,
            status=TransactionStatus.COMPLETED,
            payment_gateway=original_transaction.payment_gateway,
            payment_gateway_id=refund_id,
            payment_intent_id=payment_intent_id,
            description=f"Remboursement de la transaction {original_transaction.id}",
            completed_at=datetime.utcnow()
        )
        
        db.session.add(refund_transaction)
        db.session.commit()
        
        # Notifier l'utilisateur
        send_notification.delay(
            user_id=user.id,
            notification_type=NotificationType.CREDITS_ADDED.value,  # Temporary, créer REFUND_PROCESSED
            title="Remboursement traité",
            message=f"Un remboursement de {credits_to_remove} crédits a été traité. Nouveau solde: {new_balance} crédits.",
            priority='normal',
            related_resource_type="transaction",
            related_resource_id=str(refund_transaction.id)
        )
        
        return {
            'status': 'processed',
            'original_transaction_id': original_transaction.id,
            'refund_transaction_id': refund_transaction.id,
            'credits_removed': credits_to_remove,
            'new_balance': new_balance
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement du remboursement: {str(e)}")
        return {'status': 'error', 'error': str(e)}

@celery_app.task
def deduct_credits_for_recording(user_id, credits_amount, recording_id, description=None):
    """
    Déduit des crédits pour un enregistrement
    """
    try:
        logger.info(f"Déduction de {credits_amount} crédits pour utilisateur {user_id}")
        
        user = User.query.get(user_id)
        if not user:
            return {'status': 'error', 'message': 'User not found'}
        
        # Vérifier que l'utilisateur a assez de crédits
        if user.credits_balance < credits_amount:
            logger.warning(f"Utilisateur {user_id} n'a pas assez de crédits ({user.credits_balance} < {credits_amount})")
            return {
                'status': 'insufficient_credits',
                'current_balance': user.credits_balance,
                'required': credits_amount
            }
        
        # Déduire les crédits
        old_balance = user.credits_balance
        user.credits_balance -= credits_amount
        new_balance = user.credits_balance
        
        # Créer une transaction de débit
        transaction = Transaction(
            user_id=user.id,
            transaction_type='credit_usage',
            credits_amount=-credits_amount,  # Négatif pour une déduction
            status=TransactionStatus.COMPLETED,
            description=description or f"Déduction pour enregistrement {recording_id}",
            completed_at=datetime.utcnow()
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        logger.info(f"Crédits déduits - Utilisateur: {user_id}, Anciens: {old_balance}, Nouveaux: {new_balance}")
        
        return {
            'status': 'success',
            'transaction_id': transaction.id,
            'credits_deducted': credits_amount,
            'new_balance': new_balance
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de la déduction de crédits: {str(e)}")
        return {'status': 'error', 'error': str(e)}

@celery_app.task
def check_pending_transactions():
    """
    Vérifie et nettoie les transactions en attente depuis trop longtemps
    """
    logger.info("Vérification des transactions en attente")
    
    try:
        # Transactions en attente depuis plus de 24h
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        
        old_pending_transactions = Transaction.query.filter(
            Transaction.status == TransactionStatus.PENDING,
            Transaction.created_at < cutoff_time
        ).all()
        
        if not old_pending_transactions:
            return {'expired_transactions': 0}
        
        expired_count = 0
        for transaction in old_pending_transactions:
            try:
                # Marquer comme expirée/annulée
                transaction.status = TransactionStatus.CANCELLED
                transaction.cancelled_at = datetime.utcnow()
                transaction.failure_reason = "Transaction expired (>24h pending)"
                
                # Notifier l'utilisateur si nécessaire
                if transaction.user:
                    send_notification.delay(
                        user_id=transaction.user.id,
                        notification_type=NotificationType.PAYMENT_FAILED.value,
                        title="Transaction expirée",
                        message="Votre transaction de paiement a expiré. Veuillez réessayer si nécessaire.",
                        priority='normal'
                    )
                
                expired_count += 1
                
            except Exception as e:
                logger.error(f"Erreur lors de l'expiration de la transaction {transaction.id}: {e}")
        
        if expired_count > 0:
            db.session.commit()
            logger.info(f"Expiré {expired_count} transactions en attente")
        
        return {'expired_transactions': expired_count}
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des transactions: {e}")
        return {'error': str(e)}