"""
Module de gestion des vidéos et des enregistrements MJPEG pour PadelVar.
Système modernisé basé sur FFmpeg et Bunny Stream CDN.

Version 2.0 - Système d'enregistrement MJPEG vers Bunny Stream
"""

from flask import Blueprint, request, jsonify, session
from src.models.user import db, User, Video, Court, Club
from src.services.video_recording_engine import video_recording_engine
from datetime import datetime, timedelta
import logging
from typing import Dict, Any
from functools import wraps

logger = logging.getLogger(__name__)

# Création du Blueprint
videos_bp = Blueprint('videos', __name__)


def require_auth(f):
    """Décorateur pour vérifier l'authentification"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentification requise'}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_club_or_admin(f):
    """Décorateur pour vérifier les permissions club ou admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentification requise'}), 401
        
        user = User.query.get(session['user_id'])
        if not user or user.role.value not in ['club', 'super_admin']:
            return jsonify({'error': 'Permissions insuffisantes'}), 403
        
        return f(*args, **kwargs)
    return decorated_function


# ====================================================================
# ROUTES D'ENREGISTREMENT MJPEG
# ====================================================================

@videos_bp.route('/recording/start', methods=['POST'])
@require_club_or_admin
def start_mjpeg_recording():
    """Démarre un nouvel enregistrement MJPEG"""
    try:
        data = request.get_json()
        
        # Paramètres obligatoires
        court_id = data.get('court_id')
        if not court_id:
            return jsonify({'error': 'court_id requis'}), 400
        
        # Vérifier que le terrain existe
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 404
        
        # Paramètres optionnels
        duration = data.get('duration', 300)  # 5 minutes par défaut
        title = data.get('title', f'Match du {datetime.now().strftime("%d/%m/%Y")}')
        
        # Démarrer l'enregistrement via le nouveau moteur
        result = video_recording_engine.start_recording(
            court_id=court_id,
            user_id=session['user_id'],
            session_name=title
        )
        
        if result.get('success'):
            session_id = result.get('session_id')
            # Créer une entrée dans la base de données
            try:
                video = Video(
                    title=title,
                    description=f"Enregistrement automatique terrain {court_id}",
                    user_id=session['user_id'],
                    court_id=court_id,
                    file_url=f"recording://{session_id}",  # URL temporaire
                    duration=0,  # Sera mis à jour à la fin
                    is_unlocked=True,
                    credits_cost=0
                )
                db.session.add(video)
                db.session.commit()
                
                result['video_id'] = video.id
                
            except Exception as e:
                logger.error(f"Erreur création vidéo en DB: {e}")
                # Continue quand même avec l'enregistrement
        
        return jsonify(result), 200 if result.get('success') else 400
        
    except Exception as e:
        logger.error(f"Erreur lors du démarrage de l'enregistrement: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/recording/stop', methods=['POST'])
@require_club_or_admin
def stop_mjpeg_recording():
    """Arrête un enregistrement MJPEG"""
    try:
        data = request.get_json()
        session_id = data.get('session_id') or data.get('recording_id')
        
        if not session_id:
            return jsonify({'error': 'session_id requis'}), 400
        
        # Arrêter l'enregistrement via le nouveau moteur
        result = video_recording_engine.stop_recording(session_id)
        
        if result.get('success'):
            # Mettre à jour la vidéo en base de données
            try:
                video = Video.query.filter_by(
                    file_url=f"recording://{session_id}"
                ).first()
                
                if video:
                    stats = result.get('stats', {})
                    video.duration = int(stats.get('duration_seconds', 0))
                    video.file_url = f"bunny://segments/{session_id}"
                    db.session.commit()
                    
                    result['video_id'] = video.id
                    
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour de la vidéo: {e}")
        
        return jsonify(result), 200 if result['success'] else 400
        
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt de l'enregistrement: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/recording/status/<recording_id>', methods=['GET'])
@require_auth
def get_recording_status(recording_id):
    """Récupère le statut d'un enregistrement"""
    try:
        status = video_recording_engine.get_recording_status(recording_id)
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/recordings/active', methods=['GET'])
@require_club_or_admin
def get_active_recordings():
    """Récupère la liste des enregistrements actifs"""
    try:
        active_recordings = video_recording_engine.list_active_recordings()
        return jsonify({
            'active_recordings': active_recordings,
            'count': len(active_recordings)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des enregistrements actifs: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/recordings/stop-all', methods=['POST'])
@require_club_or_admin
def stop_all_recordings():
    """Arrête tous les enregistrements actifs"""
    try:
        # Récupérer tous les enregistrements actifs
        active_recordings = video_recording_engine.list_active_recordings()
        stopped_count = 0
        
        # Arrêter chaque enregistrement
        for recording in active_recordings:
            session_id = recording.get('session_id')
            if session_id:
                try:
                    video_recording_engine.stop_recording(session_id)
                    stopped_count += 1
                except Exception as e:
                    logger.error(f"Erreur arrêt {session_id}: {e}")
        
        return jsonify({
            'success': True,
            'message': f'{stopped_count} enregistrements arrêtés',
            'stopped_count': stopped_count
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt de tous les enregistrements: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


# ====================================================================
# ROUTES DE GESTION DES VIDÉOS
# ====================================================================

@videos_bp.route('/my-videos', methods=['GET'])
@require_auth
def get_my_videos():
    """Récupère les vidéos de l'utilisateur connecté"""
    try:
        user_id = session['user_id']
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
        
        # Construire la requête selon le rôle
        if user.role.value == 'super_admin':
            # Super admin voit toutes les vidéos
            videos = Video.query.order_by(Video.created_at.desc()).all()
        elif user.role.value == 'club':
            # Club voit les vidéos de ses terrains
            club = Club.query.filter_by(user_id=user_id).first()
            if club:
                court_ids = [court.id for court in club.courts]
                videos = Video.query.filter(
                    Video.court_id.in_(court_ids)
                ).order_by(Video.created_at.desc()).all()
            else:
                videos = []
        else:
            # Joueur voit ses propres vidéos
            videos = Video.query.filter_by(
                user_id=user_id
            ).order_by(Video.created_at.desc()).all()
        
        # Convertir en format API
        videos_data = []
        for video in videos:
            video_dict = video.to_dict()
            
            # Ajouter les informations utilisateur et terrain
            if video.user_id:
                video_user = User.query.get(video.user_id)
                video_dict['user_name'] = video_user.name if video_user else 'Inconnu'
            
            if video.court_id:
                court = Court.query.get(video.court_id)
                video_dict['court_name'] = f"Terrain {court.id}" if court else 'Terrain inconnu'
            
            videos_data.append(video_dict)
        
        return jsonify({
            'videos': videos_data,
            'count': len(videos_data),
            'user_role': user.role.value
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/video/<int:video_id>', methods=['GET'])
@require_auth
def get_video_details(video_id):
    """Récupère les détails d'une vidéo"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Vidéo non trouvée'}), 404
        
        # Vérifier les permissions
        user_id = session['user_id']
        user = User.query.get(user_id)
        
        can_access = False
        if user.role.value == 'super_admin':
            can_access = True
        elif user.role.value == 'club':
            club = Club.query.filter_by(user_id=user_id).first()
            if club and video.court_id in [court.id for court in club.courts]:
                can_access = True
        elif video.user_id == user_id:
            can_access = True
        
        if not can_access:
            return jsonify({'error': 'Accès non autorisé'}), 403
        
        # Construire la réponse
        video_dict = video.to_dict()
        
        # Ajouter les informations supplémentaires
        if video.user_id:
            video_user = User.query.get(video.user_id)
            video_dict['user_name'] = video_user.name if video_user else 'Inconnu'
        
        if video.court_id:
            court = Court.query.get(video.court_id)
            video_dict['court_name'] = f"Terrain {court.id}" if court else 'Terrain inconnu'
        
        return jsonify(video_dict), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la vidéo {video_id}: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/video/<int:video_id>', methods=['DELETE'])
@require_club_or_admin
def delete_video(video_id):
    """Supprime une vidéo"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Vidéo non trouvée'}), 404
        
        # Vérifier les permissions
        user_id = session['user_id']
        user = User.query.get(user_id)
        
        can_delete = False
        if user.role.value == 'super_admin':
            can_delete = True
        elif user.role.value == 'club':
            club = Club.query.filter_by(user_id=user_id).first()
            if club and video.court_id in [court.id for court in club.courts]:
                can_delete = True
        
        if not can_delete:
            return jsonify({'error': 'Permissions insuffisantes'}), 403
        
        # Supprimer la vidéo
        db.session.delete(video)
        db.session.commit()
        
        logger.info(f"Vidéo {video_id} supprimée par l'utilisateur {user_id}")
        
        return jsonify({
            'message': 'Vidéo supprimée avec succès',
            'video_id': video_id
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de la vidéo {video_id}: {e}")
        db.session.rollback()
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


# ====================================================================
# ROUTES DE STATUT DU SERVICE
# ====================================================================

@videos_bp.route('/service/status', methods=['GET'])
@require_auth
def get_service_status():
    """Récupère le statut du service d'enregistrement"""
    try:
        active_recordings = video_recording_engine.list_active_recordings()
        status = {
            'service': 'operational',
            'active_recordings_count': len(active_recordings),
            'engine': 'video_recording_engine',
            'version': '2.0'
        }
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut du service: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


@videos_bp.route('/service/config', methods=['GET'])
@require_club_or_admin
def get_service_config():
    """Récupère la configuration du service"""
    try:
        config = {
            'ffmpeg_path': getattr(video_recording_engine, 'FFMPEG_PATH', 'ffmpeg'),
            'video_dir': str(video_recording_engine.video_dir),
            'temp_dir': str(video_recording_engine.temp_dir),
            'max_duration': video_recording_engine.config['max_duration'],
            'fps': video_recording_engine.config['fps'],
            'resolution': video_recording_engine.config['resolution'],
            'keep_local_files': video_recording_engine.config['keep_local_files']
        }
        return jsonify({
            'config': config,
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la configuration: {e}")
        return jsonify({
            'error': 'Erreur interne du serveur',
            'details': str(e)
        }), 500


# ====================================================================
# ROUTES DE HEALTH CHECK
# ====================================================================

@videos_bp.route('/health', methods=['GET'])
def health_check():
    """Point de santé pour le monitoring"""
    try:
        # Test basique de la base de données
        from sqlalchemy import text
        db.session.execute(text('SELECT 1'))
        
        # Statut du service d'enregistrement
        active_recordings = video_recording_engine.list_active_recordings()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected',
            'recording_service': 'operational',
            'active_recordings': len(active_recordings)
        }), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }), 503


logger.info("🎥 Routes vidéo MJPEG chargées")
