"""
Module vidéos (nettoyé). Les endpoints start/stop internes sont dépréciés.
Utiliser /api/recording/start et /api/recording/stop.
"""
from flask import Blueprint, request, jsonify, session
from src.models.user import db, User, Video, Court, Club
from functools import wraps
import logging

logger = logging.getLogger(__name__)
videos_bp = Blueprint('videos', __name__)

# Helpers

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'user_id' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*a, **k)
    return w


def get_current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None


def api_response(data=None, message=None, status=200, error=None):
    resp = {}
    if data is not None:
        resp.update(data)
    if message:
        resp['message'] = message
    if error:
        resp['error'] = error
    return jsonify(resp), status

# ================= Vidéos =================
@videos_bp.route('/my-videos', methods=['GET'])
@login_required
def my_videos():
    from src.models.user import SharedVideo
    user = get_current_user()
    
    # Vidéos possédées par l'utilisateur
    owned_videos = Video.query.filter_by(user_id=user.id).order_by(Video.recorded_at.desc()).all()
    
    # Vidéos partagées avec l'utilisateur
    shared_with_me = SharedVideo.query.filter_by(shared_with_user_id=user.id).order_by(SharedVideo.shared_at.desc()).all()
    
    # Combiner les vidéos
    videos_list = []
    
    # Ajouter les vidéos possédées
    for v in owned_videos:
        video_data = v.to_dict()  # ✅ Utiliser to_dict() pour avoir tous les champs
        video_data['is_shared'] = False  # Ajouter le champ is_shared
        videos_list.append(video_data)
    
    # Ajouter les vidéos partagées
    for sv in shared_with_me:
        if sv.video:  # Vérifier que la vidéo existe toujours
            video_data = sv.video.to_dict()  # ✅ Utiliser to_dict() pour avoir tous les champs
            video_data['is_shared'] = True  # C'est une vidéo partagée
            video_data['shared_by'] = sv.owner.name if sv.owner else 'Inconnu'
            video_data['shared_at'] = sv.shared_at.isoformat() if sv.shared_at else None
            video_data['shared_message'] = sv.message
            video_data['shared_video_id'] = sv.id  # Pour pouvoir supprimer le partage
            videos_list.append(video_data)
    
    return api_response({'videos': videos_list})



@videos_bp.route('/<int:video_id>', methods=['GET'])
@login_required
def get_video(video_id):
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    if video.user_id != user.id and not video.is_unlocked:
        return api_response(error='Accès non autorisé', status=403)
    return api_response({'video': video.to_dict()})


@videos_bp.route('/<int:video_id>', methods=['PUT'])
@login_required
def update_video(video_id):
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    if video.user_id != user.id:
        return api_response(error='Accès non autorisé', status=403)
    data = request.get_json() or {}
    if 'title' in data:
        video.title = data['title']
    if 'description' in data:
        video.description = data['description']
    db.session.commit()
    return api_response({'video': video.to_dict()}, 'Vidéo mise à jour')


@videos_bp.route('/<int:video_id>', methods=['DELETE'])
@login_required
def delete_video(video_id):
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    if video.user_id != user.id:
        return api_response(error='Accès non autorisé', status=403)
    db.session.delete(video)
    db.session.commit()
    return api_response(message='Vidéo supprimée')


@videos_bp.route('/<int:video_id>/share', methods=['POST'])
@login_required
def share_video(video_id):
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    if video.user_id != user.id:
        return api_response(error='Accès non autorisé', status=403)
    if not video.is_unlocked:
        return api_response(error='Vidéo verrouillée', status=400)
    base = request.host_url
    video_url = f"{base}videos/{video_id}/watch"
    share = {
        'facebook': f"https://www.facebook.com/sharer/sharer.php?u={video_url}",
        'instagram': video_url,
        'youtube': video_url,
        'direct': video_url
    }
    return api_response({'share_urls': share, 'video_url': video_url}, 'Liens générés')

