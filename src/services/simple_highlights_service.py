"""
Simple Highlights Service (Version 1 - Sans IA)
Génère des highlights en extrayant des clips à intervalles réguliers
"""

import os
import requests
import subprocess
from datetime import datetime
from typing import List, Dict, Optional
import json
import logging

from src.models.database import db
from src.models.user import Video, HighlightVideo, HighlightJob
from src.config.highlights_config import HighlightsConfig
from src.services.bunny_storage_service import bunny_storage_service

logger = logging.getLogger(__name__)

class SimpleHighlightsService:
    """Service de génération de highlights simple (sans IA)"""
    
    def __init__(self):
        self.config = HighlightsConfig
        
    def create_highlights_job(self, video_id: int, user_id: int, target_duration: int = 90) -> HighlightJob:
        """Crée un job de génération de highlights"""
        
        # Vérifier que la vidéo existe
        video = Video.query.get(video_id)
        if not video:
            raise ValueError(f"Video {video_id} not found")
        
        # Vérifier qu'il n'y a pas déjà un job en cours
        existing_job = HighlightJob.query.filter_by(
            video_id=video_id,
            status='queued'
        ).first()
        
        if existing_job:
            return existing_job
        
        # Créer le job
        job = HighlightJob(
            video_id=video_id,
            user_id=user_id,
            target_duration=target_duration,
            status='queued'
        )
        
        db.session.add(job)
        db.session.commit()
        
        logger.info(f"✅ Highlight job created: ID={job.id}, Video={video_id}")
        
        return job
    
    def process_highlights(self, job_id: int) -> Optional[HighlightVideo]:
        """Traite un job de highlights (méthode principale)"""
        
        job = HighlightJob.query.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        try:
            # Mettre à jour le statut
            job.status = 'downloading'
            job.started_at = datetime.utcnow()
            job.progress = 10
            db.session.commit()
            
            logger.info(f"🎬 Starting highlight generation for job {job_id}")
            
            # 1. Télécharger la vidéo source
            local_video_path = self._download_video(job)
            job.progress = 30
            db.session.commit()
            
            # 2. Générer les highlights
            job.status = 'processing'
            db.session.commit()
            
            highlight_path = self._generate_simple_highlights(
                local_video_path, 
                job.target_duration
            )
            job.progress = 70
            db.session.commit()
            
            # 3. Créer l'entrée HighlightVideo
            highlight_video = HighlightVideo(
                original_video_id=job.video_id,
                generation_status='processing'
            )
            db.session.add(highlight_video)
            db.session.commit()
            
            # 4. Uploader vers Bunny CDN
            job.status = 'uploading'
            db.session.commit()
            
            self._upload_to_bunny(highlight_video, highlight_path)
            job.progress = 90
            db.session.commit()
            
            # 5. Finaliser
            highlight_video.generation_status = 'completed'
            highlight_video.completed_at = datetime.utcnow()
            
            job.status = 'completed'
            job.progress = 100
            job.completed_at = datetime.utcnow()
            job.highlight_video_id = highlight_video.id
            
            db.session.commit()
            
            # 6. Nettoyer les fichiers temporaires
            self._cleanup_temp_files([local_video_path, highlight_path])
            
            logger.info(f"✅ Highlights generated successfully: Job={job_id}, Highlight={highlight_video.id}")
            
            return highlight_video
            
        except Exception as e:
            logger.error(f"❌ Error generating highlights for job {job_id}: {e}")
            
            job.status = 'failed'
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.session.commit()
            
            raise
    
    def _download_video(self, job: HighlightJob) -> str:
        """Télécharge la vidéo source depuis Bunny CDN"""
        
        video = job.video
        
        if not video.file_url:
            raise ValueError(f"Video {video.id} has no file_url")
        
        logger.info(f"📥 Downloading video from: {video.file_url}")
        
        # Créer le chemin local
        filename = f"source_{job.id}_{video.id}.mp4"
        local_path = os.path.join(self.config.TEMP_DIR, filename)
        
        # Télécharger
        response = requests.get(video.file_url, stream=True, timeout=300)
        response.raise_for_status()
        
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"✅ Video downloaded to: {local_path}")
        
        return local_path
    
    def _generate_simple_highlights(self, video_path: str, target_duration: int) -> str:
        """Génère les highlights en mode simple (extraction à intervalles)"""
        
        logger.info(f"🎞️ Generating simple highlights (target: {target_duration}s)")
        
        # 1. Obtenir la durée de la vidéo
        duration = self._get_video_duration(video_path)
        logger.info(f"  Video duration: {duration}s")
        
        # 2. Calculer les intervalles pour extraire les clips
        clips_count = self.config.SIMPLE_CLIPS_COUNT
        clip_duration = target_duration / clips_count  # ~15s par clip
        interval = duration / clips_count
        
        logger.info(f"  Extracting {clips_count} clips of ~{clip_duration:.1f}s")
        
        # 3. Extraire les clips
        clip_paths = []
        timestamps = []
        
        for i in range(clips_count):
            start_time = i * interval
            
            # Ne pas dépasser la durée de la vidéo
            if start_time + clip_duration > duration:
                break
            
            clip_path = os.path.join(
                self.config.TEMP_DIR,
                f"clip_{i}_{os.path.basename(video_path)}"
            )
            
            # Extraire avec FFmpeg
            self._extract_clip(video_path, start_time, clip_duration, clip_path)
            
            clip_paths.append(clip_path)
            timestamps.append({
                'start': start_time,
                'end': start_time + clip_duration,
                'clip_index': i
            })
        
        # 4. Concaténer les clips
        output_path = os.path.join(
            self.config.TEMP_DIR,
            f"highlights_{os.path.basename(video_path)}"
        )
        
        self._concatenate_clips(clip_paths, output_path)
        
        # 5. Nettoyer les clips individuels
        for clip_path in clip_paths:
            if os.path.exists(clip_path):
                os.remove(clip_path)
        
        logger.info(f"✅ Highlights generated: {output_path}")
        
        return output_path
    
    def _get_video_duration(self, video_path: str) -> float:
        """Obtient la durée d'une vidéo avec FFprobe"""
        
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        duration = float(result.stdout.strip())
        
        return duration
    
    def _extract_clip(self, input_path: str, start: float, duration: float, output_path: str):
        """Extrait un clip avec FFmpeg"""
        
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite
            '-ss', str(start),
            '-i', input_path,
            '-t', str(duration),
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-preset', 'fast',
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
    
    def _concatenate_clips(self, clip_paths: List[str], output_path: str):
        """Concatène plusieurs clips en un seul fichier"""
        
        # Créer le fichier de liste pour FFmpeg
        list_file = os.path.join(self.config.TEMP_DIR, 'concat_list.txt')
        
        with open(list_file, 'w') as f:
            for clip_path in clip_paths:
                # Format requis par FFmpeg
                f.write(f"file '{clip_path}'\n")
        
        # Concaténer avec FFmpeg
        cmd = [
            'ffmpeg',
            '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', list_file,
            '-c', 'copy',
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # Nettoyer le fichier de liste
        if os.path.exists(list_file):
            os.remove(list_file)
    
    def _upload_to_bunny(self, highlight_video: HighlightVideo, local_path: str):
        """Upload le fichier highlights vers Bunny CDN"""
        
        logger.info(f"☁️ Uploading highlights to Bunny CDN...")
        
        # Utiliser le service Bunny existant
        upload_id = bunny_storage_service.queue_upload(
            local_path=local_path,
            title=f"Highlights - Video {highlight_video.original_video_id}",
            metadata={
                'highlight_video_id': highlight_video.id,
                'original_video_id': highlight_video.original_video_id,
                'type': 'highlights'
            }
        )
        
        logger.info(f"  Upload queued: {upload_id}")
        
        # Attendre que l'upload soit terminé
        import time
        time.sleep(3)
        
        # Récupérer le statut
        upload_status = bunny_storage_service.get_upload_status(upload_id)
        
        if upload_status and upload_status.get('bunny_video_id'):
            highlight_video.bunny_video_id = upload_status['bunny_video_id']
            highlight_video.file_url = f"https://{self.config.BUNNY_CDN_HOSTNAME}/{highlight_video.bunny_video_id}/play.mp4"
            
            # Obtenir la durée
            highlight_video.duration = int(self._get_video_duration(local_path))
            
            db.session.commit()
            
            logger.info(f"✅ Uploaded to Bunny: {highlight_video.bunny_video_id}")
        else:
            logger.warning(f"⚠️ Upload status: {upload_status}")
    
    def _cleanup_temp_files(self, file_paths: List[str]):
        """Nettoie les fichiers temporaires"""
        
        for path in file_paths:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
                    logger.info(f"🗑️ Cleaned up: {path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not delete {path}: {e}")

# Instance singleton
simple_highlights_service = SimpleHighlightsService()
