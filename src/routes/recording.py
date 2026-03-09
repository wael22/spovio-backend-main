"""
Routes pour la gestion avancée des enregistrements
Fonctionnalités : durée sélectionnable, arrêt automatique, gestion par club
"""

from flask import Blueprint, request, jsonify, session
from datetime import datetime, timedelta
import uuid
import logging
import json
import os

from ..models.database import db
from ..models.user import (
    User, Club, Court, Video, RecordingSession, 
    ClubActionHistory, UserRole
)
# from ..services.video_capture_service_ultimate import (
#     DirectVideoCaptureService
# )
from ..video_system.config import VideoConfig

# Instance globale du service
# video_capture_service = DirectVideoCaptureService()


logger = logging.getLogger(__name__)

recording_bp = Blueprint('recording', __name__, url_prefix='/api/recording')

def get_current_user():
    """Récupérer l'utilisateur actuel"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

def log_recording_action(session_obj, action_type, action_details, performed_by_id):
    """Log d'action pour les enregistrements avec gestion d'erreur améliorée"""
    try:
        # Convertir les détails en JSON si nécessaire
        if isinstance(action_details, dict):
            details_json = json.dumps(action_details)
        elif isinstance(action_details, str):
            details_json = action_details
        else:
            details_json = json.dumps({"raw_details": str(action_details)})
        
        action_history = ClubActionHistory(
            club_id=session_obj.club_id,
            user_id=session_obj.user_id,
            action_type=action_type,
            action_details=details_json,
            performed_by_id=performed_by_id,
            performed_at=datetime.utcnow()
        )
        db.session.add(action_history)
        # Ne pas faire de flush ici pour éviter les problèmes de transaction
        logger.info(f"Action d'enregistrement préparée: {action_type}")
    except Exception as e:
        logger.error(f"Erreur lors du logging: {e}")
        # Ne pas lever l'exception pour ne pas interrompre le flux principal

def cleanup_expired_sessions(club_id=None):
    """Nettoyer toutes les sessions expirées pour un club ou globalement"""
    try:
        if club_id:
            expired_sessions = RecordingSession.query.filter_by(
                club_id=club_id,
                status='active'
            ).all()
        else:
            expired_sessions = RecordingSession.query.filter_by(status='active').all()
        
        cleaned_count = 0
        for session in expired_sessions:
            if session.is_expired():
                logger.info(f"Nettoyage automatique de la session expirée: {session.recording_id}")
                _stop_recording_session(session, 'auto', session.user_id)
                cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Nettoyage terminé: {cleaned_count} sessions expirées fermées")
        
        return cleaned_count
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage automatique: {e}")
        return 0

# ====================================================================
# ROUTES DE DÉMARRAGE D'ENREGISTREMENT
# ====================================================================

@recording_bp.route('/start', methods=['POST'])
def start_recording_with_duration():
    """Démarrer un enregistrement avec durée sélectionnable"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.get_json()
        court_id = data.get('court_id')
        duration = data.get('duration', 90)  # défaut: 90 minutes
        title = data.get('title', '')
        description = data.get('description', '')
        
        if not court_id:
            return jsonify({'error': 'Court ID requis'}), 400
        
        # Vérifier que le terrain existe et n'est pas occupé
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 404
        
        # Nettoyer les sessions expirées pour ce club avant de vérifier la disponibilité
        cleanup_expired_sessions(court.club_id)
        
        # Note: La vérification de disponibilité du terrain est gérée par RecordingSession
        # L'ancien système utilisait court.is_recording qui n'existe plus
        
        # Vérifier que l'utilisateur a des crédits
        if user.credits_balance < 1:
            return jsonify({'error': 'Crédits insuffisants'}), 400
        
        # Vérifier que l'utilisateur n'a pas déjà un enregistrement en cours
        existing_session = RecordingSession.query.filter_by(
            user_id=user.id,
            status='active'
        ).first()
        
        if existing_session:
            return jsonify({
                'error': 'Vous avez déjà un enregistrement en cours',
                'existing_recording': existing_session.to_dict()
            }), 409
        
        # Convertir la durée en minutes et la valider
        if duration == 'MAX':
            planned_duration = 200  # 200 minutes max
        else:
            planned_duration = int(duration)
            if planned_duration not in [60, 90, 120, 200]:
                return jsonify({'error': 'Durée invalide. Utilisez 60, 90, 120 ou MAX (200)'}), 400
        
        # Générer un ID unique pour l'enregistrement
        recording_id = f"rec_{user.id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"
        
        # Récupérer le club pour le titre
        club = Club.query.get(court.club_id)
        
        # Générer le titre par défaut: "date/club/terrain"
        if not title:
            date_str = datetime.now().strftime("%d/%m/%Y")
            club_name = club.name if club else "Club"
            title = f"{date_str}/{club_name}/{court.name}"
        
        # Créer la session d'enregistrement
        recording_session = RecordingSession(
            recording_id=recording_id,
            user_id=user.id,
            court_id=court_id,
            club_id=court.club_id,
            planned_duration=planned_duration,
            title=title,
            description=description,
            status='active'
        )
        
        # Note: Le terrain est réservé via RecordingSession status='active'
        # L'ancien système utilisait court.is_recording qui n'existe plus
        
        #Débiter un crédit
        user.credits_balance -= 1
        
        # Ajouter tous les objets à la session
        db.session.add(recording_session)
        
        # Log de l'action (sera ajouté à la session mais pas encore commité)
        log_recording_action(
            recording_session,
            'start_recording',
            {
                'court_name': court.name,
                'duration_minutes': planned_duration,
                'credits_used': 1,
                'new_balance': user.credits_balance
            },
            user.id
        )
        
        # Faire le commit de toutes les modifications en une fois
        db.session.commit()
        
        logger.info(f"Enregistrement démarré: {recording_id} sur terrain {court_id}")
        
        # Préparer la réponse après le commit réussi
        response_data = {
            'message': 'Enregistrement démarré avec succès',
            'recording_session': recording_session.to_dict(),
            'court': court.to_dict(),
            'user_credits': user.credits_balance
        }
        
        return jsonify(response_data), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du démarrage d'enregistrement: {str(e)}")
        logger.error(f"Type d'erreur: {type(e).__name__}")
        logger.error(f"Traceback: ", exc_info=True)
        return jsonify({
            'error': f'Erreur lors du démarrage: {str(e)}',
            'error_type': type(e).__name__
        }), 500

