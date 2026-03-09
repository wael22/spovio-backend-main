from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

@dataclass
class RecordingSegment:
    """Represents a video segment found on the camera storage"""
    start_time: datetime
    end_time: datetime
    size_bytes: int
    download_url: str
    filename: str

class CameraDriver(ABC):
    """Abstract base class for IP Camera drivers"""
    
    def __init__(self, ip: str, port: int, username: str, password: str):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        
    @abstractmethod
    def find_recordings(self, start_time: datetime, end_time: datetime) -> List[RecordingSegment]:
        """
        Search for recordings on the camera storage within the given time range.
        Returns a list of segments that cover the requested period.
        """
        pass
        
    @abstractmethod
    def download_segment(self, segment: RecordingSegment, output_path: str, timeout: int = 300) -> bool:
        """
        Download a specific segment to a local file.
        """
        pass
        
    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if the camera is reachable and credentials are valid.
        """
        pass
