# src/tasks/maintenance_tasks.py

"""
Tâches de maintenance Celery pour PadelVar
Gère le nettoyage des données, sessions zombies, monitoring système
"""

import logging
import psutil
import time
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..celery_app import celery_app
from ..models.database import db
from ..models.user import (
    User, RecordingSession, Notification, IdempotencyKey, 
    Transaction, TransactionStatus, UserStatus
)
from ..middleware.idempotence import IdempotenceMiddleware
from .notification_tasks import send_notification

logger = logging.getLogger(__name__)

@celery_app.task
def cleanup_zombie_sessions():
    """
    TÂCHE CRITIQUE: Nettoie les sessions d'enregistrement zombies
    
    Une session est considérée comme zombie si:
    - Elle est marquée comme 'active' mais le processus FFmpeg n'existe plus
    - Elle dépasse la durée maximale autorisée
    - Elle n'a pas d'activité récente
    """
    try:
        logger.info("Démarrage du nettoyage des sessions zombies")
        
        zombie_count = 0
        cleaned_courts = 0
        
        # Récupérer toutes les sessions actives
        active_sessions = RecordingSession.query.filter_by(status='active').all()
        
        if not active_sessions:
            logger.info("Aucune session active trouvée")
            return {'zombie_sessions_cleaned': 0, 'courts_freed': 0}
        
        logger.info(f"Vérification de {len(active_sessions)} sessions actives")
        
        for session in active_sessions:
            is_zombie = False
            zombie_reason = ""
            
            try:
                # 1. Vérifier si la session a expiré
                if session.is_expired():
                    is_zombie = True
                    zombie_reason = "Session expirée"
                
                # 2. Vérifier les processus système si on a un PID FFmpeg
                elif hasattr(session, 'ffmpeg_pid') and session.ffmpeg_pid:
                    try:
                        # Vérifier si le processus existe encore
                        process = psutil.Process(session.ffmpeg_pid)
                        
                        # Vérifier si le processus est bien FFmpeg
                        if 'ffmpeg' not in process.name().lower():
                            is_zombie = True
                            zombie_reason = "Processus FFmpeg introuvable"
                        
                        # Vérifier si le processus est trop ancien (>3h)
                        elif time.time() - process.create_time() > 10800:  # 3 heures
                            is_zombie = True
                            zombie_reason = "Processus FFmpeg trop ancien"
                            
                    except psutil.NoSuchProcess:
                        is_zombie = True
                        zombie_reason = "Processus FFmpeg n'existe plus"
                
                # 3. Vérifier les sessions sans activité récente (>2h)
                elif session.start_time and (datetime.utcnow() - session.start_time).total_seconds() > 7200:
                    elapsed_minutes = session.get_elapsed_minutes()
                    if elapsed_minutes > session.max_duration:
                        is_zombie = True
                        zombie_reason = "Durée maximale dépassée"
                
                # Nettoyer la session zombie
                if is_zombie:
                    logger.warning(f"Session zombie détectée: {session.recording_id} - {zombie_reason}")
                    
                    # Marquer comme failed
                    session.status = 'failed'
                    session.stopped_by = 'system_cleanup'
                    session.end_time = datetime.utcnow()
                    
                    # Libérer le terrain
                    if session.court:
                        session.court.is_recording = False
                        session.court.recording_session_id = None
                        session.court.current_recording_id = None
                        cleaned_courts += 1
                    
                    # Terminer le processus FFmpeg s'il existe encore
                    if hasattr(session, 'ffmpeg_pid') and session.ffmpeg_pid:
                        try:
                            process = psutil.Process(session.ffmpeg_pid)
                            process.terminate()
                            logger.info(f"Processus FFmpeg {session.ffmpeg_pid} terminé")
                        except psutil.NoSuchProcess:
                            pass  # Déjà terminé
                        except Exception as e:
                            logger.warning(f"Impossible de terminer le processus {session.ffmpeg_pid}: {e}")
                    
                    # Notifier l'utilisateur
                    try:
                        send_notification.delay(
                            user_id=session.user_id,
                            notification_type='recording_stopped',
                            title="Enregistrement interrompu",
                            message=f"Votre enregistrement sur le terrain {session.court.name if session.court else 'N/A'} a été interrompu automatiquement. Raison: {zombie_reason}",
                            priority="high",
                            related_resource_type="recording_session",
                            related_resource_id=session.recording_id
                        )
                    except Exception as notification_error:
                        logger.warning(f"Erreur lors de l'envoi de notification: {notification_error}")
                    
                    zombie_count += 1
                    
            except Exception as session_error:
                logger.error(f"Erreur lors du traitement de la session {session.recording_id}: {session_error}")
        
        # Commit des changements
        if zombie_count > 0:
            db.session.commit()
            logger.info(f"Nettoyage terminé: {zombie_count} sessions zombies, {cleaned_courts} terrains libérés")
        else:
            logger.info("Aucune session zombie trouvée")
        
        return {
            'zombie_sessions_cleaned': zombie_count,
            'courts_freed': cleaned_courts,
            'total_sessions_checked': len(active_sessions)
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des sessions zombies: {str(e)}")
        db.session.rollback()
        return {'error': str(e)}

@celery_app.task
def cleanup_expired_idempotency_keys():
    """
    Nettoie les clés d'idempotence expirées
    """
    try:
        logger.info("Nettoyage des clés d'idempotence expirées")
        
        cleaned_count = IdempotenceMiddleware.cleanup_expired_keys()
        
        logger.info(f"Nettoyage idempotence terminé: {cleaned_count} clés supprimées")
        
        return {'expired_keys_cleaned': cleaned_count}
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des clés d'idempotence: {str(e)}")
        return {'error': str(e)}

@celery_app.task
def cleanup_old_notifications():
    """
    Nettoie les anciennes notifications
    """
    try:
        logger.info("Nettoyage des anciennes notifications")
        
        # Supprimer les notifications lues de plus de 30 jours
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        old_read_notifications = Notification.query.filter(
            Notification.is_read == True,
            Notification.created_at < thirty_days_ago
        ).delete()
        
        # Supprimer les notifications expirées
        expired_notifications = Notification.query.filter(
            Notification.expires_at < datetime.utcnow()
        ).delete()
        
        # Archiver les notifications non lues de plus de 7 jours
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        archived_count = Notification.query.filter(
            Notification.is_read == False,
            Notification.is_archived == False,
            Notification.created_at < seven_days_ago
        ).update({'is_archived': True})
        
        db.session.commit()
        
        total_cleaned = old_read_notifications + expired_notifications
        logger.info(f"Nettoyage notifications terminé: {total_cleaned} supprimées, {archived_count} archivées")
        
        return {
            'old_notifications_cleaned': total_cleaned,
            'notifications_archived': archived_count
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des notifications: {str(e)}")
        db.session.rollback()
        return {'error': str(e)}

@celery_app.task
def cleanup_old_transactions():
    """
    Nettoie les anciennes transactions failed/cancelled
    """
    try:
        logger.info("Nettoyage des anciennes transactions")
        
        # Supprimer les transactions failed/cancelled de plus de 90 jours
        ninety_days_ago = datetime.utcnow() - timedelta(days=90)
        
        old_failed_transactions = Transaction.query.filter(
            Transaction.status.in_([TransactionStatus.FAILED, TransactionStatus.CANCELLED]),
            Transaction.created_at < ninety_days_ago
        ).delete()
        
        db.session.commit()
        
        logger.info(f"Nettoyage transactions terminé: {old_failed_transactions} transactions supprimées")
        
        return {'old_transactions_cleaned': old_failed_transactions}
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des transactions: {str(e)}")
        db.session.rollback()
        return {'error': str(e)}

@celery_app.task
def generate_daily_health_report():
    """
    Génère un rapport de santé quotidien du système
    """
    try:
        logger.info("Génération du rapport de santé quotidien")
        
        # Statistiques des dernières 24h
        yesterday = datetime.utcnow() - timedelta(days=1)
        
        # Statistiques utilisateurs
        new_users = User.query.filter(User.created_at >= yesterday).count()
        active_users = User.query.filter(User.status == UserStatus.ACTIVE).count()
        
        # Statistiques enregistrements
        recent_sessions = RecordingSession.query.filter(RecordingSession.created_at >= yesterday).count()
        completed_sessions = RecordingSession.query.filter(
            RecordingSession.created_at >= yesterday,
            RecordingSession.status == 'completed'
        ).count()
        failed_sessions = RecordingSession.query.filter(
            RecordingSession.created_at >= yesterday,
            RecordingSession.status == 'failed'
        ).count()
        
        # Statistiques transactions
        recent_transactions = Transaction.query.filter(Transaction.created_at >= yesterday).count()
        completed_transactions = Transaction.query.filter(
            Transaction.created_at >= yesterday,
            Transaction.status == TransactionStatus.COMPLETED
        ).count()
        
        # Métriques système
        memory_usage = psutil.virtual_memory().percent
        disk_usage = psutil.disk_usage('/').percent
        
        # Compter les processus FFmpeg actifs
        ffmpeg_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'create_time']):
            try:
                if 'ffmpeg' in proc.info['name'].lower():
                    ffmpeg_processes.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        report = {
            'date': datetime.utcnow().isoformat(),
            'users': {
                'new_users_24h': new_users,
                'total_active_users': active_users
            },
            'recordings': {
                'sessions_24h': recent_sessions,
                'completed_24h': completed_sessions,
                'failed_24h': failed_sessions,
                'success_rate': round((completed_sessions / recent_sessions * 100) if recent_sessions > 0 else 0, 2)
            },
            'payments': {
                'transactions_24h': recent_transactions,
                'completed_24h': completed_transactions,
                'success_rate': round((completed_transactions / recent_transactions * 100) if recent_transactions > 0 else 0, 2)
            },
            'system': {
                'memory_usage_percent': memory_usage,
                'disk_usage_percent': disk_usage,
                'active_ffmpeg_processes': len(ffmpeg_processes)
            }
        }
        
        # Log du rapport
        logger.info(f"Rapport de santé généré: {report}")
        
        # Alertes si nécessaire
        alerts = []
        
        if memory_usage > 85:
            alerts.append(f"⚠️ Utilisation mémoire critique: {memory_usage}%")
        
        if disk_usage > 90:
            alerts.append(f"⚠️ Espace disque critique: {disk_usage}%")
        
        if len(ffmpeg_processes) > 10:
            alerts.append(f"⚠️ Trop de processus FFmpeg actifs: {len(ffmpeg_processes)}")
        
        if failed_sessions > 0 and recent_sessions > 0:
            failure_rate = (failed_sessions / recent_sessions) * 100
            if failure_rate > 20:
                alerts.append(f"⚠️ Taux d'échec élevé des enregistrements: {failure_rate:.1f}%")
        
        # Envoyer des alertes aux admins si nécessaire
        if alerts:
            admin_users = User.query.filter_by(role='super_admin').all()
            for admin in admin_users:
                try:
                    send_notification.delay(
                        user_id=admin.id,
                        notification_type='system_alert',
                        title="Alertes système",
                        message=f"Alertes détectées:\n" + "\n".join(alerts),
                        priority="urgent"
                    )
                except Exception as notification_error:
                    logger.warning(f"Erreur lors de l'envoi d'alerte à l'admin: {notification_error}")
        
        return {
            'report': report,
            'alerts': alerts,
            'alerts_sent': len(alerts) > 0
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération du rapport de santé: {str(e)}")
        return {'error': str(e)}

@celery_app.task
def force_cleanup_system():
    """
    Nettoyage forcé du système en cas de problème critique
    """
    try:
        logger.warning("Démarrage du nettoyage forcé du système")
        
        results = {}
        
        # 1. Nettoyer toutes les sessions zombies
        results['zombie_cleanup'] = cleanup_zombie_sessions.apply().result
        
        # 2. Terminer tous les processus FFmpeg anciens
        terminated_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'create_time']):
            try:
                if 'ffmpeg' in proc.info['name'].lower():
                    # Terminer si plus de 30 minutes
                    if time.time() - proc.info['create_time'] > 1800:
                        psutil.Process(proc.info['pid']).terminate()
                        terminated_processes.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        results['terminated_ffmpeg'] = terminated_processes
        
        # 3. Libérer tous les terrains bloqués
        from ..models.user import Court
        blocked_courts = Court.query.filter_by(is_recording=True).all()
        freed_courts = []
        
        for court in blocked_courts:
            # Vérifier s'il y a vraiment une session active
            active_session = RecordingSession.query.filter_by(
                court_id=court.id,
                status='active'
            ).first()
            
            if not active_session:
                court.is_recording = False
                court.recording_session_id = None
                court.current_recording_id = None
                freed_courts.append(court.id)
        
        if freed_courts:
            db.session.commit()
        
        results['freed_courts'] = freed_courts
        
        # 4. Nettoyage mémoire Python
        import gc
        gc.collect()
        
        logger.warning(f"Nettoyage forcé terminé: {results}")
        
        return results
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage forcé: {str(e)}")
        db.session.rollback()
        return {'error': str(e)}