# ====================================================================
# ROUTES D'ARRÊT D'ENREGISTREMENT
# ====================================================================

@recording_bp.route('/stop', methods=['POST'])
@recording_bp.route('/v3/stop/<recording_id>', methods=['POST'])  # Route v3 pour compatibilité
def stop_recording(recording_id=None):
    """Arrêter un enregistrement (par le joueur)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Si recording_id n'est pas dans l'URL, le chercher dans le JSON
        if not recording_id:
            data = request.get_json()
            recording_id = data.get('recording_id')
        
        if not recording_id:
            return jsonify({'error': 'Recording ID requis'}), 400
        
        # Récupérer la session d'enregistrement
        recording_session = RecordingSession.query.filter_by(
            recording_id=recording_id,
            user_id=user.id,
            status='active'
        ).first()
        
        if not recording_session:
            return jsonify({'error': 'Session d\'enregistrement non trouvée ou déjà terminée'}), 404
        
        # Arrêter l'enregistrement
        return _stop_recording_session(recording_session, 'player', user.id)
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'arrêt d'enregistrement: {e}")
        return jsonify({'error': 'Erreur lors de l\'arrêt'}), 500

@recording_bp.route('/force-stop/<recording_id>', methods=['POST'])
@recording_bp.route('/v3/force-stop/<recording_id>', methods=['POST'])  # Route v3
def force_stop_recording(recording_id):
    """Arrêter un enregistrement (par le club)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
    
    try:
        # Récupérer la session d'enregistrement
        recording_session = RecordingSession.query.filter_by(
            recording_id=recording_id,
            club_id=user.club_id,
            status='active'
        ).first()
        
        if not recording_session:
            return jsonify({'error': 'Session d\'enregistrement non trouvée'}), 404
        
        # Arrêter l'enregistrement
        return _stop_recording_session(recording_session, 'club', user.id)
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'arrêt forcé: {e}")
        return jsonify({'error': 'Erreur lors de l\'arrêt forcé'}), 500

