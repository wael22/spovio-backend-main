"""
Modèles SQLAlchemy pour les enregistrements vidéo et les matches
Extension des modèles existants pour supporter le système d'enregistrement
"""
from datetime import datetime
from enum import Enum
from .database import db


class RecordingStatus(Enum):
    """Statut d'un enregistrement vidéo"""
    IDLE = "idle"
    RECORDING = "recording"
    DONE = "done"
    ERROR = "error"


class Match(db.Model):
    """Modèle pour représenter un match de padel"""
    __tablename__ = 'match'
    
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    court_id = db.Column(db.Integer, db.ForeignKey('court.id'), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    video_path = db.Column(db.String(255), nullable=True)
    recording_status = db.Column(
        db.Enum(RecordingStatus),
        default=RecordingStatus.IDLE,
        nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    player = db.relationship('User', backref='matches', lazy=True)
    court = db.relationship('Court', backref='matches', lazy=True)
    
    def to_dict(self):
        """Convertir le modèle en dictionnaire"""
        return {
            'id': self.id,
            'player_id': self.player_id,
            'court_id': self.court_id,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'video_path': self.video_path,
            'recording_status': self.recording_status.value if self.recording_status else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ProxyStatus(db.Model):
    """Modèle pour stocker le statut des proxies vidéo"""
    __tablename__ = 'proxy_status'
    
    id = db.Column(db.Integer, primary_key=True)
    court_id = db.Column(db.Integer, db.ForeignKey('court.id'), nullable=False, unique=True)
    port = db.Column(db.Integer, nullable=False)
    is_running = db.Column(db.Boolean, default=False)
    is_connected = db.Column(db.Boolean, default=False)
    last_check = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    court = db.relationship('Court', backref='proxy_status', lazy=True)
    
    def to_dict(self):
        """Convertir le modèle en dictionnaire"""
        return {
            'id': self.id,
            'court_id': self.court_id,
            'port': self.port,
            'is_running': self.is_running,
            'is_connected': self.is_connected,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class RecordingLog(db.Model):
    """Modèle pour enregistrer les logs d'enregistrement vidéo"""
    __tablename__ = 'recording_log'
    
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    court_id = db.Column(db.Integer, db.ForeignKey('court.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'start', 'stop', 'error'
    message = db.Column(db.Text, nullable=True)
    video_path = db.Column(db.String(255), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    file_size_bytes = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    match = db.relationship('Match', backref='recording_logs', lazy=True)
    court = db.relationship('Court', backref='recording_logs', lazy=True)
    
    def to_dict(self):
        """Convertir le modèle en dictionnaire"""
        return {
            'id': self.id,
            'match_id': self.match_id,
            'court_id': self.court_id,
            'action': self.action,
            'message': self.message,
            'video_path': self.video_path,
            'duration_seconds': self.duration_seconds,
            'file_size_bytes': self.file_size_bytes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
