"""
Service pour créer des clips vidéo manuellement
Utilise FFmpeg pour découper les vidéos et Bunny CDN pour le stockage
"""

import os
import subprocess
import tempfile
import logging
from datetime import datetime
from typing import Dict, Optional
from src.models.database import db
from src.models.user import UserClip, Video
from src.config.bunny_config import BUNNY_CONFIG
import requests

logger = logging.getLogger(__name__)


class ManualClipService:
    """Service pour gérer la création manuelle de clips vidéo"""
    
    def __init__(self):
        self.temp_dir = tempfile.gettempdir()
    
    def _get_bunny_config(self):
        """Charge la config Bunny depuis la DB (comme bunny_storage_service)"""
        try:
            from src.models.system_configuration import SystemConfiguration
            config = SystemConfiguration.get_bunny_cdn_config()  # ✅ Correct method name
            
            # Vérifier si l'API key est valide (non chiffrée)
            api_key = config.get('api_key', '') if config else ''
            
            # Une API key Bunny valide fait ~40-60 chars
            # Si >100 = probablement chiffrée → rejeter
            if api_key and len(api_key) < 100:
                logger.info(f"✅ Using Bunny config from DB (api_key length: {len(api_key)})")
                return config
            else:
                if api_key:
                    logger.warning(f"⚠️ DB API key too long ({len(api_key)} chars), likely encrypted. Using fallback")
        except Exception as e:
            logger.warning(f"Could not load Bunny config from DB: {e}")
        
        # Fallback : utiliser BunnyConfig qui charge depuis .env AVEC fallback hardcodé
        from src.config.bunny_config import BunnyConfig
        fallback_config = BunnyConfig.load_config()
        
        api_key_len = len(fallback_config.get('api_key', ''))
        logger.info(f"✅ Using Bunny config from BunnyConfig fallback (api_key length: {api_key_len})")
        return fallback_config
    
    def create_clip(
        self,
        video_id: int,
        user_id: int,
        start_time: float,
        end_time: float,
        title: str,
        description: Optional[str] = None
    ) -> UserClip:
        """
        Crée un clip à partir d'une vidéo existante
        
        Args:
            video_id: ID de la vidéo source
            user_id: ID de l'utilisateur créant le clip
            start_time: Temps de début en secondes
            end_time: Temps de fin en secondes
            title: Titre du clip
            description: Description optionnelle
        
        Returns:
            UserClip: Le clip créé
        """
        # Vérifier que la vidéo existe
        video = Video.query.get(video_id)
        if not video:
            raise ValueError("Video not found")
        
        # Pas de restriction - tous les utilisateurs peuvent créer des clips
        
        # Valider les timestamps
        if start_time < 0 or end_time <= start_time:
            raise ValueError("Invalid time range")
        
        if video.duration and end_time > video.duration:
            raise ValueError(f"End time exceeds video duration ({video.duration}s)")
        
        # Créer l'enregistrement du clip
        clip = UserClip(
            video_id=video_id,
            user_id=user_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            duration=int(end_time - start_time),
            status='pending'
        )
        
        db.session.add(clip)
        db.session.commit()
        
        logger.info(f"Created clip {clip.id} for video {video_id}")
        
        return clip
    
    def process_clip(self, clip_id: int) -> bool:
        """
        Traite un clip: télécharge la vidéo source, découpe, upload
        
        Args:
            clip_id: ID du clip à traiter
        
        Returns:
            bool: True si succès, False sinon
        """
        clip = UserClip.query.get(clip_id)
        if not clip:
            logger.error(f"Clip {clip_id} not found")
            return False
        
        try:
            clip.status = 'processing'
            db.session.commit()
            
            video = clip.video
            
            if not video.bunny_video_id:
                raise ValueError("Source video must have a Bunny video ID")
            
            config = self._get_bunny_config()
            
            logger.info(f"Creating clip from Bunny video: {video.bunny_video_id}")
            logger.info(f"Cutting from {clip.start_time}s to {clip.end_time}s")
            
            # Télécharger la vidéo source via API (utilise méthode existante)
            source_path = self._download_bunny_video(video.bunny_video_id)
            
            # Découper localement
            duration = clip.end_time - clip.start_time
            clip_path = self._cut_video_local(source_path, clip.start_time, clip.end_time)
            
            # Générer miniature
            logger.info("Generating thumbnail")
            thumbnail_path = self._generate_thumbnail(clip_path)
            
            # Upload vers Bunny
            logger.info("Uploading clip to Bunny CDN")
            clip_url, bunny_video_id = self._upload_to_bunny(
                clip_path,
                f"clip_{clip.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            )
            
            # Mettre à jour le clip
            clip.file_url = clip_url
            clip.thumbnail_url = thumbnail_path  # Ou None si upload thumbnail pas implémenté
            clip.bunny_video_id = bunny_video_id
            clip.status = 'completed'
            clip.completed_at = datetime.utcnow()
            db.session.commit()
            
            # Nettoyer fichiers temp
            self._cleanup_files([clip_path, thumbnail_path])
            
            logger.info(f"Clip {clip_id} processed successfully (optimized streaming)")
            return True
            
        except Exception as e:
            logger.error(f"Error processing clip {clip_id}: {str(e)}")
            clip.status = 'failed'
            clip.error_message = str(e)
            db.session.commit()
            return False
    
    def _download_bunny_video(self, video_id: str) -> str:
        """
        Télécharge une vidéo depuis Bunny Stream via l'API
        Utilise l'API Key pour l'authentification (pas de 403)
        """
        # 1. Récupérer les informations de la vidéo via l'API
        config = self._get_bunny_config()
        api_url = f"https://video.bunnycdn.com/library/{config['library_id']}/videos/{video_id}"
        headers = {'AccessKey': config['api_key']}
        
        logger.info(f"Fetching video info from Bunny API: {video_id}")
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        
        video_info = response.json()
        
        # 2. Construire l'URL de téléchargement MP4
        # Bunny Stream stocke les vidéos encodées, on prend la meilleure qualité
        # L'URL de téléchargement direct nécessite l'API key
        download_url = f"https://video.bunnycdn.com/library/{config['library_id']}/videos/{video_id}/mp4/original"
        
        logger.info(f"Downloading video from Bunny API")
        
        # 3. Télécharger avec l'API key dans les headers
        response = requests.get(download_url, headers=headers, stream=True)
        response.raise_for_status()
        
        # 4. Sauvegarder dans un fichier temporaire
        temp_file = os.path.join(self.temp_dir, f"source_{datetime.now().timestamp()}.mp4")
        
        with open(temp_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"Downloaded Bunny video to {temp_file}")
        return temp_file
    
    def _download_video(self, url: str) -> str:
        """Télécharge une vidéo depuis une URL (fallback pour URLs non-Bunny)"""
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        temp_file = os.path.join(self.temp_dir, f"source_{datetime.now().timestamp()}.mp4")
        
        with open(temp_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return temp_file
    
    def _cut_video_from_bunny_api(self, video_id: str, start_time: float, end_time: float, config: dict) -> str:
        """
        Télécharge vidéo via API Bunny (avec auth) puis découpe
        ✅ Résout 403 Forbidden
        """
        output_path = os.path.join(self.temp_dir, f"clip_{datetime.now().timestamp()}.mp4")
        
        # Télécharger via API - URL CORRECTE pour MP4 complet
        logger.info(f"Downloading from Bunny API: {video_id}")
        download_url = f"https://video.bunnycdn.com/library/{config['library_id']}/videos/{video_id}/mp4/original"
        
        headers = {'AccessKey': config['api_key']}
        response = requests.get(download_url, headers=headers, stream=True)
        response.raise_for_status()
        
        temp_source = os.path.join(self.temp_dir, f"source_{datetime.now().timestamp()}.mp4")
        
        with open(temp_source, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"Downloaded source ({os.path.getsize(temp_source)} bytes), cutting clip...")
        
        # Découper
        duration = end_time - start_time
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start_time),
            '-i', temp_source,
            '-t', str(duration),
            '-c', 'copy',
            '-movflags', '+faststart',
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            # Fallback ré-encodage
            logger.warning("FFmpeg copy failed, trying re-encode...")
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(start_time),
                '-i', temp_source,
                '-t', str(duration),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-c:a', 'aac',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        
        # Nettoyer
        try:
            os.remove(temp_source)
            logger.debug(f"Cleaned up {temp_source}")
        except:
            pass
        
        return output_path
    
    def _cut_video_from_url(self, source_url: str, start_time: float, end_time: float) -> str:
        """
        Découpe une vidéo DIRECTEMENT depuis une URL Bunny
        ✅ OPTIMISÉ : Ne télécharge QUE la portion nécessaire
        ✅ Utilise -ss AVANT -i pour seek rapide côté serveur
        """
        output_path = os.path.join(
            self.temp_dir,
            f"clip_{datetime.now().timestamp()}.mp4"
        )
        
        duration = end_time - start_time
        
        # Commande FFmpeg optimale
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite
            '-ss', str(start_time),  # ❗ AVANT -i = seek rapide
            '-i', source_url,  # URL directe
            '-t', str(duration),  # Durée exacte
            '-c', 'copy',  # Pas de ré-encodage
            '-movflags', '+faststart',  # Optimisation web
            '-avoid_negative_ts', 'make_zero',
            output_path
        ]
        
        logger.info(f"FFmpeg streaming clip: {duration}s from {source_url}")
        logger.debug(f"Command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            
            # Fallback: Si -c copy échoue, ré-encoder
            logger.warning("Trying with re-encoding fallback...")
            cmd_reencode = [
                'ffmpeg',
                '-y',
                '-ss', str(start_time),
                '-i', source_url,
                '-t', str(duration),
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-c:a', 'aac',
                '-movflags', '+faststart',
                output_path
            ]
            
            result = subprocess.run(cmd_reencode, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg failed (even with re-encode): {result.stderr}")
        
        return output_path
    
    def _generate_thumbnail(self, video_path: str) -> str:
        """Génère une miniature à partir de la vidéo"""
        thumbnail_path = os.path.join(
            self.temp_dir,
            f"thumb_{datetime.now().timestamp()}.jpg"
        )
        
        # Extraire une frame à 1 seconde
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-ss', '1',
            '-vframes', '1',
            '-q:v', '2',  # Qualité
            thumbnail_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.warning(f"Thumbnail generation failed: {result.stderr}")
            # Utiliser une image par défaut
            thumbnail_path = None
        
        return thumbnail_path
    
    def _upload_to_bunny(self, file_path: str, filename: str) -> tuple:
        """
        Upload une vidéo vers Bunny Stream
        
        Returns:
            tuple: (url, video_id)
        """
        # Pour Bunny Stream, on utilise leur API d'upload
        # Documentation: https://docs.bunny.net/reference/video_createvideo
        
        config = self._get_bunny_config()
        url = f"https://video.bunnycdn.com/library/{config['library_id']}/videos"
        
        # 1. Créer la vidéo
        headers = {
            'AccessKey': config['api_key'],
            'Content-Type': 'application/json'
        }
        
        data = {
            'title': filename
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        
        video_data = response.json()
        video_id = video_data['guid']
        
        # 2. Upload le fichier
        upload_url = f"https://video.bunnycdn.com/library/{config['library_id']}/videos/{video_id}"
        
        with open(file_path, 'rb') as f:
            upload_response = requests.put(
                upload_url,
                headers={'AccessKey': config['api_key']},
                data=f
            )
            upload_response.raise_for_status()
        
        # 3. Construire l'URL de lecture
        video_url = f"https://{config['cdn_hostname']}/{video_id}/playlist.m3u8"
        
        return video_url, video_id
    
    def _upload_thumbnail_to_bunny(self, file_path: str, filename: str) -> Optional[str]:
        """Upload une miniature vers Bunny Storage"""
        if not file_path:
            return None
        
        # Pour simplifier, on peut utiliser le storage Bunny ou générer l'URL depuis Stream
        # Ici on retourne None pour l'instant, Bunny Stream génère automatiquement des thumbnails
        return None
    
    def _cleanup_files(self, file_paths: list):
        """Nettoie les fichiers temporaires"""
        for path in file_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    logger.debug(f"Cleaned up {path}")
            except Exception as e:
                logger.warning(f"Could not delete {path}: {e}")
    
    def delete_clip(self, clip_id: int, user_id: int) -> bool:
        """
        Supprime un clip
        
        Args:
            clip_id: ID du clip à supprimer
            user_id: ID de l'utilisateur (pour vérification)
        
        Returns:
            bool: True si succès
        """
        clip = UserClip.query.get(clip_id)
        
        if not clip:
            raise ValueError("Clip not found")
        
        if clip.user_id != user_id:
            raise ValueError("User does not own this clip")
        
        # Supprimer de Bunny CDN si le fichier existe
        if clip.bunny_video_id:
            try:
                self._delete_from_bunny(clip.bunny_video_id)
            except Exception as e:
                logger.warning(f"Could not delete from Bunny: {e}")
        
        # Supprimer de la base de données
        db.session.delete(clip)
        db.session.commit()
        
        logger.info(f"Deleted clip {clip_id}")
        return True
    
    def _delete_from_bunny(self, video_id: str):
        """Supprime une vidéo de Bunny Stream"""
        config = self._get_bunny_config()
        url = f"https://video.bunnycdn.com/library/{config['library_id']}/videos/{video_id}"
        
        response = requests.delete(
            url,
            headers={'AccessKey': config['api_key']}
        )
        response.raise_for_status()
    
    def get_user_clips(self, user_id: int, video_id: Optional[int] = None) -> list:
        """
        Récupère les clips d'un utilisateur
        
        Args:
            user_id: ID de l'utilisateur
            video_id: Optionnel, filtrer par vidéo
        
        Returns:
            list: Liste des clips
        """
        query = UserClip.query.filter_by(user_id=user_id)
        
        if video_id:
            query = query.filter_by(video_id=video_id)
        
        return query.order_by(UserClip.created_at.desc()).all()


# Instance globale
manual_clip_service = ManualClipService()
