# src/tasks/video_processing.py

"""
Tâches Celery pour le traitement vidéo asynchrone
Gère l'enregistrement, la conversion et l'upload vers Bunny CDN
"""

import os
import logging
import subprocess
import time
from datetime import datetime, timedelta
from celery import current_task
from sqlalchemy.exc import SQLAlchemyError

from ..celery_app import celery_app
from ..models.database import db
from ..models.user import User, RecordingSession, Notification, NotificationType
from ..models.recording import Recording
from ..services.ffmpeg_runner import FFmpegRunner
from ..services.bunny_storage_service import BunnyStorageService
from ..tasks.notification_tasks import send_notification

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_video_recording(self, session_id):
    """
    Traite une session d'enregistrement vidéo de manière asynchrone
    1. Lance l'enregistrement FFmpeg
    2. Surveille le processus
    3. Upload vers Bunny CDN
    4. Met à jour les statuts et notifie l'utilisateur
    """
    task_id = self.request.id
    logger.info(f"Démarrage tâche traitement vidéo - Session: {session_id}, Task: {task_id}")
    
    try:
        # Récupérer la session d'enregistrement
        session = RecordingSession.query.filter_by(recording_id=session_id).first()
        if not session:
            raise ValueError(f"Session d'enregistrement non trouvée: {session_id}")
        
        # Vérifier que la session est active
        if session.status != 'active':
            logger.warning(f"Session {session_id} n'est pas active (statut: {session.status})")
            return {'status': 'skipped', 'reason': 'session_not_active'}
        
        # Mise à jour du statut
        current_task.update_state(state='PROGRESS', meta={'step': 'initializing', 'progress': 0})
        
        # 1. Configuration FFmpeg
        court = session.court
        user = session.user
        
        # Générer le nom de fichier et les chemins
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{session_id}_{timestamp}.mp4"
        temp_path = os.path.join("/tmp", filename)
        
        # 2. Lancement de l'enregistrement FFmpeg
        current_task.update_state(state='PROGRESS', meta={'step': 'recording', 'progress': 10})
        
        ffmpeg = FFmpegRunner()
        process = ffmpeg.start_recording(
            camera_url=court.camera_url,
            output_path=temp_path,
            duration_minutes=session.planned_duration
        )
        
        logger.info(f"FFmpeg lancé avec PID: {process.pid} pour session {session_id}")
        
        # Notifier l'utilisateur du démarrage
        send_notification.delay(
            user_id=user.id,
            notification_type=NotificationType.RECORDING_STARTED.value,
            title="Enregistrement démarré",
            message=f"L'enregistrement de votre session sur le terrain {court.name} a commencé.",
            related_resource_type="recording_session",
            related_resource_id=session_id
        )
        
        # 3. Surveillance du processus d'enregistrement
        start_time = time.time()
        max_duration_seconds = session.max_duration * 60
        
        while process.poll() is None:  # Processus encore en cours
            elapsed = time.time() - start_time
            progress = min(90, int((elapsed / max_duration_seconds) * 80) + 10)
            
            current_task.update_state(
                state='PROGRESS',
                meta={
                    'step': 'recording',
                    'progress': progress,
                    'elapsed_seconds': int(elapsed),
                    'max_duration_seconds': max_duration_seconds
                }
            )
            
            # Vérifier si la session a été arrêtée
            db.session.refresh(session)
            if session.status != 'active':
                logger.info(f"Session {session_id} arrêtée, terminaison de FFmpeg")
                ffmpeg.stop_recording(process)
                break
            
            # Vérifier timeout
            if elapsed > max_duration_seconds:
                logger.warning(f"Timeout atteint pour session {session_id}, arrêt forcé")
                ffmpeg.stop_recording(process)
                session.status = 'completed'
                session.stopped_by = 'auto'
                session.end_time = datetime.utcnow()
                break
                
            time.sleep(5)  # Vérification toutes les 5 secondes
        
        # 4. Vérification du fichier de sortie
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise Exception(f"Fichier vidéo non créé ou vide: {temp_path}")
        
        file_size = os.path.getsize(temp_path)
        logger.info(f"Enregistrement terminé - Taille: {file_size} bytes")
        
        current_task.update_state(state='PROGRESS', meta={'step': 'uploading', 'progress': 90})
        
        # 5. Upload vers Bunny CDN
        bunny_service = BunnyStorageService()
        upload_result = bunny_service.upload_video(
            file_path=temp_path,
            filename=filename,
            on_progress=lambda percent: current_task.update_state(
                state='PROGRESS',
                meta={'step': 'uploading', 'progress': 90 + int(percent * 0.1)}
            )
        )
        
        if not upload_result.get('success'):
            raise Exception(f"Échec upload Bunny CDN: {upload_result.get('error')}")
        
        # 6. Création de l'enregistrement en base
        recording = Recording(
            id=session_id,
            user_id=user.id,
            court_id=court.id,
            club_id=session.club_id,
            title=session.title or f"Enregistrement {court.name}",
            file_url=upload_result['file_url'],
            started_at=session.start_time,
            ended_at=session.end_time,
            file_size=file_size,
            status='completed',
            upload_status='completed',
            bunny_video_id=upload_result.get('video_id'),
            bunny_url=upload_result['file_url'],
            credits_cost=session.planned_duration  # 1 crédit par minute
        )
        
        db.session.add(recording)
        
        # 7. Mise à jour de la session
        session.status = 'completed'
        if not session.end_time:
            session.end_time = datetime.utcnow()
        
        # 8. Libération du terrain
        court.is_recording = False
        court.recording_session_id = None
        court.current_recording_id = None
        
        # 9. Notification de fin
        send_notification.delay(
            user_id=user.id,
            notification_type=NotificationType.VIDEO_READY.value,
            title="Vidéo prête",
            message=f"Votre enregistrement sur le terrain {court.name} est terminé et disponible.",
            related_resource_type="recording",
            related_resource_id=session_id,
            action_url=f"/videos/{recording.id}",
            action_label="Voir la vidéo"
        )
        
        db.session.commit()
        
        # 10. Nettoyage du fichier temporaire
        try:
            os.remove(temp_path)
            logger.info(f"Fichier temporaire supprimé: {temp_path}")
        except Exception as e:
            logger.warning(f"Impossible de supprimer le fichier temporaire: {e}")
        
        logger.info(f"Traitement vidéo terminé avec succès pour session {session_id}")
        return {
            'status': 'completed',
            'recording_id': recording.id,
            'file_url': recording.file_url,
            'file_size': file_size,
            'duration': session.get_elapsed_minutes()
        }
        
    except Exception as e:
        logger.error(f"Erreur lors du traitement vidéo pour session {session_id}: {str(e)}")
        
        # Nettoyage en cas d'erreur
        try:
            session = RecordingSession.query.filter_by(recording_id=session_id).first()
            if session and session.status == 'active':
                session.status = 'failed'
                session.end_time = datetime.utcnow()
                
                # Libérer le terrain
                if session.court:
                    session.court.is_recording = False
                    session.court.recording_session_id = None
                    session.court.current_recording_id = None
                
                # Notification d'erreur
                send_notification.delay(
                    user_id=session.user_id,
                    notification_type=NotificationType.RECORDING_STOPPED.value,
                    title="Enregistrement échoué",
                    message="Une erreur s'est produite lors de l'enregistrement. Nos équipes ont été notifiées.",
                    priority="high"
                )
                
                db.session.commit()
        except Exception as cleanup_error:
            logger.error(f"Erreur lors du nettoyage: {cleanup_error}")
        
        # Retry si possible
        if self.request.retries < self.max_retries:
            logger.info(f"Retry {self.request.retries + 1}/{self.max_retries} pour session {session_id}")
            raise self.retry(exc=e)
        
        return {'status': 'failed', 'error': str(e)}

