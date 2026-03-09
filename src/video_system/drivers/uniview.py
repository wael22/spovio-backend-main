import logging
import requests
from datetime import datetime
from typing import List, Optional
from requests.auth import HTTPDigestAuth
import urllib.parse

from .base import CameraDriver, RecordingSegment

logger = logging.getLogger(__name__)

class UniviewDriver(CameraDriver):
    """
    Driver for Uniview IP Cameras (IPC3535LB-ADZK-H)
    Uses RTSP Replay (Backfilling) as LAPI is not supported.
    """
    
    def __init__(self, ip: str, port: int, username: str, password: str):
        super().__init__(ip, port, username, password)
        # RTSP Port is default 554
        self.rtsp_port = port if port != 80 else 554
        
    def health_check(self) -> bool:
        """Check connection by attempting to connect to the RTSP port"""
        import socket
        try:
            with socket.create_connection((self.ip, self.rtsp_port), timeout=5):
                return True
        except Exception as e:
            logger.error(f"Uniview RTSP health check failed: {e}")
            return False

    def find_recordings(self, start_time: datetime, end_time: datetime) -> List[RecordingSegment]:
        """
        Since LAPI is not supported, we cannot query the exact segments.
        We assume the recording exists for the requested time range and let the RTSP Replay fail if not.
        Returns a single 'virtual' segment for the requested duration.
        """
        # Pattern verified: rtsp://user:pass@ip:port/playback/service?starttime=...&endtime=...
        # Format: YYYY_MM_DD_HH_MM_SS
        t_start_flat = start_time.strftime("%Y_%m_%d_%H_%M_%S")
        t_end_flat = end_time.strftime("%Y_%m_%d_%H_%M_%S")
        
        # We need to escape the password for the URL if it contains special chars?
        # Standard RTSP URL usually handles it, but safer to warn/check. 
        # For now, we construct it directly.
        
        replay_url = (
            f"rtsp://{self.username}:{self.password}@{self.ip}:{self.rtsp_port}"
            f"/playback/service?starttime={t_start_flat}&endtime={t_end_flat}"
        )
        
        # Return a virtual segment
        return [RecordingSegment(
            start_time=start_time,
            end_time=end_time,
            size_bytes=0, # Unknown
            download_url=replay_url,
            filename=f"uniview_replay_{t_start_flat}_{t_end_flat}.mp4"
        )]

    def download_segment(self, segment: RecordingSegment, output_path: str, timeout: int = 300) -> bool:
        """
        Download (record) the RTSP replay stream to a file using FFmpeg.
        """
        import subprocess
        import os
        
        try:
            logger.info(f"Downloading segment via RTSP Replay: {segment.download_url}")
            
            # Using -rtsp_transport tcp is often more reliable for playback
            # -t specifies duration to stop (safety net), though the stream should end itself
            duration_sec = (segment.end_time - segment.start_time).total_seconds()
            
            # FFmpeg command
            cmd = [
                "ffmpeg",
                "-y", # Overwrite
                "-rtsp_transport", "tcp",
                "-i", segment.download_url,
                "-c", "copy", # No re-encoding
                "-t", str(duration_sec + 10), # Add buffer
                str(output_path)
            ]
            
            logger.info(f"Running FFmpeg: {' '.join(cmd)}")
            
            # Run FFmpeg
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout
            )
            
            if process.returncode != 0:
                logger.error(f"FFmpeg failed: {process.stderr.decode()}")
                return False
                
            # Verify file exists and has size
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return True
            else:
                logger.error("Output file is empty or missing")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timed out downloading segment")
            return False
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False
