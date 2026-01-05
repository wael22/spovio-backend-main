"""
Routes Flask pour gérer les enregistrements vidéo et les proxies vidéo
Intégration du système d'enregistrement avec Video Proxy Server et FFmpeg
"""
import logging
from flask import Blueprint, request, jsonify, Response
from functools import wraps
from datetime import datetime
import asyncio

from ..models.database import db
from ..models.user import User, UserRole
from ..services.flask_recording_manager import get_recording_manager
from ..services.flask_proxy_manager import get_proxy_manager

logger = logging.getLogger(__name__)

recording_bp = Blueprint('recording_integration', __name__)

# Initialiser les gestionnaires
recording_manager = get_recording_manager()
proxy_manager = get_proxy_manager()


def token_required(f):
    """Décorateur pour vérifier le token JWT"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]
            except IndexError:
                return jsonify({'message': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        try:
            # Vérifier le token (à adapter selon votre implémentation JWT)
            # Pour l'instant, on récupère l'utilisateur depuis la session
            from flask import session
            if 'user_id' not in session:
                return jsonify({'message': 'Invalid token'}), 401
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return jsonify({'message': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    
    return decorated


def get_current_user():
    """Obtenir l'utilisateur courant depuis la session"""
    from flask import session
    if 'user_id' not in session:
        return None
    
    user = User.query.get(session['user_id'])
    return user


@recording_bp.route('/api/recording/matches/<int:match_id>/recording/start', methods=['POST'])
@token_required
def start_recording(match_id):
    """Démarrer un enregistrement vidéo pour un match"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'message': 'User not authenticated'}), 401
        
        # Récupérer le match
        from ..models.user import Match, Court, RecordingStatus
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'message': 'Match not found'}), 404
        
        # Vérifier les permissions
        if current_user.role == UserRole.PLAYER:
            if match.player_id != current_user.id:
                return jsonify({'message': 'Players can only start recording for their own matches'}), 403
        
        # Vérifier que le match n'est pas déjà en cours d'enregistrement
        if hasattr(match, 'recording_status') and match.recording_status == RecordingStatus.RECORDING:
            return jsonify({'message': 'Recording already in progress for this match'}), 409
        
        # Récupérer le terrain
        court = Court.query.get(match.court_id)
        if not court:
            return jsonify({'message': 'Court not found'}), 404
        
        # Vérifier que la caméra est configurée
        if not hasattr(court, 'camera_url') or not court.camera_url:
            return jsonify({'message': f'Camera not configured for court {court.id}'}), 502
        
        # Démarrer le proxy si nécessaire
        if not proxy_manager.is_proxy_healthy(court.id):
            logger.info(f"Starting proxy for court {court.id}")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(proxy_manager.start_proxy(court.id, court.camera_url))
            finally:
                loop.close()
        
        # Récupérer la durée si fournie
        duration = request.json.get('duration') if request.json else None
        
        # Démarrer l'enregistrement
        video_path = recording_manager.start_recording(
            match_id=match.id,
            court_id=court.id,
            duration_seconds=duration
        )
        
        # Mettre à jour le statut du match
        if hasattr(match, 'video_path'):
            match.video_path = video_path
        if hasattr(match, 'recording_status'):
            match.recording_status = RecordingStatus.RECORDING
        db.session.commit()
        
        logger.info(f"Recording started for match {match_id} by user {current_user.id}")
        
        return jsonify({
            'match_id': match.id,
            'status': 'recording',
            'video_path': video_path
        }), 200
        
    except ValueError as e:
        return jsonify({'message': str(e)}), 409
    except Exception as e:
        logger.error(f"Failed to start recording for match {match_id}: {e}")
        return jsonify({'message': 'Failed to start recording'}), 500


@recording_bp.route('/api/recording/matches/<int:match_id>/recording/stop', methods=['POST'])
@token_required
def stop_recording(match_id):
    """Arrêter un enregistrement vidéo"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'message': 'User not authenticated'}), 401
        
        # Vérifier les permissions
        if current_user.role != UserRole.CLUB:
            return jsonify({'message': 'Only club can stop recordings'}), 403
        
        # Récupérer le match
        from ..models.user import Match, RecordingStatus
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'message': 'Match not found'}), 404
        
        # Vérifier qu'un enregistrement est en cours
        if not recording_manager.is_recording(match_id):
            return jsonify({'message': 'No active recording found for this match'}), 404
        
        # Arrêter l'enregistrement
        video_path = recording_manager.stop_recording(match_id)
        
        # Mettre à jour le statut du match
        if hasattr(match, 'recording_status'):
            match.recording_status = RecordingStatus.DONE
        db.session.commit()
        
        logger.info(f"Recording stopped for match {match_id} by user {current_user.id}")
        
        return jsonify({
            'match_id': match.id,
            'status': 'done',
            'video_path': video_path
        }), 200
        
    except ValueError as e:
        return jsonify({'message': str(e)}), 404
    except Exception as e:
        logger.error(f"Failed to stop recording for match {match_id}: {e}")
        return jsonify({'message': 'Failed to stop recording'}), 500