@celery_app.task(bind=True, max_retries=2)
def stop_video_recording(self, session_id, stopped_by='user'):
    """
    Arrête un enregistrement vidéo en cours
    """
    logger.info(f"Demande d'arrêt enregistrement - Session: {session_id}, Par: {stopped_by}")
    
    try:
        session = RecordingSession.query.filter_by(recording_id=session_id).first()
        if not session:
            return {'status': 'error', 'message': 'Session non trouvée'}
        
        if session.status != 'active':
            return {'status': 'already_stopped', 'current_status': session.status}
        
        # Marquer la session comme arrêtée
        session.status = 'stopped'
        session.stopped_by = stopped_by
        session.end_time = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"Session {session_id} marquée comme arrêtée")
        return {'status': 'stopped', 'session_id': session_id}
        
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt de l'enregistrement {session_id}: {str(e)}")
        return {'status': 'error', 'error': str(e)}

@celery_app.task
def check_bunny_upload_status():
    """
    Tâche périodique pour vérifier le statut des uploads Bunny CDN en attente
    """
    logger.info("Vérification des uploads Bunny CDN en attente")
    
    try:
        # Rechercher les enregistrements avec upload en cours
        pending_uploads = Recording.query.filter_by(upload_status='uploading').all()
        
        if not pending_uploads:
            logger.info("Aucun upload en attente")
            return {'checked': 0, 'updated': 0}
        
        bunny_service = BunnyStorageService()
        updated_count = 0
        
        for recording in pending_uploads:
            try:
                # Vérifier le statut chez Bunny
                if recording.bunny_video_id:
                    status = bunny_service.get_video_status(recording.bunny_video_id)
                    
                    if status.get('status') == 'finished':
                        recording.upload_status = 'completed'
                        recording.file_url = status.get('url', recording.file_url)
                        updated_count += 1
                        
                        # Notifier l'utilisateur
                        send_notification.delay(
                            user_id=recording.user_id,
                            notification_type=NotificationType.VIDEO_READY.value,
                            title="Vidéo disponible",
                            message=f"Votre enregistrement '{recording.title}' est maintenant disponible.",
                            related_resource_type="recording",
                            related_resource_id=str(recording.id)
                        )
                        
                    elif status.get('status') == 'failed':
                        recording.upload_status = 'failed'
                        recording.error_message = status.get('error', 'Upload failed')
                        updated_count += 1
                        
            except Exception as e:
                logger.warning(f"Erreur lors de la vérification du recording {recording.id}: {e}")
        
        if updated_count > 0:
            db.session.commit()
            logger.info(f"Mis à jour {updated_count} enregistrements")
        
        return {'checked': len(pending_uploads), 'updated': updated_count}
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des uploads Bunny: {e}")
        return {'error': str(e)}