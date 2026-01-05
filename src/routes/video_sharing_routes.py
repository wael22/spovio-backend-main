"""
Routes pour le partage de vidéos entre utilisateurs
"""
from flask import Blueprint, request, jsonify, session
from src.models.user import db, User, Video, SharedVideo
from functools import wraps
import logging

logger = logging.getLogger(__name__)
video_sharing_bp = Blueprint('video_sharing', __name__)

# Helper: Login required
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return wrapper

def get_current_user():
    """Récupère l'utilisateur courant depuis la session"""
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def api_response(data=None, message=None, status=200, error=None):
    """Format de réponse API standardisé"""
    resp = {}
    if data is not None:
        resp.update(data)
    if message:
        resp['message'] = message
    if error:
        resp['error'] = error
    return jsonify(resp), status

# ================= ENDPOINTS DE PARTAGE =================

@video_sharing_bp.route('/<int:video_id>/share-with-user', methods=['POST'])
@login_required
def share_video_with_user(video_id):
    """Partager une vidéo avec un utilisateur par email"""
    current_user = get_current_user()
    
    # Récupérer les données de la requête
    data = request.get_json() or {}
    recipient_email = (data.get('recipient_email') or '').strip()
    message_raw = data.get('message') or ''
    message = message_raw.strip() if message_raw else None
    
    # Validation
    if not recipient_email:
        return api_response(error='Email du destinataire requis', status=400)
    
    # Vérifier que la vidéo existe et appartient à l'utilisateur
    video = Video.query.get(video_id)
    if not video:
        return api_response(error='Vidéo non trouvée', status=404)
    
    if video.user_id != current_user.id:
        return api_response(error='Vous ne pouvez partager que vos propres vidéos', status=403)
    
    # Trouver l'utilisateur destinataire par email
    recipient = User.query.filter_by(email=recipient_email).first()
    if not recipient:
        return api_response(error=f'Aucun utilisateur trouvé avec l\'email {recipient_email}', status=404)
    
    # Vérifier qu'on ne partage pas avec soi-même
    if recipient.id == current_user.id:
        return api_response(error='Vous ne pouvez pas partager une vidéo avec vous-même', status=400)
    
    # Vérifier si la vidéo n'est pas déjà partagée avec cet utilisateur
    existing_share = SharedVideo.query.filter_by(
        video_id=video_id,
        shared_with_user_id=recipient.id
    ).first()
    
    if existing_share:
        return api_response(error='Cette vidéo est déjà partagée avec cet utilisateur', status=400)
    
    # Créer le partage
    try:
        shared_video = SharedVideo(
            video_id=video_id,
            owner_user_id=current_user.id,
            shared_with_user_id=recipient.id,
            message=message
        )
        db.session.add(shared_video)
        
        # Créer une notification pour le destinataire
        from src.models.notification import Notification, NotificationType
        try:
            notification = Notification(
                user_id=recipient.id,
                title='Nouvelle vidéo partagée',
                message=f'{current_user.name} a partagé une vidéo avec vous: "{video.title}"',
                notification_type=NotificationType.VIDEO,
                link=None
            )
            db.session.add(notification)
            logger.info(f"[NOTIF DEBUG] Notification créée pour user_id={recipient.id}, email={recipient.email}")
        except Exception as notif_error:
            logger.error(f"[NOTIF ERROR] Erreur lors de la création de notification: {notif_error}")
            import traceback
            logger.error(traceback.format_exc())
            # Ne pas bloquer le partage si la notification échoue
        
        db.session.commit()
        
        logger.info(f"Vidéo {video_id} partagée par {current_user.email} avec {recipient.email}")
        
        return api_response(
            data={'shared_video': shared_video.to_dict()},
            message=f'Vidéo partagée avec succès avec {recipient.name}',
            status=201
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du partage de vidéo: {e}")
        return api_response(error='Erreur lors du partage de la vidéo', status=500)


@video_sharing_bp.route('/shared-with-me', methods=['GET'])
@login_required
def get_shared_with_me():
    """Récupérer toutes les vidéos partagées avec l'utilisateur courant"""
    current_user = get_current_user()
    
    try:
        shared_videos = SharedVideo.query.filter_by(
            shared_with_user_id=current_user.id
        ).order_by(SharedVideo.shared_at.desc()).all()
        
        return api_response({
            'shared_videos': [sv.to_dict() for sv in shared_videos],
            'total': len(shared_videos)
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos partagées: {e}")
        return api_response(error='Erreur lors de la récupération des vidéos partagées', status=500)


@video_sharing_bp.route('/shared/<int:shared_video_id>', methods=['DELETE'])
@login_required
def remove_shared_access(shared_video_id):
    """Supprimer l'accès partagé à une vidéo"""
    current_user = get_current_user()
    
    # Trouver le partage
    shared_video = SharedVideo.query.get(shared_video_id)
    if not shared_video:
        return api_response(error='Partage non trouvé', status=404)
    
    # Vérifier que l'utilisateur est soit le propriétaire, soit le destinataire
    if shared_video.owner_user_id != current_user.id and shared_video.shared_with_user_id != current_user.id:
        return api_response(error='Vous n\'êtes pas autorisé à supprimer ce partage', status=403)
    
    try:
        db.session.delete(shared_video)
        db.session.commit()
        
        logger.info(f"Partage {shared_video_id} supprimé par l'utilisateur {current_user.id}")
        
        return api_response(message='Partage supprimé avec succès')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la suppression du partage: {e}")
        return api_response(error='Erreur lors de la suppression du partage', status=500)


@video_sharing_bp.route('/my-shared-videos', methods=['GET'])
@login_required
def get_my_shared_videos():
    """Récupérer toutes les vidéos que l'utilisateur a partagées avec d'autres"""
    current_user = get_current_user()
    
    try:
        shared_videos = SharedVideo.query.filter_by(
            owner_user_id=current_user.id
        ).order_by(SharedVideo.shared_at.desc()).all()
        
        return api_response({
            'shared_videos': [sv.to_dict() for sv in shared_videos],
            'total': len(shared_videos)
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos partagées: {e}")
        return api_response(error='Erreur lors de la récupération des vidéos partagées', status=500)