@recording_bp.route('/api/recording/matches/<int:match_id>/recording/status', methods=['GET'])
@token_required
def get_recording_status(match_id):
    """Obtenir le statut d'un enregistrement"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'message': 'User not authenticated'}), 401
        
        # Récupérer le match
        from ..models.user import Match
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'message': 'Match not found'}), 404
        
        is_recording = recording_manager.is_recording(match_id)
        
        return jsonify({
            'match_id': match.id,
            'recording_status': getattr(match, 'recording_status', 'unknown'),
            'is_recording': is_recording,
            'video_path': getattr(match, 'video_path', None)
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get recording status for match {match_id}: {e}")
        return jsonify({'message': 'Failed to get recording status'}), 500


@recording_bp.route('/api/recording/courts/<int:court_id>/camera', methods=['POST'])
@token_required
def set_court_camera(court_id):
    """Configurer la caméra pour un terrain"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'message': 'User not authenticated'}), 401
        
        # Vérifier les permissions
        if current_user.role != UserRole.CLUB:
            return jsonify({'message': 'Only club can configure cameras'}), 403
        
        # Récupérer le terrain
        from ..models.user import Court
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'message': 'Court not found'}), 404
        
        # Récupérer l'URL de la caméra
        data = request.json
        if not data or 'url' not in data:
            return jsonify({'message': 'Camera URL is required'}), 400
        
        camera_url = data['url']
        
        # Mettre à jour l'URL de la caméra
        court.camera_url = camera_url
        db.session.commit()
        
        # Mettre à jour le proxy
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(proxy_manager.set_camera_url(court_id, camera_url))
            finally:
                loop.close()
            logger.info(f"Camera URL updated for court {court_id}")
        except Exception as e:
            logger.error(f"Failed to update proxy for court {court_id}: {e}")
            return jsonify({'message': 'Failed to configure proxy'}), 502
        
        stream_url = proxy_manager.get_stream_url(court_id)
        
        return jsonify({
            'court_id': court_id,
            'stream_url': stream_url
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to set court camera for court {court_id}: {e}")
        return jsonify({'message': 'Failed to set court camera'}), 500


@recording_bp.route('/api/recording/courts/<int:court_id>/stream_url', methods=['GET'])
@token_required
def get_stream_url(court_id):
    """Obtenir l'URL du flux vidéo pour un terrain"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'message': 'User not authenticated'}), 401
        
        # Récupérer le terrain
        from ..models.user import Court
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'message': 'Court not found'}), 404
        
        stream_url = proxy_manager.get_stream_url(court_id)
        
        return jsonify({
            'court_id': court_id,
            'stream_url': stream_url
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get stream URL for court {court_id}: {e}")
        return jsonify({'message': 'Failed to get stream URL'}), 500


@recording_bp.route('/api/recording/recordings/active', methods=['GET'])
@token_required
def get_active_recordings():
    """Obtenir la liste des enregistrements actifs"""
    try:
        current_user = get_current_user()
        if not current_user:
            return jsonify({'message': 'User not authenticated'}), 401
        
        # Vérifier les permissions
        if current_user.role != UserRole.CLUB:
            return jsonify({'message': 'Only club can view all active recordings'}), 403
        
        active_recordings = recording_manager.get_active_recordings()
        
        return jsonify({
            'active_recordings': active_recordings
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get active recordings: {e}")
        return jsonify({'message': 'Failed to get active recordings'}), 500


@recording_bp.route('/api/recording/stream/<int:court_id>', methods=['GET'])
def stream_video(court_id):
    """Streamer le flux vidéo MJPEG pour un terrain"""
    try:
        # Récupérer le proxy
        proxy = proxy_manager.proxies.get(court_id, {}).get('proxy')
        if not proxy:
            return jsonify({'message': 'Proxy not found for this court'}), 404
        
        # Générer les frames
        def generate():
            for frame in proxy.generate_frames():
                yield frame
        
        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
        
    except Exception as e:
        logger.error(f"Failed to stream video for court {court_id}: {e}")
        return jsonify({'message': 'Failed to stream video'}), 500