@celery_app.task
def system_monitoring_check():
    """
    Tâche de monitoring continu du système
    Utilise le module monitoring_simple pour effectuer les vérifications
    """
    try:
        from ..monitoring_simple import check_system, memory_check_alert, ffmpeg_process_check
        
        logger.info("Démarrage du monitoring système automatique")
        
        # Vérifications système complètes
        system_status = check_system()
        memory_status = memory_check_alert()
        ffmpeg_status = ffmpeg_process_check()
        
        # Préparer le rapport de monitoring
        monitoring_report = {
            'timestamp': datetime.utcnow().isoformat(),
            'system_check': system_status,
            'memory_ok': memory_status,
            'ffmpeg_ok': ffmpeg_status,
            'overall_health': memory_status and ffmpeg_status and not system_status.get('error')
        }
        
        # Alertes critiques aux admins si nécessaire
        if not monitoring_report['overall_health']:
            admin_users = User.query.filter_by(role='super_admin').all()
            
            alert_messages = []
            if not memory_status:
                memory_percent = system_status.get('memory_percent', 0)
                alert_messages.append(f"Mémoire critique: {memory_percent}%")
            
            if not ffmpeg_status:
                alert_messages.append("Processus FFmpeg problématiques détectés")
            
            if system_status.get('error'):
                alert_messages.append(f"Erreur système: {system_status['error']}")
            
            if alert_messages:
                for admin in admin_users:
                    try:
                        send_notification.delay(
                            user_id=admin.id,
                            notification_type='system_alert',
                            title="Alerte Monitoring Système",
                            message=f"Problèmes détectés:\n" + "\n".join(alert_messages),
                            priority="urgent"
                        )
                    except Exception as notification_error:
                        logger.warning(f"Erreur lors de l'envoi d'alerte monitoring: {notification_error}")
        
        logger.info(f"Monitoring système terminé: {monitoring_report}")
        return monitoring_report
        
    except Exception as e:
        logger.error(f"Erreur lors du monitoring système: {str(e)}")
        return {'error': str(e), 'timestamp': datetime.utcnow().isoformat()}

@celery_app.task
def cleanup_temp_files():
    """
    Nettoie les fichiers temporaires anciens
    """
    logger.info("Nettoyage des fichiers temporaires")
    
    try:
        import os
        temp_dir = "/tmp"
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(hours=24)  # Fichiers de plus de 24h
        
        cleaned_files = 0
        total_size = 0
        
        if os.path.exists(temp_dir):
            for filename in os.listdir(temp_dir):
                if filename.startswith('recording_') and filename.endswith('.mp4'):
                    file_path = os.path.join(temp_dir, filename)
                    try:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        if mod_time < cutoff_time:
                            file_size = os.path.getsize(file_path)
                            os.remove(file_path)
                            cleaned_files += 1
                            total_size += file_size
                            logger.info(f"Fichier temporaire supprimé: {filename}")
                    except Exception as e:
                        logger.warning(f"Impossible de supprimer {filename}: {e}")
        
        logger.info(f"Nettoyage terminé: {cleaned_files} fichiers supprimés ({total_size / 1024 / 1024:.1f} MB)")
        
        return {
            'files_deleted': cleaned_files,
            'size_freed_mb': round(total_size / 1024 / 1024, 1)
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des fichiers temporaires: {e}")
        return {'error': str(e)}