def _stop_recording_session(recording_session, stopped_by, performed_by_id):
    """Fonction utilitaire pour arrêter une session d'enregistrement"""
    try:
        # Mettre à jour la session
        recording_session.status = 'stopped'
        recording_session.stopped_by = stopped_by
        
        # ✅ CORRECTION DURÉE: Si arrêté automatiquement (expiration), on force la durée prévue
        # car cela signifie souvent que le serveur a redémarré après l'heure de fin prévue.
        if stopped_by == 'auto' and recording_session.is_expired():
            # Calculer la fin théorique
            theoretical_end = recording_session.start_time + timedelta(minutes=recording_session.planned_duration)
            recording_session.end_time = theoretical_end
            logger.info(f"🔄 Correction durée (Auto-Expire): Fin ajustée à {theoretical_end} (Durée: {recording_session.planned_duration}m)")
        else:
            recording_session.end_time = datetime.utcnow()
        
        
        # 🔧 LIBÉRER LE TERRAIN
        court = Court.query.get(recording_session.court_id)
        if court:
            court.is_recording = False
            logger.info(f"🔓 Terrain {court.name} libéré (enregistrement {stopped_by})")
        
        # Créer la vidéo
        elapsed_minutes = recording_session.get_elapsed_minutes()
        
        # � LOGS DÉTAILLÉS DURÉE - Début analyse
        logger.info(f"🕐 ANALYSE DURÉE pour {recording_session.recording_id}:")
        logger.info(f"   📅 Start time: {recording_session.start_time}")
        logger.info(f"   📅 End time: {recording_session.end_time}")
        logger.info(f"   ⏱️ Durée calculée DB: {elapsed_minutes:.2f} minutes = {elapsed_minutes * 60:.0f} secondes")
        
        # Use elapsed time from database as duration
        final_duration = elapsed_minutes * 60
        
        # 📊 LOGS DÉTAILLÉS - Résultat final
        logger.info(f"🎯 DURÉE FINALE RETENUE:")
        logger.info(f"   💾 Stockage en DB: {final_duration:.0f} secondes = {final_duration/60:.2f} minutes")
        # Source: Calcul DB (temps start → end)

        # 🛑 NETTOYAGE SYSTÈME VIDÉO (V3)
        # 🛑 NETTOYAGE SYSTÈME VIDÉO (V3)
        try:
            from src.video_system.recording import video_recorder
            from src.video_system.session_manager import session_manager
            
            # 1. Arrêter le processus FFmpeg (ce qui libère le flag recording_active)
            logger.info(f"🛑 Arrêt du système vidéo pour {recording_session.recording_id}")
            # Note: recording_session.recording_id == session_id dans la V3
            video_recorder.stop_recording(recording_session.recording_id)
            
            # 2. Fermer la session (arrêt proxy, cleanup mémoire)
            session_manager.close_session(recording_session.recording_id)
            logger.info(f"✅ Session système fermée: {recording_session.recording_id}")
            
        except Exception as v3_err:
            logger.warning(f"⚠️ Erreur lors du nettoyage V3 (non critique): {v3_err}")
            # On continue, ce n'est pas bloquant pour la sauvegarde BDD
        
        video = Video(
            user_id=recording_session.user_id,
            court_id=recording_session.court_id,
            title=recording_session.title,
            description=recording_session.description,
            duration=final_duration,  # ✅ DURÉE RÉELLE du fichier vidéo
            file_url=f'/videos/rec_{recording_session.recording_id}.mp4',
            is_unlocked=True,
            processing_status='pending',  # 🆕 Statut initial avant upload
            local_file_path=str(VideoConfig.get_video_dir(recording_session.club_id) / f"{recording_session.recording_id}.mp4") if (VideoConfig.get_video_dir(recording_session.club_id) / f"{recording_session.recording_id}.mp4").exists() else (f"static/videos/{recording_session.recording_id}.mp4" if os.path.exists(f"static/videos/{recording_session.recording_id}.mp4") else None)
        )
        
        # 📦 Calculer la taille du fichier si disponible
        try:
            # Chemins possibles pour le fichier vidéo
            video_dir = VideoConfig.get_video_dir(recording_session.club_id)
            possible_paths = [
                str(video_dir / f"{recording_session.recording_id}.mp4"),
                f"static/videos/{recording_session.club_id}/{recording_session.recording_id}.mp4",
                f"static/videos/{recording_session.recording_id}.mp4"
            ]
            
            for video_path in possible_paths:
                if os.path.exists(video_path):
                    file_size = os.path.getsize(video_path)
                    # Check for Integer overflow (Postgres Integer is max 2147483647)
                    if file_size < 2147483647:
                        video.file_size = file_size
                    else:
                        logger.warning(f"⚠️ File size {file_size} exceeds Integer limit, setting to None")
                        video.file_size = None
                    
                    logger.info(f"📦 Taille fichier vidéo: {file_size / (1024*1024):.2f} MB")
                    break
        except Exception as e:
            logger.warning(f"⚠️ Impossible de calculer la taille du fichier: {e}")
        
        db.session.add(video)
        
        # Log de l'action
        log_recording_action(
            recording_session,
            'stop_recording',
            {
                'stopped_by': stopped_by,
                'duration_minutes': elapsed_minutes,
                'court_name': court.name if court else 'Inconnu'
            },
            performed_by_id
        )
        
        db.session.commit()
        
        db.session.commit()
        
        logger.info(f"Enregistrement arrêté: {recording_session.recording_id} par {stopped_by}")

        # 🔔 NOTIFICATION D'ARRÊT (si pas par le joueur)
        if stopped_by in ['auto', 'club']:
            try:
                from ..models.notification import Notification, NotificationType
                
                notif_title = "Enregistrement terminé"
                if stopped_by == 'auto':
                    notif_msg = "Votre session a expiré et l'enregistrement a été arrêté automatiquement."
                else:
                    notif_msg = "Le club a arrêté votre session d'enregistrement."
                
                # Créer la notification
                # Note: On utilise le constructeur direct car create_notification n'est peut-être pas une méthode de classe accessible ici
                notif = Notification(
                    user_id=recording_session.user_id,
                    notification_type=NotificationType.RECORDING_STOPPED,
                    title=notif_title,
                    message=notif_msg,
                    related_resource_type='video',
                    related_resource_id=str(video.id)
                )
                db.session.add(notif)
                db.session.commit()
                logger.info(f"✅ Notification d'arrêt envoyée à l'utilisateur {recording_session.user_id}")
            except Exception as notif_e:
                logger.error(f"⚠️ Erreur envoi notification arrêt: {notif_e}")

        # 🚀 UPLOAD BUNNY CDN AUTOMATIQUE
        try:
            # Déterminer le chemin local du fichier
            local_video_path = None
            video_dir = VideoConfig.get_video_dir(recording_session.club_id)
            possible_paths = [
                str(video_dir / f"{recording_session.recording_id}.mp4"),
                f"static/videos/{recording_session.club_id}/{recording_session.recording_id}.mp4",
                f"static/videos/{recording_session.recording_id}.mp4"
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    local_video_path = path
                    break
            
            if local_video_path:
                from src.services.bunny_storage_service import bunny_storage_service
                logger.info(f"🚀 Début upload vers Bunny CDN: {local_video_path}")
                
                # 🆕 Mettre à jour le statut avant l'upload
                video.processing_status = 'uploading'
                db.session.commit()
                
                upload_id = bunny_storage_service.queue_upload(
                    local_path=local_video_path,
                    title=video.title,
                    metadata={
                        'video_id': video.id,
                        'user_id': recording_session.user_id,
                        'court_id': recording_session.court_id,
                        'recording_id': recording_session.recording_id,
                        'duration': final_duration / 60
                    }
                )
                logger.info(f"✅ Upload Bunny programmé: {upload_id}")
                
                # ✨ NEW: Wait briefly for upload to complete and extract bunny_video_id
                import time
                time.sleep(3)  # Give queue time to process and create video
                
                upload_status = bunny_storage_service.get_upload_status(upload_id)
                if upload_status and upload_status.get('bunny_video_id'):
                    bunny_id = upload_status['bunny_video_id']
                    video.bunny_video_id = bunny_id
                    # ✅ CORRECTION: Mettre à jour file_url avec l'URL Bunny CDN complète
                    from src.config.bunny_config import BUNNY_CONFIG
                    cdn_hostname = BUNNY_CONFIG.get('cdn_hostname', 'vz-9b857324-07d.b-cdn.net')
                    video.file_url = f"https://{cdn_hostname}/{bunny_id}/playlist.m3u8"
                    # 🆕 Mettre à jour le statut selon le statut Bunny
                    video.processing_status = 'processing'
                    db.session.commit()
                    logger.info(f"✅ Bunny video ID saved: {video.bunny_video_id}")
                    logger.info(f"✅ Bunny URL updated: {video.file_url}")
                else:
                    logger.warning(f"⚠️ Upload status: {upload_status}")
            else:
                logger.warning(f"⚠️ Fichier vidéo introuvable pour upload: {recording_session.recording_id}")
                
        except Exception as upload_error:
            logger.error(f"❌ Erreur déclenchement upload Bunny: {upload_error}")
        
        return jsonify({
            'message': 'Enregistrement arrêté avec succès',
            'video': video.to_dict(),
            'session': recording_session.to_dict(),
            'stopped_by': stopped_by
        }), 200
        
    except Exception as e:
        db.session.rollback()
        raise e

# ====================================================================
# ROUTES DE CONSULTATION
# ====================================================================

@recording_bp.route('/my-active', methods=['GET'])
@recording_bp.route('/v3/my-active', methods=['GET'])  # Route v3
def get_my_active_recording():
    """Récupérer l'enregistrement actif de l'utilisateur"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        recording_session = RecordingSession.query.filter_by(
            user_id=user.id,
            status='active'
        ).first()
        
        if not recording_session:
            return jsonify({'active_recording': None}), 200
        
        # Vérifier si l'enregistrement a expiré
        if recording_session.is_expired():
            # Arrêter automatiquement l'enregistrement expiré
            _stop_recording_session(recording_session, 'auto', user.id)
            return jsonify({'active_recording': None, 'message': 'Enregistrement expiré et arrêté automatiquement'}), 200
        
        # Enrichir avec les données du terrain et club
        court = Court.query.get(recording_session.court_id)
        club = Club.query.get(recording_session.club_id)
        
        result = recording_session.to_dict()
        if court:
            result['court'] = court.to_dict()
        if club:
            result['club'] = club.to_dict()
        
        return jsonify({'active_recording': result}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'enregistrement actif: {e}")
        return jsonify({'error': 'Erreur lors de la récupération'}), 500

@recording_bp.route('/club/active', methods=['GET'])
@recording_bp.route('/v3/club/active', methods=['GET'])  # Route v3
def get_club_active_recordings():
    """Récupérer tous les enregistrements actifs d'un club"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
    
    try:
        # Récupérer toutes les sessions actives du club
        active_sessions = RecordingSession.query.filter_by(
            club_id=user.club_id,
            status='active'
        ).all()
        
        # Enrichir avec les données utilisateur et terrain
        recordings_data = []
        for session in active_sessions:
            session_data = session.to_dict()
            
            # Ajouter les infos utilisateur
            player = User.query.get(session.user_id)
            if player:
                session_data['player'] = {
                    'id': player.id,
                    'name': player.name,
                    'email': player.email
                }
            
            # Ajouter les infos terrain
            court = Court.query.get(session.court_id)
            if court:
                session_data['court'] = court.to_dict()
            
            recordings_data.append(session_data)
        
        return jsonify({
            'active_recordings': recordings_data,
            'count': len(recordings_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des enregistrements du club: {e}")
        return jsonify({'error': 'Erreur lors de la récupération'}), 500

@recording_bp.route('/v3/clubs/<int:club_id>/courts', methods=['GET'])
def get_available_courts(club_id):
    """Récupérer les terrains disponibles d'un club"""
    print(f"=== DEBUG TERRAINS DISPONIBLES ===")
    print(f"Club ID demandé: {club_id}")
    
    user = get_current_user()
    if not user:
        print("❌ Utilisateur non authentifié")
        return jsonify({'error': 'Non authentifié'}), 401
    
    print(f"👤 Utilisateur: {user.email} (ID: {user.id})")
    
    try:
        # Nettoyer automatiquement les enregistrements expirés pour ce club
        cleanup_expired_sessions(club_id)
        
        # Récupérer tous les terrains du club
        courts = Court.query.filter_by(club_id=club_id).all()
        print(f"🏟️ Terrains trouvés pour club {club_id}: {len(courts)}")
        
        courts_data = []
        for court in courts:
            # 🔍 DEBUG: Forcer un refresh depuis la BD
            db.session.refresh(court)
            print(f"🔍 DEBUG Court {court.id}: is_recording={court.is_recording}")
            
            court_data = court.to_dict()
            print(f"📍 Terrain '{court.name}' (ID: {court.id}) - Disponible: {court_data['available']}")
            courts_data.append(court_data)
        
        print(f"✅ Réponse API: {len(courts_data)} terrains retournés")
        print(f"📋 Terrains: {[c['name'] for c in courts_data]}")
        
        # Créer la réponse avec headers anti-cache
        response = jsonify({'courts': courts_data})
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response, 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des terrains: {e}")
        return jsonify({'error': 'Erreur lors de la récupération'}), 500

# ====================================================================
# TÂCHE DE NETTOYAGE AUTOMATIQUE
# ====================================================================

@recording_bp.route('/cleanup-expired', methods=['POST'])
@recording_bp.route('/v3/cleanup-expired', methods=['POST'])  # Route v3
def cleanup_expired_recordings():
    """Nettoyer les enregistrements expirés (tâche de maintenance)"""
    user = get_current_user()
    if not user or user.role != UserRole.SUPER_ADMIN:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        # Récupérer toutes les sessions actives expirées
        expired_sessions = RecordingSession.query.filter_by(status='active').all()
        expired_count = 0
        
        for session in expired_sessions:
            if session.is_expired():
                _stop_recording_session(session, 'auto', user.id)
                expired_count += 1
        
        logger.info(f"Nettoyage automatique: {expired_count} enregistrements expirés arrêtés")
        
        return jsonify({
            'message': f'{expired_count} enregistrements expirés ont été arrêtés',
            'expired_count': expired_count
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage: {e}")
        return jsonify({'error': 'Erreur lors du nettoyage'}), 500

# ====================================================================
# V3 RECORDING API - Uses recording_manager_v2 for actual video capture
# ====================================================================

@recording_bp.route('/v3/health', methods=['GET'])
def recording_v3_health():
    """Health check for recording system v3"""
    try:
        from src.services.recording_manager_v2 import get_recording_manager
        from src.services.video_proxy_manager_v2 import get_proxy_manager
        from src.recording_config.recording_config import config
        
        recording_manager = get_recording_manager()
        proxy_manager = get_proxy_manager()
        
        # Check FFmpeg
        ffmpeg_ok = config.validate_ffmpeg()
        
        # Check disk space
        disk_ok = config.has_sufficient_disk_space()
        disk_gb = config.get_available_disk_space() / (1024**3)
        
        # Get active recordings
        active_recordings = recording_manager.get_all_active()
        
        health_status = {
            'status': 'healthy' if (ffmpeg_ok and disk_ok) else 'degraded',
            'ffmpeg_available': ffmpeg_ok,
            'ffmpeg_path': config.FFMPEG_PATH,
            'disk_space_ok': disk_ok,
            'disk_space_gb': round(disk_gb, 2),
            'active_recordings_count': len(active_recordings),
            'max_concurrent': config.MAX_CONCURRENT_RECORDINGS,
            'proxy_count': len(proxy_manager.proxies)
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@recording_bp.route('/v3/test', methods=['GET'])
def recording_v3_test():
    """Test endpoint for v3 recording system"""
    return jsonify({
        'message': 'Recording V3 API is working',
        'version': '3.0',
        'endpoints': {
            'start': '/api/recording/v3/start',
            'stop': '/api/recording/v3/stop',
            'status': '/api/recording/v3/status/<recording_id>',
            'active': '/api/recording/v3/active',
            'health': '/api/recording/v3/health',
            'diagnostics': '/api/recording/v3/diagnostics/<recording_id>'
        }
    }), 200


@recording_bp.route('/v3/start', methods=['POST'])
def start_recording_v3():
    """🆕 ADAPTATEUR: Redirige vers le nouveau système vidéo stable"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # 🆕 Utiliser le NOUVEAU système vidéo stable
        from src.video_system.session_manager import session_manager
        from src.video_system.recording import video_recorder
        
        data = request.get_json()
        court_id = data.get('court_id')
        # Frontend envoie 'duration_minutes' (int) : 60, 90, 120, ou 200
        duration_minutes = data.get('duration_minutes')
        # ✅ NOUVEAU: Récupérer le titre et description personnalisés
        custom_title = data.get('title')
        custom_description = data.get('description')
        
        # Valider la durée
        if not duration_minutes or duration_minutes not in [60, 90, 120, 200]:
            return jsonify({'error': 'Durée invalide. Utilisez 60, 90, 120 ou 200 minutes'}), 400
        
        if not court_id:
            return jsonify({'error': 'court_id requis'}), 400
        
        # Get court
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 404
        
        if not court.camera_url:
            return jsonify({'error': f'Caméra non configurée pour le terrain {court_id}'}), 400
        
        # 🧹 Nettoyage préventif des sessions expirées
        cleanup_expired_sessions(court.club_id)

        # 🔒 Check if court already has active recording in DB
        existing_recording = RecordingSession.query.filter_by(
            court_id=court_id,
            status='active'
        ).first()

        if existing_recording:
            # Check if it's expired OR if it's a "zombie"
            # Une session est zombie si:
            # 1. Elle n'est PAS dans session_manager (serveur redémarré)
            # 2. OU Elle est dans session_manager MAIS recording_active est Faux (arrêt planté/timeout)
            
            is_zombie = existing_recording.recording_id not in session_manager.sessions
            if not is_zombie:
                 # Check memory status
                 mem_session = session_manager.sessions.get(existing_recording.recording_id)
                 if mem_session and not mem_session.recording_active:
                     is_zombie = True
                     logger.info(f"🧟 Session {existing_recording.recording_id} trouvée en mémoire mais INACTIVE -> Zombie cleanable")

            if existing_recording.is_expired() or is_zombie:
                reason = "expirée" if (existing_recording.is_expired() and not is_zombie) else "zombie/bug"
                logger.info(f"Session {reason} trouvée {existing_recording.recording_id}, nettoyage immédiat...")
                try:
                    # Pour un zombie pur (pas en RAM), on force le statut DB
                    if existing_recording.recording_id not in session_manager.sessions:
                         existing_recording.status = 'stopped'
                         existing_recording.end_time = datetime.now()
                         db.session.commit()
                         logger.info("✅ Session zombie (RAM missing) nettoyée en BDD")
                    else:
                        # Si elle est en RAM (même inactive), on tente un cleanup propre
                        _stop_recording_session(existing_recording, 'auto', user.id)
                        logger.info("✅ Session expirée/inactive nettoyée avec succès via stop_recording")
                except Exception as e:
                    logger.error(f"⚠️ Erreur nettoyage session {reason}: {e}")
            else:
                 return jsonify({
                     'success': False,
                     'error': f'Une session est déjà active sur ce terrain ({existing_recording.recording_id})',
                     'existing_recording_id': existing_recording.recording_id
                 }), 409
        
        logger.info(f"🎬 V3 Adapter: Nouvelle demande d'enregistrement - Terrain {court_id}, Durée: {duration_minutes} min")
        
        # 💳 VÉRIFIER LES CRÉDITS AVANT DE DÉMARRER
        if user.credits_balance < 1:
            return jsonify({
                'success': False,
                'error': 'Crédits insuffisants. Vous devez avoir au moins 1 crédit pour démarrer un enregistrement.'
            }), 400
        
        # 1. Créer session caméra
        try:
            session = session_manager.create_session(
                terrain_id=court_id,
                camera_url=court.camera_url,
                club_id=court.club_id,
                user_id=user.id
            )
            logger.info(f"✅ Session créée: {session.session_id}")
        except RuntimeError as e:
            # Conflict detected by SessionManager
            return jsonify({
                'success': False,
                'error': str(e)
            }), 409
        except Exception as e:
            logger.error(f"❌ Erreur création session: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': f'Erreur création session: {str(e)}'
            }), 500
        
        # 2. Démarrer enregistrement avec la durée en secondes
        try:
            success = video_recorder.start_recording(
                session=session,
                duration_seconds=duration_minutes * 60  # Convertir minutes → secondes pour FFmpeg
            )
            
            if not success:
                session_manager.close_session(session.session_id)
                return jsonify({
                    'success': False,
                    'error': 'Échec démarrage enregistrement'
                }), 500
            
            # 3. 🆕 Mettre à jour l'état du terrain dans la DB
            from datetime import datetime
            
            try:
                # 💳 DÉBITER 1 CRÉDIT (déjà vérifié avant)
                # Débiter 1 crédit
                user.credits_balance -= 1
                logger.info(f"💳 Crédit déduit: Nouveau solde = {user.credits_balance}")

                
                # Récupérer le club pour le titre
                club = Club.query.get(court.club_id)
                
                # ✅ NOUVEAU: Utiliser le titre personnalisé s'il existe, sinon générer le titre par défaut
                if custom_title:
                    final_title = custom_title
                else:
                    # Générer le titre par défaut: "date/club/terrain"
                    date_str = datetime.now().strftime("%d/%m/%Y")
                    club_name = club.name if club else "Club"
                    final_title = f"{date_str}/{club_name}/{court.name}"
                
                # Créer une entrée RecordingSession pour le suivi
                recording_session = RecordingSession(
                    recording_id=session.session_id,
                    court_id=court_id,
                    user_id=user.id,
                    club_id=court.club_id,
                    planned_duration=duration_minutes,
                    status='active',
                    title=final_title,  # ✅ Utilise le titre personnalisé ou par défaut
                    description=custom_description  # ✅ NOUVEAU: Sauvegarder la description
                )
                db.session.add(recording_session)
                
                # Marquer le terrain comme occupé
                court.is_recording = True
                
                db.session.commit()
                logger.info(f"📊 État terrain mis à jour: {court.name} → En enregistrement")
                
            except Exception as db_err:
                logger.error(f"⚠️ Erreur mise à jour DB: {db_err}")
                # Rollback et arrêter enregistrement proprement
                db.session.rollback()
                video_recorder.stop_recording(session.session_id)
                session_manager.close_session(session.session_id)
                return jsonify({
                    'success': False,
                    'error': f'Erreur base de données: {str(db_err)}'
                }), 500

            
            logger.info(f"✅ Enregistrement démarré via nouveau système: {session.session_id}")
            
            # Retourner format compatible avec l'ancien système
            return jsonify({
                'success': True,
                'message': 'Enregistrement démarré',
                'recording_id': session.session_id,
                'recording_info': {
                    'session_id': session.session_id,
                    'terrain_id': court_id,
                    'duration_seconds': duration_minutes * 60
                }
            }), 201
            
        except Exception as e:
            logger.error(f"❌ Erreur démarrage enregistrement: {e}", exc_info=True)
            # Arrêter enregistrement si démarré
            try:
                video_recorder.stop_recording(session.session_id)
                session_manager.close_session(session.session_id)
            except:
                pass
            return jsonify({
                'success': False,
                'error': f'Erreur enregistrement: {str(e)}'
            }), 500
        
    except Exception as e:
        logger.error(f"Error in v3 adapter: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        }), 500


@recording_bp.route('/v3/stop', methods=['POST'])
def stop_recording_v3():
    """Stop recording using recording_manager_v2"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        from src.services.recording_manager_v2 import get_recording_manager
        
        data = request.get_json()
        recording_id = data.get('recording_id')
        
        if not recording_id:
            return jsonify({'error': 'recording_id requis'}), 400
        
        recording_manager = get_recording_manager()
        
        success, message = recording_manager.stop_recording(
            recording_id=recording_id,
            reason='manual'
        )
        
        if not success:
            return jsonify({
                'success': False,
                'error': message
            }), 500
        
        # Get final recording info
        recording_info = recording_manager.get_recording_info(recording_id)
        
        response = {
            'success': True,
            'message': message,
            'recording_id': recording_id
        }
        
        if recording_info:
            response['final_video_path'] = recording_info.get('final_video_path')
            response['status'] = recording_info.get('status')
            
            # Calculate file size if video exists
            final_path = recording_info.get('final_video_path')
            if final_path and os.path.exists(final_path):
                file_size = os.path.getsize(final_path)
                response['file_size_mb'] = file_size / (1024**2)
        
        logger.info(f"✅ V3 Recording stopped: {recording_id}")
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error stopping v3 recording: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'Erreur: {str(e)}'
        }), 500


@recording_bp.route('/v3/status/<recording_id>', methods=['GET'])
def get_recording_status_v3(recording_id):
    """Get status of a recording"""
    try:
        from src.services.recording_manager_v2 import get_recording_manager
        
        recording_manager = get_recording_manager()
        recording_info = recording_manager.get_recording_info(recording_id)
        
        if not recording_info:
            return jsonify({'error': 'Enregistrement non trouvé'}), 404
        
        # Calculate elapsed time
        start_time = datetime.fromisoformat(recording_info['start_time'])
        elapsed_seconds = (datetime.now() - start_time).total_seconds()
        
        response = {
            'recording_id': recording_id,
            'status': recording_info.get('status'),
            'elapsed_seconds': int(elapsed_seconds),
            'duration_seconds': recording_info.get('duration_seconds'),
            'start_time': recording_info.get('start_time'),
            'expected_end_time': recording_info.get('expected_end_time'),
            'segments_written': recording_info.get('segments_written', []),
            'final_video_path': recording_info.get('final_video_path'),
            'errors': recording_info.get('errors', [])
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error getting recording status: {e}")
        return jsonify({'error': str(e)}), 500


@recording_bp.route('/v3/active', methods=['GET'])
def get_active_recordings_v3():
    """Get all active recordings"""
    try:
        from src.services.recording_manager_v2 import get_recording_manager
        
        recording_manager = get_recording_manager()
        active_recordings = recording_manager.get_all_active()
        
        return jsonify(active_recordings), 200
        
    except Exception as e:
        logger.error(f"Error getting active recordings: {e}")
        return jsonify({'error': str(e)}), 500


@recording_bp.route('/v3/diagnostics/<recording_id>', methods=['GET'])
def get_recording_diagnostics_v3(recording_id):
    """Get detailed diagnostics for a recording"""
    try:
        from src.services.recording_manager_v2 import get_recording_manager
        
        recording_manager = get_recording_manager()
        recording_info = recording_manager.get_recording_info(recording_id)
        
        if not recording_info:
            return jsonify({'error': 'Enregistrement non trouvé'}), 404
        
        # Enhanced diagnostics
        diagnostics = recording_info.copy()
        
        # Add file system info
        tmp_dir = recording_info.get('tmp_dir')
        if tmp_dir and os.path.exists(tmp_dir):
            tmp_files = os.listdir(tmp_dir)
            diagnostics['tmp_files'] = tmp_files
            diagnostics['tmp_file_count'] = len(tmp_files)
        
        final_path = recording_info.get('final_video_path')
        if final_path and os.path.exists(final_path):
            file_size = os.path.getsize(final_path)
            diagnostics['final_file_size_mb'] = file_size / (1024**2)
            diagnostics['final_file_exists'] = True
        else:
            diagnostics['final_file_exists'] = False
        
        return jsonify(diagnostics), 200
        
    except Exception as e:
        logger.error(f"Error getting diagnostics: {e}")
        return jsonify({'error': str(e)}), 500


@recording_bp.route('/v3/stream/<int:terrain_id>', methods=['GET'])
def get_stream_url_v3(terrain_id):
    """Get the streaming URL for a terrain's camera"""
    try:
        from src.services.video_proxy_manager_v2 import get_proxy_manager
        
        # Get court
        court = Court.query.get(terrain_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 404
        
        proxy_manager = get_proxy_manager()
        
        # Check if proxy is running
        proxy_info = proxy_manager.get_proxy_info(terrain_id)
        
        if not proxy_info:
            # Proxy not running, return camera URL and suggest starting it
            return jsonify({
                'terrain_id': terrain_id,
                'camera_url': court.camera_url,
                'proxy_active': False,
                'message': 'Proxy non démarré. Démarrez un enregistrement pour activer le proxy.'
            }), 200
        
        return jsonify({
            'terrain_id': terrain_id,
            'camera_url': court.camera_url,
            'proxy_url': proxy_info.get('proxy_url'),
            'proxy_active': True,
            'proxy_port': proxy_info.get('port')
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting stream URL: {e}")
        return jsonify({'error': str(e)}), 500
