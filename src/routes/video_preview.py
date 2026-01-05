"""
Routes Preview - Streaming Vidéo en Temps Réel
===============================================

Endpoints pour:
- Preview MJPEG (streaming continu)
- Snapshot JPEG (image unique)
- Support multi-viewers
"""

import logging
from flask import Blueprint, Response, jsonify, request
import requests

from ..video_system import session_manager
from ..models.user import UserRole
from ..routes.auth import get_current_user

logger = logging.getLogger(__name__)

# Blueprint
preview_bp = Blueprint('preview', __name__, url_prefix='/api/preview')


@preview_bp.route('/<session_id>/stream.mjpeg', methods=['GET'])
def stream_mjpeg(session_id: str):
    """
    Stream MJPEG en direct depuis le proxy
    
    Usage:
        <img src="/api/preview/<session_id>/stream.mjpeg" />
        <video src="/api/preview/<session_id>/stream.mjpeg" />
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    # Récupérer la session
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({'error': 'Session non trouvée'}), 404
    
    # Vérifier les droits
    if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
        if session.user_id != user.id:
            return jsonify({'error': 'Accès non autorisé'}), 403
    
    # Proxy le stream depuis le proxy local
    try:
        logger.info(f"📡 Stream preview demandé pour {session_id} par user {user.id}")
        
        # Connexion au proxy local
        proxy_response = requests.get(session.local_url, stream=True, timeout=30)
        
        if proxy_response.status_code != 200:
            return jsonify({'error': 'Proxy non disponible'}), 503
        
        # Re-stream vers le client
        def generate():
            try:
                for chunk in proxy_response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception as e:
                logger.error(f"❌ Erreur streaming: {e}")
        
        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erreur preview stream: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@preview_bp.route('/<session_id>/snapshot.jpg', methods=['GET'])
def snapshot(session_id: str):
    """
    Obtenir un snapshot JPEG unique
    
    Usage:
        <img src="/api/preview/<session_id>/snapshot.jpg" />
        Polling toutes les N secondes pour preview animée
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    # Récupérer la session
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({'error': 'Session non trouvée'}), 404
    
    # Vérifier les droits
    if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
        if session.user_id != user.id:
            return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        # Construire l'URL du snapshot depuis le proxy
        snapshot_url = session.local_url.replace('/stream.mjpg', '/snapshot.jpg')
        
        # Récupérer le snapshot
        response = requests.get(snapshot_url, timeout=5)
        
        if response.status_code != 200:
            return jsonify({'error': 'Snapshot non disponible'}), 503
        
        return Response(
            response.content,
            mimetype='image/jpeg',
            headers={
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Erreur snapshot: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@preview_bp.route('/<session_id>/info', methods=['GET'])
def preview_info(session_id: str):
    """
    Obtenir les infos du preview (URL, status, etc.)
    """
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    # Récupérer la session
    session = session_manager.get_session(session_id)
    if not session:
        return jsonify({'error': 'Session non trouvée'}), 404
    
    # Vérifier les droits
    if user.role not in [UserRole.SUPER_ADMIN, UserRole.CLUB_ADMIN]:
        if session.user_id != user.id:
            return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        # Vérifier la santé du proxy
        health_url = session.local_url.replace('/stream.mjpg', '/health')
        
        proxy_healthy = False
        try:
            health_response = requests.get(health_url, timeout=2)
            proxy_healthy = health_response.status_code == 200
        except:
            pass
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'proxy_healthy': proxy_healthy,
            'proxy_url': session.local_url,
            'stream_url': f'/api/preview/{session_id}/stream.mjpeg',
            'snapshot_url': f'/api/preview/{session_id}/snapshot.jpg',
            'recording_active': session.recording_active
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur preview info: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
