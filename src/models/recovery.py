from datetime import datetime
from enum import Enum
from .database import db

class RecoveryStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RecoveryRequestType(Enum):
    AUTO = "auto"   # Detected by system
    MANUAL = "manual" # Requested by user/admin

class VideoRecoveryRequest(db.Model):
    """
    Model track video recovery requests from SD cards.
    """
    __tablename__ = 'video_recovery_request'

    id = db.Column(db.Integer, primary_key=True)
    
    # Context
    court_id = db.Column(db.Integer, db.ForeignKey('court.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Optional (if auto-detected without session)
    original_session_id = db.Column(db.String(100), nullable=True) # Linked recording session
    
    # Timing (Critical for SD card search)
    match_start = db.Column(db.DateTime, nullable=False)
    match_end = db.Column(db.DateTime, nullable=False)
    
    # Status
    status = db.Column(db.Enum(RecoveryStatus), default=RecoveryStatus.PENDING)
    request_type = db.Column(db.Enum(RecoveryRequestType), default=RecoveryRequestType.AUTO)
    priority = db.Column(db.Integer, default=1) # Higher = processed first
    
    # Result
    recovered_video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relations
    court = db.relationship('Court', backref='recovery_requests')
    user = db.relationship('User', backref='recovery_requests')
    recovered_video = db.relationship('Video', backref='recovery_source')

    def to_dict(self):
        return {
            'id': self.id,
            'court_id': self.court_id,
            'user_id': self.user_id,
            'court_name': self.court.name if self.court else None,
            'match_start': self.match_start.isoformat(),
            'match_end': self.match_end.isoformat(),
            'status': self.status.value,
            'request_type': self.request_type.value,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'recovered_video_id': self.recovered_video_id,
            'video_url': self.recovered_video.file_url if self.recovered_video else None,
            'video_status': self.recovered_video.processing_status if self.recovered_video else None
        }
