import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from ..models.database import db
from ..models.recovery import VideoRecoveryRequest, RecoveryStatus, RecoveryRequestType
from ..models.user import Court, User, Video
from ..video_system.drivers.uniview import UniviewDriver
from ..services.bunny_storage_service import bunny_storage_service
from ..video_system.config import VideoConfig

logger = logging.getLogger(__name__)

class RecoveryService:
    """
    Service to handle video recovery from camera SD cards.
    """
    
    def __init__(self):
        self.download_dir = Path(VideoConfig.VIDEOS_DIR) / "recovery"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
    def create_request(self, court_id: int, start_time: datetime, end_time: datetime, 
                      user_id: Optional[int] = None, request_type: RecoveryRequestType = RecoveryRequestType.MANUAL) -> VideoRecoveryRequest:
        """Create a new recovery request"""
        request = VideoRecoveryRequest(
            court_id=court_id,
            user_id=user_id,
            match_start=start_time,
            match_end=end_time,
            status=RecoveryStatus.PENDING,
            request_type=request_type
        )
        db.session.add(request)
        db.session.commit()
        logger.info(f"Created recovery request {request.id} for court {court_id}")
        return request

    def process_pending_requests(self):
        """Process all pending recovery requests"""
        pending_requests = VideoRecoveryRequest.query.filter_by(status=RecoveryStatus.PENDING).all()
        logger.info(f"Found {len(pending_requests)} pending recovery requests")
        
        for request in pending_requests:
            self.process_request(request)

    def process_request(self, request: VideoRecoveryRequest):
        """Process a single recovery request"""
        try:
            logger.info(f"Processing recovery request {request.id}")
            request.status = RecoveryStatus.PROCESSING
            request.started_at = datetime.utcnow()
            db.session.commit()
            
            # 1. Get Camera Credentials
            court = Court.query.get(request.court_id)
            if not court:
                raise ValueError(f"Court {request.court_id} not found")
                
            # Extract credentials from RTSP URL or use default/configured ones
            # Assumes URL format: rtsp://user:pass@ip:port/...
            credentials = self._parse_rtsp_url(court.camera_url)
            if not credentials:
                raise ValueError("Could not parse credentials from camera URL")
                
            driver = UniviewDriver(
                ip=credentials['ip'],
                port=credentials['port'], 
                username=credentials['username'],
                password=credentials['password']
            )
            
            # 2. Check Connection
            if not driver.health_check():
                raise ConnectionError(f"Could not connect to camera at {credentials['ip']}")
                
            # 3. Find Recordings
            logger.info(f"Searching for recordings between {request.match_start} and {request.match_end}")
            segments = driver.find_recordings(request.match_start, request.match_end)
            
            if not segments:
                raise FileNotFoundError("No recordings found on SD card for this period")
                
            logger.info(f"Found {len(segments)} segments")
            
            # 4. Download Segments
            downloaded_files = []
            for i, segment in enumerate(segments):
                filename = f"recovery_{request.id}_seg_{i}.mp4"
                output_path = self.download_dir / filename
                
                if driver.download_segment(segment, str(output_path)):
                    downloaded_files.append(str(output_path))
                else:
                    logger.error(f"Failed to download segment {i}")
                    
            if not downloaded_files:
                raise RuntimeError("Failed to download any segments")
                
            # 5. Concatenate if multiple (using ffmpeg) or just use the first if single/merged
            # For simplicity MVP, we'll take the first large enough file or headers
            # Ideally we should merge with ffmpeg here.
            final_file_path = downloaded_files[0] 
            
            if len(downloaded_files) > 1:
                final_file_path = self._merge_videos(downloaded_files, request.id)

            # 6. Upload to Bunny
            logger.info(f"Uploading recovered video: {final_file_path}")
            
            # Create video metadata
            duration = int((request.match_end - request.match_start).total_seconds())
            
            file_size = os.path.getsize(final_file_path)
            
            # Create placeholder video record
            video = Video(
                title=f"Recovered Match - {request.match_start.strftime('%d/%m %H:%M')}",
                description="Automatically recovered from camera SD card",
                user_id=request.user_id if request.user_id else 1, # Default to admin/system if unknown
                court_id=request.court_id,
                duration=duration,
                file_size=file_size,
                processing_status="uploading"
            )
            db.session.add(video)
            db.session.commit()
            
            # Queue upload
            metadata = {
                'video_id': video.id,
                'user_id': video.user_id,
                'court_id': video.court_id,
                'duration': duration
            }
            
            bunny_task_id = bunny_storage_service.queue_upload(final_file_path, video.title, metadata)
            
            # Update Request
            request.status = RecoveryStatus.COMPLETED
            request.completed_at = datetime.utcnow()
            request.recovered_video_id = video.id
            db.session.commit()
            
            logger.info(f"Recovery request {request.id} completed successfully")
            
        except Exception as e:
            logger.error(f"Recovery failed: {e}", exc_info=True)
            request.status = RecoveryStatus.FAILED
            request.error_message = str(e)
            db.session.commit()

    def _parse_rtsp_url(self, url: str) -> Optional[Dict]:
        """Parse RTSP/HTTP URL to extract credentials and IP details"""
        try:
            if not url:
                return None
                
            # Defaults
            username = "admin"
            password = "password" # You might want to load this from env
            ip = "127.0.0.1"
            port = 80
            
            # Simple parsing if it contains @ (user:pass@host)
            if '@' in url:
                # Remove protocol prefix
                clean_url = url.split('://')[-1]
                
                auth_part, address_part = clean_url.split('@', 1)
                
                if ':' in auth_part:
                    username, password = auth_part.split(':', 1)
                else:
                    username = auth_part
                
                if '/' in address_part:
                    address_part = address_part.split('/')[0]
                    
                if ':' in address_part:
                    ip, port_str = address_part.split(':', 1)
                    try:
                        port = int(port_str)
                    except:
                        pass
                else:
                    ip = address_part
            else:
                # No credentials in URL, try to just exact host/ip
                # This is a fallback for testing or open streams
                clean_url = url.split('://')[-1]
                address_part = clean_url.split('/')[0]
                if ':' in address_part:
                    ip, port_str = address_part.split(':', 1)
                    try:
                        port = int(port_str)
                    except:
                        pass
                else:
                    ip = address_part
                    
            # Special handling: If RTMP (1935), we likely want RTSP (554) for recovery
            if 'rtmp' in url.lower() or port == 1935:
                # logger.info(f"Detected RTMP/1935 in URL ({url}), defaulting to RTSP port 554 for recovery")
                port = 554
                
            return {
                'username': username,
                'password': password,
                'ip': ip,
                'port': port if port else 554
            }
        except Exception as e:
            logger.error(f"Error parsing RTSP URL: {e}")
            # Return basic defaults if parsing fails completely, rather than crashing
            return {
                'username': 'admin',
                'password': 'password',
                'ip': '127.0.0.1',
                'port': 554 
            }

    def _merge_videos(self, file_paths: List[str], request_id: int) -> str:
        """Merge multiple video files using FFmpeg"""
        # This requires ffmpeg installed
        import subprocess
        
        list_file_path = self.download_dir / f"list_{request_id}.txt"
        output_path = self.download_dir / f"merged_{request_id}.mp4"
        
        try:
            with open(list_file_path, 'w') as f:
                for path in file_paths:
                    # Windows path escaping might be needed
                    f.write(f"file '{path}'\n")
            
            cmd = [
                "ffmpeg", "-f", "concat", "-safe", "0", 
                "-i", str(list_file_path),
                "-c", "copy", "-y", str(output_path)
            ]
            
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Cleanup source files
            for path in file_paths:
                try:
                    os.remove(path)
                except:
                    pass
            os.remove(list_file_path)
            
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Merge failed, returning first file: {e}")
            return file_paths[0]

recovery_service = RecoveryService()
