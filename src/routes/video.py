"""
Routes API - Système Vidéo Stable
==================================

Endpoints pour:
- Gestion sessions (create, close, list, get)
- Enregistrement vidéo (start, stop, status)
- Gestion fichiers vidéo (list, download, delete)
- Health check

Pipeline: Caméra → video_proxy_server.py → FFmpeg → MP4 unique
"""

import logging
from flask import Blueprint, request, jsonify, send_file
from pathlib import Path

# Import des modules vidéo
from ..video_system import session_manager, video_recorder, VideoConfig
from ..video_system.session_manager import VideoSession

# Import des modèles existants
from ..models.database import db
from ..models.user import Court, User, UserRole
from ..routes.auth import get_current_user

logger = logging.getLogger(__name__)

# Blueprint
video_bp = Blueprint('video', __name__, url_prefix='/api/video')


# ======================
# SESSIONS
# ======================

@video_bp.route('/session/create', methods=['POST'])
def create_session():
    """
    Créer une session caméra avec proxy
    
    Body:
    {
        "terrain_id": int,
        "camera_url": str (optionnel, sera récupéré depuis Court)
    }
    
    Returns:
    {
        "success": true,
        "session": {...}
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.json
        terrain_id = data.get('terrain_id')
        
        if not terrain_id:
            return jsonify({'error': 'terrain_id requis'}), 400
        
        # Récupérer le terrain
        court = Court.query.get(terrain_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 404
        
        # Vérifier que l'utilisateur a accès au club
        if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
            # Joueur normal : vérifier qu'il appartient au club
            if hasattr(user, 'club_id') and user.club_id != court.club_id:
                return jsonify({'error': 'Accès non autorisé à ce terrain'}), 403
        
        # URL caméra
        camera_url = data.get('camera_url') or court.camera_url
        if not camera_url:
            return jsonify({'error': 'Caméra non configurée pour ce terrain'}), 400
        
        # Créer la session
        session = session_manager.create_session(
            terrain_id=terrain_id,
            camera_url=camera_url,
            club_id=court.club_id,
            user_id=user.id
        )
        
        logger.info(f"✅ Session créée: {session.session_id} par user {user.id}")
        
        return jsonify({
            'success': True,
            'session': session.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"❌ Erreur création session: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/session/close', methods=['POST'])
def close_session():
    """
    Fermer une session (seulement si pas d'enregistrement actif)
    
    Body:
    {
        "session_id": str
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'error': 'session_id requis'}), 400
        
        # Récupérer la session
        session = session_manager.get_session(session_id)
        if not session:
            return jsonify({'error': 'Session non trouvée'}), 404
        
        # Vérifier les droits
        if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
            if session.user_id != user.id:
                return jsonify({'error': 'Accès non autorisé à cette session'}), 403
        
        # Vérifier qu'il n'y a pas d'enregistrement actif
        if session.recording_active:
            return jsonify({'error': 'Enregistrement actif, arrêtez-le d\'abord'}), 400
        
        session_manager.close_session(session_id)
        logger.info(f"✅ Session fermée: {session_id} par user {user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Session {session_id} fermée'
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur fermeture session: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/session/list', methods=['GET'])
def list_sessions():
    """Lister les sessions actives (filtrées selon le rôle)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        sessions = session_manager.list_sessions()
        
        # Filtrer selon le rôle
        if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
            # Joueur : voir uniquement ses sessions
            sessions = [s for s in sessions if s['user_id'] == user.id]
        elif user.role == UserRole.CLUB_ADMIN:
            # Admin club : voir les sessions de son club
            if hasattr(user, 'club_id') and user.club_id:
                sessions = [s for s in sessions if s['club_id'] == user.club_id]
        
        return jsonify({
            'success': True,
            'sessions': sessions,
            'count': len(sessions)
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur liste sessions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/session/<session_id>', methods=['GET'])
def get_session(session_id: str):
    """Obtenir les détails d'une session"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        session = session_manager.get_session(session_id)
        
        if not session:
            return jsonify({'error': 'Session non trouvée'}), 404
        
        # Vérifier les droits
        if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
            if session.user_id != user.id:
                return jsonify({'error': 'Accès non autorisé à cette session'}), 403
        
        return jsonify({
            'success': True,
            'session': session.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur récupération session: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ======================
# RECORDING
# ======================

@video_bp.route('/record/start', methods=['POST'])
def start_recording():
    """
    Démarrer un enregistrement
    
    Body:
    {
        "session_id": str,
        "duration_minutes": int (optionnel, défaut: 90)
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.json
        session_id = data.get('session_id')
        duration_minutes = data.get('duration_minutes', 90)
        
        if not session_id:
            return jsonify({'error': 'session_id requis'}), 400
        
        # Récupérer la session
        session = session_manager.get_session(session_id)
        if not session:
            return jsonify({'error': 'Session non trouvée'}), 404
        
        # Vérifier les droits
        if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
            if session.user_id != user.id:
                return jsonify({'error': 'Accès non autorisé à cette session'}), 403
        
        # Vérifier que l'enregistrement n'est pas déjà actif
        if session.recording_active:
            return jsonify({'error': 'Enregistrement déjà actif'}), 400
        
        # Démarrer l'enregistrement
        success = video_recorder.start_recording(
            session=session,
            duration_seconds=duration_minutes * 60
        )
        
        if not success:
            return jsonify({'error': 'Échec démarrage enregistrement'}), 500
        
        logger.info(f"✅ Enregistrement démarré: {session_id} par user {user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Enregistrement démarré',
            'session_id': session_id,
            'duration_minutes': duration_minutes
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur démarrage enregistrement: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/record/stop', methods=['POST'])
def stop_recording():
    """
    Arrêter un enregistrement
    
    Body:
    {
        "session_id": str
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'error': 'session_id requis'}), 400
        
        # Récupérer la session
        session = session_manager.get_session(session_id)
        if not session:
            return jsonify({'error': 'Session non trouvée'}), 404
        
        # Vérifier les droits (plus stricte pour l'arrêt)
        can_stop = False
        if user.role == UserRole.SUPER_ADMIN:
            can_stop = True
        elif user.role == UserRole.CLUB_ADMIN:
            # Admin du club peut stopper
            if hasattr(user, 'club_id') and user.club_id == session.club_id:
                can_stop = True
        elif session.user_id == user.id:
            # Propriétaire de la session
            can_stop = True
        
        if not can_stop:
            return jsonify({'error': 'Accès non autorisé pour arrêter cet enregistrement'}), 403
        
        # Arrêter l'enregistrement
        video_path = video_recorder.stop_recording(session_id)
        
        if not video_path:
            return jsonify({'error': 'Échec arrêt enregistrement'}), 500
        
        # Mettre à jour la session
        session.recording_active = False
        
        logger.info(f"✅ Enregistrement arrêté: {session_id} par user {user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Enregistrement arrêté',
            'video_path': video_path,
            'session_id': session_id
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur arrêt enregistrement: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/record/status/<session_id>', methods=['GET'])
def get_recording_status(session_id: str):
    """Obtenir le statut d'un enregistrement"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Récupérer la session pour vérifier les droits
        session = session_manager.get_session(session_id)
        if not session:
            return jsonify({'error': 'Session non trouvée'}), 404
        
        # Vérifier les droits
        if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
            if session.user_id != user.id:
                return jsonify({'error': 'Accès non autorisé'}), 403
        
        # Obtenir le statut
        status = video_recorder.get_recording_status(session_id)
        
        if not status:
            return jsonify({
                'success': True,
                'status': {
                    'session_id': session_id,
                    'active': False,
                    'message': 'Aucun enregistrement actif'
                }
            }), 200
        
        return jsonify({
            'success': True,
            'status': status
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur statut enregistrement: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ======================
# FILES
# ======================

@video_bp.route('/files/list', methods=['GET'])
def list_video_files():
    """Lister les fichiers vidéo d'un club"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        club_id = request.args.get('club_id')
        
        # Déterminer le club_id selon le rôle
        if not club_id:
            if hasattr(user, 'club_id'):
                club_id = user.club_id
            else:
                return jsonify({'error': 'club_id requis'}), 400
        
        club_id = int(club_id)
        
        # Vérifier les droits
        if user.role not in [UserRole.SUPER_ADMIN]:
            if hasattr(user, 'club_id') and user.club_id != club_id:
                return jsonify({'error': 'Accès non autorisé à ce club'}), 403
        
        # Lister les fichiers
        video_dir = VideoConfig.get_video_dir(club_id)
        
        if not video_dir.exists():
            return jsonify({
                'success': True,
                'videos': [],
                'count': 0
            }), 200
        
        videos = []
        for video_file in video_dir.glob('*.mp4'):
            stats = video_file.stat()
            videos.append({
                'filename': video_file.name,
                'session_id': video_file.stem,
                'size_mb': round(stats.st_size / (1024 * 1024), 2),
                'created_at': stats.st_ctime,
                'path': str(video_file)
            })
        
        # Trier par date de création (plus récent en premier)
        videos.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            'success': True,
            'videos': videos,
            'count': len(videos),
            'club_id': club_id
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur liste fichiers: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/files/<session_id>/download', methods=['GET'])
def download_video(session_id: str):
    """Télécharger un fichier vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        club_id = request.args.get('club_id')
        if not club_id:
            if hasattr(user, 'club_id'):
                club_id = user.club_id
            else:
                return jsonify({'error': 'club_id requis'}), 400
        
        club_id = int(club_id)
        
        # Vérifier les droits
        if user.role not in [UserRole.SUPER_ADMIN]:
            if hasattr(user, 'club_id') and user.club_id != club_id:
                return jsonify({'error': 'Accès non autorisé'}), 403
        
        video_path = VideoConfig.get_video_dir(club_id) / f"{session_id}.mp4"
        
        if not video_path.exists():
            return jsonify({'error': 'Fichier non trouvé'}), 404
        
        logger.info(f"📥 Téléchargement vidéo: {session_id} par user {user.id}")
        
        return send_file(
            video_path,
            as_attachment=True,
            download_name=f"{session_id}.mp4",
            mimetype='video/mp4'
        )
        
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@video_bp.route('/files/<session_id>/delete', methods=['DELETE'])
def delete_video(session_id: str):
    """Supprimer un fichier vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    # Seuls les admins peuvent supprimer
    if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        club_id = request.args.get('club_id')
        if not club_id:
            if hasattr(user, 'club_id'):
                club_id = user.club_id
            else:
                return jsonify({'error': 'club_id requis'}), 400
        
        club_id = int(club_id)
        
        # Vérifier les droits
        if user.role == UserRole.CLUB_ADMIN:
            if hasattr(user, 'club_id') and user.club_id != club_id:
                return jsonify({'error': 'Accès non autorisé'}), 403
        
        video_path = VideoConfig.get_video_dir(club_id) / f"{session_id}.mp4"
        
        if not video_path.exists():
            return jsonify({'error': 'Fichier non trouvé'}), 404
        
        # Supprimer le fichier
        video_path.unlink()
        
        # Supprimer le log associé si présent
        log_path = VideoConfig.get_log_path(session_id)
        if log_path.exists():
            log_path.unlink()
        
        logger.info(f"🗑️ Vidéo supprimée: {session_id} par user {user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Vidéo {session_id} supprimée'
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur suppression: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ======================
# HEALTH & INFO
# ======================

@video_bp.route('/health', methods=['GET'])
def health_check():
    """Vérifier la santé du système vidéo"""
    try:
        # Vérifier FFmpeg
        ffmpeg_ok = VideoConfig.validate_ffmpeg()
        
        # Compter les sessions et enregistrements actifs
        sessions = session_manager.list_sessions()
        active_recordings = len([s for s in sessions if s['recording_active']])
        
        return jsonify({
            'status': 'healthy' if ffmpeg_ok else 'degraded',
            'ffmpeg_available': ffmpeg_ok,
            'ffmpeg_path': VideoConfig.FFMPEG_PATH,
            'active_sessions': len(sessions),
            'active_recordings': active_recordings,
            'max_concurrent': VideoConfig.MAX_CONCURRENT_RECORDINGS,
            'proxy_type': 'video_proxy_server.py (internal)',
            'pipeline': 'Camera → video_proxy_server.py → FFmpeg → MP4'
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur health check: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@video_bp.route('/cleanup', methods=['POST'])
def cleanup_orphan_sessions():
    """Nettoyer les sessions orphelines (admin uniquement)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        cleaned = session_manager.cleanup_orphan_sessions()
        
        logger.info(f"🧹 Nettoyage sessions orphelines: {cleaned} sessions nettoyées par user {user.id}")
        
        return jsonify({
            'success': True,
            'cleaned_sessions': cleaned,
            'message': f'{cleaned} session(s) orpheline(s) nettoyée(s)'
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur cleanup: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
