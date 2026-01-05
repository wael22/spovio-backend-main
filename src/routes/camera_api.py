from flask import Blueprint, request, jsonify, session
from src.services.camera_capture_service import camera_capture
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
camera_bp = Blueprint('camera', __name__)


def require_auth(f):
    """Décorateur pour vérifier l'authentification"""
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function


@camera_bp.route('/test-camera', methods=['POST'])
@require_auth
def test_camera():
    """Teste la connexion à une caméra"""
    try:
        data = request.get_json()
        camera_url = data.get('camera_url')
        
        if not camera_url:
            return jsonify({'error': 'URL caméra requise'}), 400
        
        success, message = camera_capture.test_camera_connection(camera_url)
        
        return jsonify({
            'success': success,
            'message': message,
            'camera_url': camera_url
        }), 200 if success else 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@camera_bp.route('/start-recording', methods=['POST'])  
@require_auth
def start_recording():
    """Démarre un enregistrement"""
    try:
        data = request.get_json()
        
        recording_id = data.get('recording_id')
        camera_url = data.get('camera_url')
        duration_minutes = data.get('duration_minutes', 60)
        quality = data.get('quality', 'medium')
        title = data.get('title', 'Enregistrement')
        
        if not recording_id or not camera_url:
            return jsonify({'error': 'recording_id et camera_url requis'}), 400
        
        success, message = camera_capture.start_capture(
            recording_id, camera_url, duration_minutes, quality, title
        )
        
        if success:
            return jsonify({
                'message': 'Enregistrement démarré',
                'recording_id': recording_id,
                'duration_minutes': duration_minutes,
                'quality': quality,
                'camera_url': camera_url
            }), 200
        else:
            return jsonify({'error': message}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@camera_bp.route('/stop-recording/<recording_id>', methods=['POST'])
@require_auth  
def stop_recording(recording_id):
    """Arrête un enregistrement"""
    try:
        success, message = camera_capture.stop_capture(recording_id)
        
        return jsonify({
            'message': message,
            'recording_id': recording_id,
            'success': success
        }), 200 if success else 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@camera_bp.route('/recording-status/<recording_id>', methods=['GET'])
@require_auth
def get_recording_status(recording_id):
    """Récupère le statut d'un enregistrement"""
    try:
        status = camera_capture.get_capture_status(recording_id)
        
        if status:
            return jsonify(status), 200
        else:
            return jsonify({'error': 'Enregistrement non trouvé'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@camera_bp.route('/active-recordings', methods=['GET'])
@require_auth
def get_active_recordings():
    """Récupère tous les enregistrements actifs"""
    try:
        active_recordings = camera_capture.get_all_active_captures()
        
        return jsonify({
            'active_recordings': active_recordings,
            'count': len(active_recordings)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@camera_bp.route('/cleanup', methods=['POST'])
@require_auth  
def cleanup_recordings():
    """Nettoie les enregistrements terminés"""
    try:
        cleaned = camera_capture.cleanup_finished_captures()
        
        return jsonify({
            'message': f'{cleaned} enregistrements nettoyés',
            'cleaned_count': cleaned
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
