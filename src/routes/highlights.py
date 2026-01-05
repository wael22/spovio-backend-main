"""
Routes API pour la génération de highlights
"""

from flask import Blueprint, request, jsonify
from src.models.database import db
from src.models.user import HighlightJob, HighlightVideo
from src.services.simple_highlights_service import simple_highlights_service
from datetime import datetime
from functools import wraps
import logging
import threading
import jwt

logger = logging.getLogger(__name__)

# Décorateur login_required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(' ')[1]
            except IndexError:
                return jsonify({'error': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            from flask import current_app
            from src.models.user import User
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = User.query.filter_by(id=data['user_id']).first()
            if not current_user:
                return jsonify({'error': 'User not found'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            return jsonify({'error': str(e)}), 401
        
        return f(current_user, *args, **kwargs)
    return decorated_function

highlights_bp = Blueprint('highlights', __name__, url_prefix='/api/highlights')

@highlights_bp.route('/generate', methods=['POST'])
@login_required
def generate_highlights(current_user):
    """
    Démarre la génération de highlights pour une vidéo
    
    Body JSON:
    {
        "video_id": 123,
        "target_duration": 90  // optionnel, défaut 90s
    }
    """
    try:
        data = request.get_json()
        
        video_id = data.get('video_id')
        if not video_id:
            return jsonify({"error": "video_id is required"}), 400
        
        target_duration = data.get('target_duration', 90)
        
        # Créer le job
        job = simple_highlights_service.create_highlights_job(
            video_id=video_id,
            user_id=current_user.id,
            target_duration=target_duration
        )
        
        # Lancer le traitement en arrière-plan
        def process_async():
            try:
                simple_highlights_service.process_highlights(job.id)
            except Exception as e:
                logger.error(f"Error processing highlights job {job.id}: {e}")
        
        thread = threading.Thread(target=process_async)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "success": True,
            "job": job.to_dict(),
            "message": "Highlight generation started"
        }), 201
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error in generate_highlights: {e}")
        return jsonify({"error": "Internal server error"}), 500

@highlights_bp.route('/jobs/<int:job_id>/status', methods=['GET'])
def get_job_status(job_id):
    """Récupère le statut d'un job de génération"""
    try:
        job = HighlightJob.query.get(job_id)
        
        if not job:
            return jsonify({"error": "Job not found"}), 404
        
        response = job.to_dict()
        
        # Ajouter les infos de la vidéo highlight si disponible
        if job.highlight_video_id:
            highlight = HighlightVideo.query.get(job.highlight_video_id)
            if highlight:
                response['highlight_video'] = highlight.to_dict()
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        return jsonify({"error": "Internal server error"}), 500

@highlights_bp.route('/video/<int:video_id>', methods=['GET'])
def get_video_highlights(video_id):
    """Liste tous les highlights générés pour une vidéo"""
    try:
        highlights = HighlightVideo.query.filter_by(
            original_video_id=video_id
        ).all()
        
        return jsonify({
            "highlights": [h.to_dict() for h in highlights]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting video highlights: {e}")
        return jsonify({"error": "Internal server error"}), 500

@highlights_bp.route('/jobs', methods=['GET'])
@login_required
def list_user_jobs(current_user):
    """Liste tous les jobs de l'utilisateur"""
    try:
        jobs = HighlightJob.query.filter_by(
            user_id=current_user.id
        ).order_by(HighlightJob.created_at.desc()).limit(50).all()
        
        return jsonify({
            "jobs": [j.to_dict() for j in jobs]
        }), 200
        
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        return jsonify({"error": "Internal server error"}), 500

@highlights_bp.route('/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
def cancel_job(current_user, job_id):
    """Annule un job en cours (si possible)"""
    try:
        job = HighlightJob.query.get(job_id)
        
        if not job:
            return jsonify({"error": "Job not found"}), 404
        
        # Vérifier que c'est bien le job de l'utilisateur
        if job.user_id != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        
        # On peut seulement annuler les jobs en attente
        if job.status == 'queued':
            job.status = 'failed'
            job.error_message = 'Cancelled by user'
            job.completed_at = datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "Job cancelled"
            }), 200
        else:
            return jsonify({
                "error": f"Cannot cancel job in status: {job.status}"
            }), 400
        
    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        return jsonify({"error": "Internal server error"}), 500
