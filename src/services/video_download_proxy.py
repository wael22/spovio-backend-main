"""
Route proxy pour télécharger des vidéos depuis Bunny Stream.
"""
from flask import Response, stream_with_context
import requests
import logging
import os

logger = logging.getLogger(__name__)


def download_video_proxy(video_id, user, video, api_response):
    """
    Proxy pour télécharger une vidéo depuis Bunny Stream.
    
    Args:
        video_id: ID de la vidéo
        user: Utilisateur courant
        video: Objet Video depuis la DB
        api_response: Fonction pour les réponses API
    
    Returns:
        Response Flask avec le stream vidéo
    """
    # Vérifier les permissions
    if video.user_id != user.id and not video.is_unlocked:
        return api_response(error='Accès non autorisé', status=403)
    
    # Vérifier que la vidéo a une URL
    if not video.file_url:
        return api_response(error='Vidéo non disponible pour téléchargement', status=404)
    
    # Nom du fichier pour le téléchargement
    filename = f"{video.title}.mp4" if video.title else f"video-{video_id}.mp4"
    
    try:
        # Pour Bunny Stream, utiliser l'API pour obtenir l'URL MP4
        bunny_api_key = os.environ.get('BUNNY_API_KEY')
        library_id = os.environ.get('BUNNY_LIBRARY_ID', '579861')
        
        download_url = None
        video_guid = video.bunny_video_id
        
        # Si bunny_video_id n'est pas défini, essayer de l'extraire de file_url
        if not video_guid and video.file_url:
            import re
            match = re.search(r'/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/', video.file_url)
            if match:
                video_guid = match.group(1)
                logger.info(f"📥 GUID extrait de file_url: {video_guid}")
        
        # Essayer d'obtenir l'URL MP4 via l'API Bunny Stream
        if video_guid and library_id:
            try:
                api_url = f"https://video.bunnycdn.com/library/{library_id}/videos/{video_guid}"
                headers = {}
                if bunny_api_key:
                    headers['AccessKey'] = bunny_api_key
                
                logger.info(f"🔍 Récupération métadonnées vidéo depuis API Bunny: {video_guid}")
                response = requests.get(api_url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    video_data = response.json()
                    
                    # Chercher l'URL MP4 dans les métadonnées
                    # Bunny Stream stocke l'URL MP4 dans 'mp4Url' ou on peut construire depuis le CDN
                    if video_data.get('mp4Url'):
                        download_url = video_data['mp4Url']
                        logger.info(f"✅ URL MP4 trouvée: {download_url}")
                    else:
                        # Alternative: utiliser l'URL du CDN de livraison avec le GUID
                        # Format possible: https://vz-{pull_zone}.b-cdn.net/{guid}/play_720p.mp4
                        logger.warning(f"⚠️ Pas d'URL MP4 directe, tentative avec HLS master")
                        # Pour l'instant, retourner une erreur car pas d'URL MP4
                        logger.error(f"❌ Bunny Stream ne fournit pas d'URL MP4 pour: {video_guid}")
                        logger.error(f"   Métadonnées reçues: {list(video_data.keys())}")
                        return api_response(
                            error='Cette vidéo n\'est disponible qu\'en streaming. Le téléchargement direct n\'est pas supporté.',
                            status=400
                        )
                else:
                    logger.error(f"❌ Erreur API Bunny ({response.status_code}): {response.text[:200]}")
            except Exception as e:
                logger.error(f"❌ Erreur récupération métadonnées Bunny: {e}")
        
        # Fallback: utiliser file_url si disponible et que ce n'est pas HLS
        if not download_url and video.file_url and not video.file_url.endswith('.m3u8'):
            download_url = video.file_url
            logger.info(f"📥 Téléchargement depuis file_url: {video.file_url}")
        
        if not download_url:
            logger.error(f"❌ Aucune URL de téléchargement valide pour vidéo {video_id}")
            logger.error(f"   - bunny_video_id: {video.bunny_video_id}")
            logger.error(f"   - file_url: {video.file_url}")
            return api_response(
                error='Vidéo non disponible pour téléchargement. Utilisez le lecteur pour regarder la vidéo.',
                status=404
            )
        
        # Stream la vidéo depuis l'URL trouvée
        def generate():
            with requests.get(download_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        
        logger.info(f"✅ Démarrage téléchargement vidéo {video_id}: {filename}")
        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"',
                'Content-Type': 'video/mp4',
            }
        )
    except requests.RequestException as e:
        logger.error(f"❌ Erreur téléchargement vidéo {video_id}: {e}")
        return api_response(error='Erreur lors du téléchargement de la vidéo', status=500)
    except Exception as e:
        logger.error(f"❌ Erreur inattendue téléchargement {video_id}: {e}")
        return api_response(error='Erreur serveur', status=500)