@videos_bp.route('/<int:video_id>/download', methods=['GET'])
@login_required
def download_video(video_id):
    """Télécharge une vidéo via redirection directe vers Bunny CDN MP4."""
    from src.services.bunny_mp4_url_helper import get_mp4_url_helper
    from flask import redirect, request as flask_request
    
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier les permissions
    if video.user_id != user.id and not video.is_unlocked:
        return api_response(error='Accès non autorisé', status=403)
    
    # Vérifier que la vidéo a un bunny_video_id
    if not video.bunny_video_id:
        return api_response(
            error='Vidéo non disponible pour téléchargement. Cette vidéo n\'a pas été uploadée sur Bunny Stream.',
            status=404
        )
    
    # Vérifier que la vidéo n'est pas expirée/supprimée du cloud
    if video.cloud_deleted_at:
        return api_response(
            error='Cette vidéo a été supprimée du cloud et n\'est plus disponible pour téléchargement.',
            status=410  # Gone
        )
    
    # Récupérer la résolution demandée (par défaut 720p)
    resolution = flask_request.args.get('resolution', '720p')
    
    # Générer l'URL MP4 directe
    try:
        mp4_helper = get_mp4_url_helper()
        mp4_url = mp4_helper.get_mp4_download_url(video.bunny_video_id, resolution)
        
        logger.info(f"✅ Redirection téléchargement vidéo {video_id} → {resolution}: {mp4_url}")
        
        # Redirection 302 temporaire vers l'URL MP4 sur Bunny CDN
        return redirect(mp4_url, code=302)
        
    except ValueError as e:
        logger.error(f"❌ Erreur génération URL MP4 pour vidéo {video_id}: {e}")
        return api_response(
            error=f'Erreur lors de la génération de l\'URL de téléchargement: {str(e)}',
            status=500
        ) 

@videos_bp.route('/<int:video_id>/watch', methods=['GET'])
def watch_video(video_id):
    video = Video.query.get_or_404(video_id)
    if not video.is_unlocked:
        return api_response(error='Vidéo non disponible', status=403)
    stream = video.file_url or f"/api/videos/stream/video_{video_id}.mp4"
    return api_response({'video': {
        'id': video.id,
        'title': video.title,
        'description': video.description,
        'file_url': stream,
        'thumbnail_url': video.thumbnail_url,
        'duration': video.duration,
        'recorded_at': video.recorded_at.isoformat() if video.recorded_at else None
    }})


# Courts
@videos_bp.route('/courts/available', methods=['GET'])
@login_required
def available_courts():
    courts = Court.query.filter_by(is_recording=False).all()
    groups = {}
    for c in courts:
        club = Club.query.get(c.club_id)
        if club:
            groups.setdefault(club.id, {'club': club.to_dict(), 'courts': []})['courts'].append(c.to_dict())
    return api_response({'available_courts': list(groups.values()), 'total_available': len(courts)})


# Deprecated start/stop
@videos_bp.route('/record', methods=['POST'])
@login_required
def deprecated_start():
    return api_response(error='Endpoint remplacé. Utilisez /api/recording/start', status=410)


@videos_bp.route('/stop-recording', methods=['POST'])
@login_required
def deprecated_stop():
    return api_response(error='Endpoint remplacé. Utilisez /api/recording/stop', status=410)


# QR Scan
@videos_bp.route('/qr-scan', methods=['POST'])
@login_required
def scan_qr_code():
    data = request.get_json() or {}
    code = data.get('qr_code')
    if not code:
        return api_response(error='QR code requis', status=400)
    court = Court.query.filter_by(qr_code=code).first()
    if not court:
        return api_response(error='QR code invalide', status=404)
    club = Club.query.get(court.club_id)
    return api_response({'court': court.to_dict(), 'club': club.to_dict() if club else None, 'camera_url': court.camera_url, 'can_record': True}, 'QR scanné')

# Note: Ancien bloc dupliqué supprimé pour éviter conflits.

@videos_bp.route('/<int:video_id>/overlays', methods=['GET'])
def get_video_overlays(video_id):
    """Récupérer les overlays actifs pour une vidéo"""
    video = Video.query.get_or_404(video_id)
    
    # Trouver le club associé à la vidéo via le terrain
    if not video.court or not video.court.club_id:
        return jsonify({'overlays': []}), 200
        
    club = Club.query.get(video.court.club_id)
    if not club:
        return jsonify({'overlays': []}), 200
        
    # Retourner les overlays actifs du club
    # Note: on utilise getattr pour éviter les erreurs si la relation n'est pas encore chargée
    overlays = getattr(club, 'overlays', [])
    active_overlays = [o.to_dict() for o in overlays if o.is_active]
    
    return jsonify({'overlays': active_overlays}), 200
