# src/celery_app.py

"""
Configuration Celery pour PadelVar
Gère les tâches asynchrones : traitement vidéo, upload CDN, notifications, etc.
"""

import os
from celery import Celery
from celery.schedules import crontab
from .config import Config

def create_celery_app(app=None):
    """
    Crée et configure l'instance Celery
    """
    celery = Celery(
        app.import_name if app else 'padelvar',
        broker=Config.CELERY_BROKER_URL,
        backend=Config.CELERY_RESULT_BACKEND,
        include=[
            'src.tasks.video_processing',
            'src.tasks.notification_tasks',
            'src.tasks.maintenance_tasks',
            'src.tasks.payment_tasks'
        ]
    )
    
    # Configuration Celery
    celery.conf.update(
        # Sérialisation
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='Europe/Paris',
        enable_utc=True,
        
        # Gestion des tâches
        task_always_eager=Config.TESTING,  # Exécution synchrone en mode test
        task_eager_propagates=Config.TESTING,
        task_routes={
            'src.tasks.video_processing.*': {'queue': 'video_processing'},
            'src.tasks.notification_tasks.*': {'queue': 'notifications'},
            'src.tasks.maintenance_tasks.*': {'queue': 'maintenance'},
            'src.tasks.payment_tasks.*': {'queue': 'payments'}
        },
        
        # Retry et timeouts
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_soft_time_limit=300,  # 5 minutes
        task_time_limit=600,       # 10 minutes
        
        # Worker configuration
        worker_max_tasks_per_child=50,  # Redémarre le worker après 50 tâches
        worker_disable_rate_limits=False,
        
        # Monitoring
        task_send_sent_event=True,
        task_track_started=True,
        worker_send_task_events=True,
        
        # Beat scheduler (tâches périodiques)
        beat_schedule={
            # Nettoyage des sessions zombies toutes les 5 minutes
            'cleanup-zombie-sessions': {
                'task': 'src.tasks.maintenance_tasks.cleanup_zombie_sessions',
                'schedule': crontab(minute='*/5'),
                'options': {'queue': 'maintenance'}
            },
            
            # Nettoyage des clés d'idempotence expirées chaque heure
            'cleanup-expired-idempotency-keys': {
                'task': 'src.tasks.maintenance_tasks.cleanup_expired_idempotency_keys',
                'schedule': crontab(minute=0),
                'options': {'queue': 'maintenance'}
            },
            
            # Nettoyage des notifications archivées chaque jour à 2h
            'cleanup-old-notifications': {
                'task': 'src.tasks.maintenance_tasks.cleanup_old_notifications',
                'schedule': crontab(hour=2, minute=0),
                'options': {'queue': 'maintenance'}
            },
            
            # Vérification de l'état des uploads Bunny CDN
            'check-bunny-upload-status': {
                'task': 'src.tasks.video_processing.check_bunny_upload_status',
                'schedule': crontab(minute='*/10'),
                'options': {'queue': 'video_processing'}
            },
            
            # Rapport de santé système quotidien
            'daily-health-report': {
                'task': 'src.tasks.maintenance_tasks.generate_daily_health_report',
                'schedule': crontab(hour=8, minute=0),
                'options': {'queue': 'maintenance'}
            }
        }
    )
    
    # Intégration avec Flask
    if app:
        class ContextTask(celery.Task):
            """
            Make celery tasks work with Flask app context
            """
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)
                    
        celery.Task = ContextTask
    
    return celery

# Instance globale Celery
celery_app = None  # Désactivé en dev

# Fonction pour initialiser avec Flask app
def init_celery(app):
    """
    Initialise Celery avec l'application Flask
    """
    global celery_app
    celery_app = create_celery_app(app)
    return celery_app