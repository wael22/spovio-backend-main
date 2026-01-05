"""
Modèle de base de données pour les enregistrements
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, Text, Boolean
from ..models.database import db


class Recording(db.Model):
    """Modèle pour stocker les enregistrements vidéo"""
    
    __tablename__ = 'recordings'
    
    # Identifiants
    id = Column(String(36), primary_key=True)  # UUID
    user_id = Column(Integer, nullable=False)
    court_id = Column(Integer, nullable=False)
    match_id = Column(Integer, nullable=True)
    club_id = Column(Integer, nullable=True)
    
    # Métadonnées vidéo
    title = Column(String(255), nullable=False)
    file_url = Column(String(500), nullable=False)
    thumbnail_url = Column(String(500), nullable=True)
    
    # Timing
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)  # en secondes
    
    # Fichier
    file_size = Column(Integer, nullable=True)  # en bytes
    resolution_width = Column(Integer, nullable=True)
    resolution_height = Column(Integer, nullable=True)
    fps = Column(Float, nullable=True)
    bitrate = Column(String(20), nullable=True)
    
    # État
    status = Column(String(20), nullable=False, default='created')
    # created|recording|processing|completed|error
    
    upload_status = Column(String(20), nullable=False, default='pending')
    # pending|uploading|completed|failed
    
    error_message = Column(Text, nullable=True)
    
    # Bunny Stream
    bunny_video_id = Column(String(100), nullable=True)
    bunny_url = Column(String(500), nullable=True)
    
    # Paramètres
    quality_preset = Column(String(20), nullable=True)
    camera_type = Column(String(20), nullable=True)
    max_duration = Column(Integer, nullable=False, default=3600)
    
    # Accès
    is_public = Column(Boolean, nullable=False, default=False)
    credits_cost = Column(Integer, nullable=False, default=10)
    
    # Audit
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, 
                       onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Recording {self.id}: {self.title}>'
    
    def to_dict(self):
        """Sérialise en dictionnaire pour l'API"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'court_id': self.court_id,
            'match_id': self.match_id,
            'club_id': self.club_id,
            'title': self.title,
            'file_url': self.file_url,
            'thumbnail_url': self.thumbnail_url,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration': self.duration,
            'file_size': self.file_size,
            'resolution': {
                'width': self.resolution_width,
                'height': self.resolution_height
            } if self.resolution_width else None,
            'fps': self.fps,
            'bitrate': self.bitrate,
            'status': self.status,
            'upload_status': self.upload_status,
            'error_message': self.error_message,
            'bunny_video_id': self.bunny_video_id,
            'bunny_url': self.bunny_url,
            'quality_preset': self.quality_preset,
            'camera_type': self.camera_type,
            'max_duration': self.max_duration,
            'is_public': self.is_public,
            'credits_cost': self.credits_cost,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
