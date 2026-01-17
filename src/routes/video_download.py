@videos_bp.route('/download/<int:video_id>', methods=['GET'])
@login_required
def download_video(video_id):
    '''Télécharge une vidéo.'''
    from flask import redirect
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier les permissions
    if video.user_id != user.id and not video.is_unlocked:
        return api_response(error='Accès non autorisé', status=403)
    
    # Rediriger vers le fichier sur Bunny CDN
    if video.file_url:
        return redirect(video.file_url)
    else:
        return api_response(error='Fichier vidéo non disponible', status=404)

