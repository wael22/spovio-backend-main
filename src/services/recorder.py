import asyncio
import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from config import settings
from services.proxy_manager import proxy_manager

logger = logging.getLogger("video")

class RecordingInfo:
    def __init__(self, match_id: int, court_id: int, video_path: str, process: subprocess.Popen):
        self.match_id = match_id
        self.court_id = court_id
        self.video_path = video_path
        self.process = process
        self.started_at = datetime.utcnow()
        self.lock = threading.Lock()

class RecordingManager:
    def __init__(self):
        self.recordings: Dict[int, RecordingInfo] = {}
        self.max_concurrent = settings.MAX_CONCURRENT_RECORDINGS
        self.ffmpeg_path = settings.FFMPEG_PATH
        self.video_root = settings.VIDEO_ROOT
        self.lock = threading.Lock()
        
        self.video_root.mkdir(parents=True, exist_ok=True)
    
    async def start_recording(
        self,
        match_id: int,
        court_id: int,
        duration_seconds: Optional[int] = None
    ) -> str:
        with self.lock:
            if match_id in self.recordings:
                logger.warning(f"Recording already in progress for match {match_id}")
                raise ValueError(f"Recording already in progress for match {match_id}")
            
            if len(self.recordings) >= self.max_concurrent:
                raise ValueError(f"Maximum concurrent recordings ({self.max_concurrent}) reached")
        
        proxy_port = proxy_manager.get_proxy_port(court_id)
        if proxy_port is None:
            proxy_port = settings.PROXY_BASE_PORT + (court_id - 1)
        
        proxy_url = f"http://localhost:{proxy_port}/stream.mjpg"
        
        is_healthy = await proxy_manager.is_proxy_healthy(court_id)
        if not is_healthy:
            logger.warning(f"Proxy for court {court_id} not healthy, attempting to start")
        
        video_filename = f"match_{match_id}.mp4"
        video_path = self.video_root / video_filename
        
        ffmpeg_cmd = self._build_ffmpeg_command(
            proxy_url,
            str(video_path),
            duration_seconds
        )
        
        logger.info(f"Starting recording for match {match_id}, court {court_id}")
        logger.debug(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
        
        try:
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            recording_info = RecordingInfo(match_id, court_id, str(video_path), process)
            
            with self.lock:
                self.recordings[match_id] = recording_info
            
            threading.Thread(
                target=self._monitor_recording,
                args=(match_id,),
                daemon=True
            ).start()
            
            logger.info(f"Recording started for match {match_id} -> {video_path}")
            return str(video_path)
            
        except Exception as e:
            logger.error(f"Failed to start recording for match {match_id}: {e}")
            raise
    
    def _build_ffmpeg_command(
        self,
        input_url: str,
        output_path: str,
        duration_seconds: Optional[int] = None
    ) -> list:
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_url,
            "-vf", "fps=25",
            "-vsync", "1",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-movflags", "+faststart"
        ]
        
        if duration_seconds:
            cmd.extend(["-t", str(duration_seconds)])
        
        cmd.append(output_path)
        
        return cmd
    
    async def stop_recording(self, match_id: int) -> str:
        with self.lock:
            if match_id not in self.recordings:
                logger.warning(f"No recording found for match {match_id}")
                raise ValueError(f"No recording found for match {match_id}")
            
            recording = self.recordings[match_id]
        
        logger.info(f"Stopping recording for match {match_id}")
        
        try:
            if recording.process.poll() is None:
                try:
                    recording.process.stdin.write(b'q')
                    recording.process.stdin.flush()
                except Exception as e:
                    logger.warning(f"Failed to send 'q' to FFmpeg: {e}")
                
                try:
                    recording.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    logger.warning(f"FFmpeg did not stop gracefully, terminating")
                    recording.process.terminate()
                    try:
                        recording.process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        logger.error(f"FFmpeg did not terminate, killing")
                        recording.process.kill()
            
            with self.lock:
                del self.recordings[match_id]
            
            logger.info(f"Recording stopped for match {match_id}")
            return recording.video_path
            
        except Exception as e:
            logger.error(f"Error stopping recording for match {match_id}: {e}")
            raise
    
    def is_recording(self, match_id: int) -> bool:
        with self.lock:
            return match_id in self.recordings
    
    def get_active_recordings(self) -> list:
        with self.lock:
            return [
                {
                    "match_id": rec.match_id,
                    "court_id": rec.court_id,
                    "video_path": rec.video_path,
                    "started_at": rec.started_at.isoformat()
                }
                for rec in self.recordings.values()
            ]
    
    def _monitor_recording(self, match_id: int):
        try:
            recording = self.recordings.get(match_id)
            if not recording:
                return
            
            process = recording.process
            
            process.wait()
            
            return_code = process.returncode
            
            if return_code != 0:
                stderr_output = process.stderr.read().decode('utf-8', errors='ignore')
                logger.error(
                    f"Recording for match {match_id} ended with error (code {return_code}): "
                    f"{stderr_output[-500:]}"
                )
            else:
                logger.info(f"Recording for match {match_id} completed successfully")
            
            with self.lock:
                if match_id in self.recordings:
                    del self.recordings[match_id]
                    
        except Exception as e:
            logger.error(f"Error monitoring recording for match {match_id}: {e}")
            with self.lock:
                if match_id in self.recordings:
                    del self.recordings[match_id]
    
    async def cleanup_zombie_processes(self):
        with self.lock:
            dead_matches = []
            for match_id, recording in self.recordings.items():
                if recording.process.poll() is not None:
                    dead_matches.append(match_id)
            
            for match_id in dead_matches:
                logger.info(f"Cleaning up zombie recording for match {match_id}")
                del self.recordings[match_id]

recording_manager = RecordingManager()
