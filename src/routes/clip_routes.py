"""
Routes API pour la gestion des clips vidéo manuels
"""

from flask import Blueprint, request, jsonify, session
from src.models.database import db
from src.models.user import UserClip, Video, User
from src.models.notification import Notification, NotificationType
from src.services.manual_clip_service import manual_clip_service
from src.services.social_share_service import social_share_service
from functools import wraps
import logging
import threading

logger = logging.getLogger(__name__)

# Décorateur login_required basé sur la session
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        
        current_user = User.query.get(session['user_id'])
        if not current_user:
            return jsonify({'error': 'Utilisateur non trouvé'}), 401
        
        return f(current_user, *args, **kwargs)
    return decorated_function

clip_bp = Blueprint('clips', __name__, url_prefix='/api/clips')

@clip_bp.route('/create', methods=['POST'])
@login_required
def create_clip(current_user):
    """
    Crée un nouveau clip depuis une vidéo
    
    Body JSON:
    {
        "video_id": 123,
        "start_time": 10.5,
        "end_time": 25.3,
        "title": "Mon meilleur point",
        "description": "Description optionnelle"
    }
    """
    try:
        data = request.get_json()
        
        # Validation
        required_fields = ['video_id', 'start_time', 'end_time', 'title']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        video_id = data['video_id']
        start_time = float(data['start_time'])
        end_time = float(data['end_time'])
        title = data['title']
        description = data.get('description')
        
        # Créer le clip
        clip = manual_clip_service.create_clip(
            video_id=video_id,
            user_id=current_user.id,
            start_time=start_time,
            end_time=end_time,
            title=title,
            description=description
        )
        
        
        # Lancer le traitement en arrière-plan
        # Capturer l'instance Flask avant le thread
        from flask import current_app
        app = current_app._get_current_object()
        
        def process_async():
            try:
                with app.app_context():
                    manual_clip_service.process_clip(clip.id)
            except Exception as e:
                logger.error(f"Error processing clip {clip.id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        thread = threading.Thread(target=process_async)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'clip': clip.to_dict(),
            'message': 'Clip creation started'
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error creating clip: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@clip_bp.route('/upload-direct', methods=['POST'])
@login_required
def upload_direct_clip(current_user):
    """
    Upload MP4 clip directly depuis le frontend (FFmpeg.wasm)
    
    Form Data:
        file: Fichier MP4 du clip
        video_id: ID de la vidéo source
        title: Titre du clip
        description: Description (optionnel)
        start_time: Timestamp début
        end_time: Timestamp fin
    """
    try:
        # Vérifier que le fichier est présent
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        
        # Récupérer métadonnées
        video_id = request.form.get('video_id', type=int)
        title = request.form.get('title')
        description = request.form.get('description')
        start_time = request.form.get('start_time', type=float)
        end_time = request.form.get('end_time', type=float)
        
        logger.info(f"DEBUG UPLOAD: video_id={video_id} (type={type(video_id)})")
        logger.info(f"DEBUG UPLOAD: title='{title}'")
        logger.info(f"DEBUG UPLOAD: start_time={start_time} (type={type(start_time)})")
        logger.info(f"DEBUG UPLOAD: end_time={end_time} (type={type(end_time)})")
        
        # Validation
        if not all([video_id, title, start_time is not None, end_time is not None]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Vérifier que la vidéo existe
        from src.models.user import Video
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Video not found'}), 404
        
        # Pas de restriction - tous les joueurs peuvent créer des clips
        
        # Créer le clip en DB (status pending)
        clip = manual_clip_service.create_clip(
            video_id=video_id,
            user_id=current_user.id,
            start_time=start_time,
            end_time=end_time,
            title=title,
            description=description
        )
        
        logger.info(f"Uploading direct clip {clip.id} to Bunny")
        
        # Sauvegarder temporairement le fichier
        import tempfile
        import os
        from datetime import datetime
        
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"clip_upload_{datetime.now().timestamp()}.mp4")
        file.save(temp_path)
        
        filename = f"clip_{clip.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        
        # Upload vers Bunny Stream (pour streaming ET téléchargement MP4)
        clip_url, bunny_video_id = manual_clip_service._upload_to_bunny(temp_path, filename)
        logger.info(f"✅ Uploaded to Bunny Stream: {clip_url}")
        
        # ⚠️ Bunny Storage désactivé - On utilise uniquement Bunny Stream (comme les vidéos)
        # Les téléchargements MP4 se font via Bunny Stream: /clips/{id}/download → play_720p.mp4
        
        # Mettre à jour le clip avec l'URL Bunny Stream
        clip.file_url = clip_url  # Bunny Stream (HLS + MP4)
        clip.bunny_video_id = bunny_video_id  # GUID Bunny Stream (pour URL MP4)
        clip.storage_download_url = None  # Pas de Bunny Storage
        clip.status = 'completed'
        clip.completed_at = datetime.utcnow()
        
        # Créer une notification pour informer l'utilisateur
        Notification.create_notification(
            user_id=current_user.id,
            notification_type=NotificationType.VIDEO_READY,
            title="🎬 Votre clip est prêt !",
            message=f"Le clip '{clip.title}' a été créé avec succès et est maintenant disponible.",
            link=f"/dashboard?tab=clips"
        )
        
        db.session.commit()
        
        # Nettoyer fichier temp
        try:
            os.remove(temp_path)
        except:
            pass
        
        logger.info(f"✅ Clip {clip.id} uploaded successfully")
        
        return jsonify({
            'success': True,
            'clip': clip.to_dict(),
            'message': 'Clip uploaded successfully'
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error uploading clip: {e}")
        import traceback
        traceback_str = traceback.format_exc()
        logger.error(traceback_str)
        return jsonify({'error': 'Internal server error', 'details': str(e), 'trace': traceback_str}), 500

@clip_bp.route('/<int:clip_id>', methods=['GET'])
@login_required
def get_clip(current_user, clip_id):
    """Récupère les détails d'un clip"""
    try:
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            return jsonify({'error': 'Clip not found'}), 404
        
        # Vérifier que l'utilisateur a accès (propriétaire ou vidéo partagée)
        if clip.user_id != current_user.id:
            # TODO: vérifier si la vidéo est partagée avec l'utilisateur
            return jsonify({'error': 'Access denied'}), 403
        
        return jsonify(clip.to_dict()), 200
        
    except Exception as e:
        logger.error(f"Error getting clip: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@clip_bp.route('/video/<int:video_id>', methods=['GET'])
@login_required
def get_video_clips(current_user, video_id):
    """Liste tous les clips d'une vidéo"""
    try:
        # Vérifier que l'utilisateur a accès à cette vidéo
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Video not found'}), 404
        
        if video.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        clips = manual_clip_service.get_user_clips(
            user_id=current_user.id,
            video_id=video_id
        )
        
        return jsonify({
            'clips': [clip.to_dict() for clip in clips]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting video clips: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@clip_bp.route('/my-clips', methods=['GET'])
@login_required
def get_my_clips(current_user):
    """Liste tous les clips de l'utilisateur"""
    try:
        clips = manual_clip_service.get_user_clips(user_id=current_user.id)
        
        return jsonify({
            'clips': [clip.to_dict() for clip in clips]
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting user clips: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@clip_bp.route('/<int:clip_id>', methods=['DELETE'])
@login_required
def delete_clip(current_user, clip_id):
    """Supprime un clip"""
    try:
        manual_clip_service.delete_clip(clip_id, current_user.id)
        
        return jsonify({
            'success': True,
            'message': 'Clip deleted successfully'
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error deleting clip: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@clip_bp.route('/<int:clip_id>/share', methods=['POST'])
@login_required
def get_share_links(current_user, clip_id):
    """
    Génère les liens de partage pour un clip
    
    Body JSON (optionnel):
    {
        "platform": "whatsapp"  // Pour tracker le partage sur une plateforme spécifique
    }
    """
    try:
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            return jsonify({'error': 'Clip not found'}), 404
        
        # Vérifier que l'utilisateur a accès
        if clip.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        # Générer les liens
        links = social_share_service.generate_share_links(clip_id)
        
        # Tracker le partage si une plateforme est spécifiée
        data = request.get_json() or {}
        if 'platform' in data:
            social_share_service.track_share(clip_id, data['platform'])
        
        return jsonify({
            'success': True,
            'share_links': links,
            'instagram_instructions': social_share_service.generate_instagram_instructions(),
            'tiktok_instructions': social_share_service.generate_tiktok_instructions()
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error generating share links: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@clip_bp.route('/<int:clip_id>/download', methods=['GET'])
@login_required
def download_clip(current_user, clip_id):
    """
    Télécharge un clip en MP4 - redirection directe vers Bunny Stream CDN (comme les vidéos)
    """
    try:
        from flask import redirect
        from src.services.bunny_mp4_url_helper import get_mp4_url_helper
        
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            return jsonify({'error': 'Clip not found'}), 404
        
        # Vérifier les permissions
        if clip.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        # Vérifier que le clip est complété et a un bunny_video_id
        if clip.status != 'completed':
            return jsonify({
                'error': 'Clip not ready',
                'message': 'This clip is still being processed. Please try again later.'
            }), 404
        
        if not clip.bunny_video_id:
            return jsonify({
                'error': 'Clip not available for download',
                'message': 'This clip was not uploaded to Bunny Stream.'
            }), 404
        
        # Incrémenter le compteur de téléchargements
        clip.download_count += 1
        db.session.commit()
        
        # Générer l'URL MP4 depuis Bunny Stream (comme les vidéos)
        try:
            mp4_helper = get_mp4_url_helper()
            mp4_url = mp4_helper.get_mp4_download_url(clip.bunny_video_id, resolution='720p')
            
            logger.info(f"✅ Redirection téléchargement clip {clip_id} → {mp4_url}")
            
            # Redirection 302 directe vers Bunny Stream CDN (comme les vidéos)
            return redirect(mp4_url, code=302)
            
        except ValueError as e:
            logger.error(f"❌ Erreur génération URL MP4 pour clip {clip_id}: {e}")
            return jsonify({
                'error': f'Error generating download URL: {str(e)}',
                'status': 500
            }), 500
        
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement clip {clip_id}: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@clip_bp.route('/<int:clip_id>/download', methods=['POST'])
@login_required
def track_download(current_user, clip_id):
    """Enregistre un téléchargement (legacy endpoint for tracking)"""
    try:
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            return jsonify({'error': 'Clip not found'}), 404
        
        if clip.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
        
        social_share_service.track_download(clip_id)
        
        return jsonify({
            'success': True,
            'download_url': clip.storage_download_url or clip.file_url  # Fallback to stream URL
        }), 200
        
    except Exception as e:
        logger.error(f"Error tracking download: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@clip_bp.route('/<int:clip_id>/meta', methods=['GET'])
def get_clip_meta(clip_id):
    """Récupère les meta tags Open Graph pour un clip (public)"""
    try:
        meta = social_share_service.generate_open_graph_meta(clip_id)
        
        return jsonify({
            'success': True,
            'meta': meta
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Error getting clip meta: {e}")
        return jsonify({'error': 'Internal server error'}), 500
