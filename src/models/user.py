# padelvar-backend/src/models/user.py

from datetime import datetime
from enum import Enum
from .database import db
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import event
import logging

# Logging
logger = logging.getLogger(__name__)

class UserRole(Enum):
    SUPER_ADMIN = "super_admin"
    PLAYER = "player"
    CLUB = "club"

class UserStatus(Enum):
    ACTIVE = "active"
    PENDING_VERIFICATION = "pending_verification"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"

class TransactionStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"

class NotificationType(Enum):
    VIDEO_READY = "video_ready"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    CREDITS_ADDED = "credits_added"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    ACCOUNT_SUSPENDED = "account_suspended"
    SESSION_EXPIRED = "session_expired"
    SYSTEM_MAINTENANCE = "system_maintenance"

player_club_follows = db.Table(
    'player_club_follows',
    db.Column('player_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('club_id', db.Integer, db.ForeignKey('club.id'), primary_key=True)
)

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.PLAYER)
    status = db.Column(db.Enum(UserStatus), nullable=False, default=UserStatus.ACTIVE)
    credits_balance = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    google_id = db.Column(db.String(100), nullable=True, unique=True)  # ID Google pour l'authentification
    
    # Champs pour la vérification d'email
    email_verified = db.Column(db.Boolean, default=False, nullable=False)  # Statut de vérification
    email_verification_token = db.Column(db.String(10), nullable=True)  # Code de vérification
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)  # Date d'envoi du code
    
    # Champs pour l'authentification à deux facteurs (2FA)
    two_factor_secret = db.Column(db.String(255), nullable=True)  # Secret TOTP chiffré
    two_factor_enabled = db.Column(db.Boolean, default=False)  # Si 2FA est activé
    two_factor_backup_codes = db.Column(db.Text, nullable=True)  # Codes de secours (JSON)
    
    # Champs pour le tutoriel
    tutorial_completed = db.Column(db.Boolean, default=False, nullable=False)  # Tutoriel complété
    tutorial_step = db.Column(db.Integer, nullable=True)  # Étape actuelle du tutoriel (1-10)
    
    videos = db.relationship('Video', backref='owner', lazy=True, cascade='all, delete-orphan')
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=True)
    
    followed_clubs = db.relationship('Club', 
                                   secondary=player_club_follows,
                                   backref=db.backref('followers', lazy='dynamic'),
                                   lazy='dynamic')

    def to_dict(self):
        user_dict = {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'phone_number': self.phone_number,
            'role': self.role.value,
            'status': self.status.value,
            'credits_balance': self.credits_balance,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            'email_verified': self.email_verified,
            'email_verified_at': self.email_verified_at.isoformat() if self.email_verified_at else None,
            'club_id': self.club_id,
            'tutorial_completed': self.tutorial_completed,
            'tutorial_step': self.tutorial_step
        }
        if self.role == UserRole.CLUB and self.club_id:
            club = Club.query.get(self.club_id)
            if club:
                user_dict['club'] = club.to_dict()
        return user_dict

class Club(db.Model):
    __tablename__ = 'club'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    credits_balance = db.Column(db.Integer, default=0, nullable=False)  # Nouveau champ pour gérer le solde de crédits du club
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    players = db.relationship('User', backref='club', lazy=True)
    courts = db.relationship('Court', backref='club', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'address': self.address,
            'phone_number': self.phone_number, 'email': self.email,
            'credits_balance': self.credits_balance,  # Inclure le solde de crédits
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'overlays': [overlay.to_dict() for overlay in self.overlays] if hasattr(self, 'overlays') else []
        }

class ClubOverlay(db.Model):
    __tablename__ = 'club_overlay'
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    name = db.Column(db.String(100), nullable=True)  # Nom descriptif (ex: Logo Principal)
    image_url = db.Column(db.String(255), nullable=False)
    position_x = db.Column(db.Float, default=5, nullable=False)  # Pourcentage X (0-100)
    position_y = db.Column(db.Float, default=5, nullable=False)  # Pourcentage Y (0-100)
    width = db.Column(db.Float, default=10, nullable=False)      # Pourcentage Largeur (relative au container)
    opacity = db.Column(db.Float, default=1.0, nullable=False)   # Opacité (0.0-1.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relation
    club = db.relationship('Club', backref=db.backref('overlays', lazy=True, cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'club_id': self.club_id,
            'name': self.name,
            'image_url': self.image_url,
            'position_x': self.position_x,
            'position_y': self.position_y,
            'width': self.width,
            'opacity': self.opacity,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Court(db.Model):
    __tablename__ = 'court'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    qr_code = db.Column(db.String(100), unique=True, nullable=False)
    camera_url = db.Column(db.String(255), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    
    # Nouveau : statut d'occupation pour l'enregistrement
    is_recording = db.Column(db.Boolean, default=False)
    recording_session_id = db.Column(db.String(100), nullable=True)
    current_recording_id = db.Column(db.String(100), nullable=True)
    
    videos = db.relationship('Video', backref='court', lazy=True)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "club_id": self.club_id,
            "camera_url": self.camera_url, "qr_code": self.qr_code,
            "is_recording": self.is_recording,
            "recording_session_id": self.recording_session_id,
            "current_recording_id": self.current_recording_id,
            "available": not self.is_recording
        }

class Video(db.Model):
    __tablename__ = 'video'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    file_url = db.Column(db.String(255), nullable=True)
    thumbnail_url = db.Column(db.String(255), nullable=True)
    duration = db.Column(db.Integer, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)  # Taille du fichier en octets
    is_unlocked = db.Column(db.Boolean, default=True)
    credits_cost = db.Column(db.Integer, default=1)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cdn_migrated_at = db.Column(db.DateTime, nullable=True)  # Date de migration vers Bunny Stream
    bunny_video_id = db.Column(db.String(100), nullable=True)  # ID vidéo Bunny Stream (GUID)
    processing_status = db.Column(db.String(20), default='pending', nullable=True)  # Statut Bunny: 'pending', 'uploading', 'processing', 'ready', 'failed'
    deleted_at = db.Column(db.DateTime, nullable=True)  # Soft delete: date de suppression
    deletion_mode = db.Column(db.String(20), nullable=True)  # Mode de suppression: 'database', 'cloud', 'both', 'local_only', 'cloud_only', 'local_and_cloud'
    
    # Tracking fichiers locaux et cloud
    local_file_path = db.Column(db.String(500), nullable=True)  # Chemin du fichier local sur le serveur
    local_file_deleted_at = db.Column(db.DateTime, nullable=True)  # Date de suppression du fichier local
    cloud_deleted_at = db.Column(db.DateTime, nullable=True)  # Date de suppression du cloud (Bunny CDN)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    court_id = db.Column(db.Integer, db.ForeignKey('court.id'), nullable=True)
    
    # Relations (en utilisant les backrefs existants)
    # user = défini via backref='owner' dans User.videos
    # court = défini via backref='court' dans Court.videos

    def to_dict(self):
        # Calculer le statut de suppression
        deletion_status = "active"  # Par défaut
        if self.local_file_deleted_at and self.cloud_deleted_at:
            deletion_status = "deleted_both"  # Supprimé local + cloud
        elif self.local_file_deleted_at:
            deletion_status = "deleted_local"  # Supprimé local uniquement
        elif self.cloud_deleted_at:
            deletion_status = "deleted_cloud"  # Supprimé cloud uniquement
        elif self.deleted_at:
            deletion_status = "deleted_db"  # Supprimé en base (ne devrait pas arriver)
        
        # ✅ NOUVEAU: Une vidéo est expirée si le cloud est supprimé ou inexistant
        # (important pour les joueurs qui ne peuvent plus regarder la vidéo)
        is_expired = (
            deletion_status in ["deleted_cloud", "deleted_both"] or
            (self.bunny_video_id is None and self.local_file_path is None) or
            self.cloud_deleted_at is not None
        )
        
        return {
            "id": self.id, "user_id": self.user_id, "court_id": self.court_id,
            "file_url": self.file_url, "thumbnail_url": self.thumbnail_url,
            "title": self.title, "description": self.description, "duration": self.duration,
            "file_size": self.file_size, "is_unlocked": self.is_unlocked, "credits_cost": self.credits_cost,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "cdn_migrated_at": self.cdn_migrated_at.isoformat() if self.cdn_migrated_at else None,
            "bunny_video_id": self.bunny_video_id,
            "processing_status": self.processing_status,  # 'pending', 'uploading', 'processing', 'ready', 'failed'
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "is_deleted": self.deleted_at is not None,
            "deletion_mode": self.deletion_mode,
            "deletion_status": deletion_status,  # ✅ Indicateur clair de l'état de suppression
            "is_expired": is_expired,  # ✅ NOUVEAU: Vidéo expirée (cloud supprimé/inexistant)
            "club_id": self.court.club_id if self.court else None,
            
            # État des fichiers locaux et cloud
            "local_file_path": self.local_file_path,
            "has_local_file": self.local_file_path is not None and self.local_file_deleted_at is None,
            "has_cloud_file": self.bunny_video_id is not None and self.cloud_deleted_at is None,
            "local_file_deleted_at": self.local_file_deleted_at.isoformat() if self.local_file_deleted_at else None,
            "cloud_deleted_at": self.cloud_deleted_at.isoformat() if self.cloud_deleted_at else None,
            
            # Simplicité pour frontend - une vidéo est visible si elle est prête ET pas supprimée du cloud
            "is_watchable": self.bunny_video_id is not None and self.cloud_deleted_at is None and self.processing_status == 'ready',
            "is_processing": self.processing_status in ['uploading', 'processing'],
        }

class HighlightVideo(db.Model):
    """Vidéo de highlights générée automatiquement"""
    __tablename__ = 'highlight_video'
    
    id = db.Column(db.Integer, primary_key=True)
    original_video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    bunny_video_id = db.Column(db.String(100), nullable=True)  # GUID Bunny Stream
    file_url = db.Column(db.String(255), nullable=True)  # URL Bunny CDN
    duration = db.Column(db.Integer, nullable=True)  # En secondes
    
    # Métadonnées
    clips_count = db.Column(db.Integer, default=0)  # Nombre de clips utilisés
    generation_status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    
    # Détails des highlights (JSON)
    highlights_data = db.Column(db.Text, nullable=True)  # JSON: liste des timestamps
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relations
    original_video = db.relationship('Video', backref='highlights', foreign_keys=[original_video_id])
    
    def to_dict(self):
        import json
        return {
            "id": self.id,
            "original_video_id": self.original_video_id,
            "bunny_video_id": self.bunny_video_id,
            "file_url": self.file_url,
            "duration": self.duration,
            "clips_count": self.clips_count,
            "status": self.generation_status,
            "highlights_data": json.loads(self.highlights_data) if self.highlights_data else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }

class HighlightJob(db.Model):
    """Tâche de génération de highlights"""
    __tablename__ = 'highlight_job'
    
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    status = db.Column(db.String(50), default='queued')  # queued, downloading, processing, uploading, completed, failed
    progress = db.Column(db.Integer, default=0)  # 0-100
    error_message = db.Column(db.Text, nullable=True)
    
    # Configuration
    target_duration = db.Column(db.Integer, default=90)  # secondes
    
    # Résultat
    highlight_video_id = db.Column(db.Integer, db.ForeignKey('highlight_video.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relations
    video = db.relationship('Video', backref='highlight_jobs', foreign_keys=[video_id])
    user = db.relationship('User', backref='highlight_jobs')
    highlight_video = db.relationship('HighlightVideo', backref='job', foreign_keys=[highlight_video_id])
    
    def to_dict(self):
        return {
            "id": self.id,
            "video_id": self.video_id,
            "user_id": self.user_id,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "target_duration": self.target_duration,
            "highlight_video_id": self.highlight_video_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }

class UserClip(db.Model):
    """Clip vidéo créé manuellement par l'utilisateur"""
    __tablename__ = 'user_clip'
    
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Métadonnées du clip
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Timing (en secondes)
    start_time = db.Column(db.Float, nullable=False)  # Position de début dans la vidéo originale
    end_time = db.Column(db.Float, nullable=False)    # Position de fin dans la vidéo originale
    duration = db.Column(db.Integer, nullable=True)   # Durée du clip en secondes
    
    # Fichiers
    file_url = db.Column(db.String(500), nullable=True)        # URL du clip sur Bunny CDN
    thumbnail_url = db.Column(db.String(500), nullable=True)   # URL de la miniature
    bunny_video_id = db.Column(db.String(100), nullable=True)  # ID Bunny Stream
    
    # Statut de traitement
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    error_message = db.Column(db.Text, nullable=True)
    
    # Statistiques de partage
    share_count = db.Column(db.Integer, default=0)
    download_count = db.Column(db.Integer, default=0)
    
    # Dates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relations
    video = db.relationship('Video', backref='user_clips', foreign_keys=[video_id])
    user = db.relationship('User', backref='created_clips')
    
    def to_dict(self):
        return {
            "id": self.id,
            "video_id": self.video_id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "file_url": self.file_url,
            "thumbnail_url": self.thumbnail_url,
            "bunny_video_id": self.bunny_video_id,
            "status": self.status,
            "error_message": self.error_message,
            "share_count": self.share_count,
            "download_count": self.download_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }

class RecordingSession(db.Model):
    """Modèle pour gérer les sessions d'enregistrement en cours"""
    __tablename__ = 'recording_session'
    id = db.Column(db.Integer, primary_key=True)
    recording_id = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    court_id = db.Column(db.Integer, db.ForeignKey('court.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    
    # Durée et timing
    planned_duration = db.Column(db.Integer, nullable=False)  # en minutes
    max_duration = db.Column(db.Integer, default=200)  # limite max en minutes
    start_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    
    # Statut
    status = db.Column(db.String(20), default='active')  # active, stopped, completed, expired
    stopped_by = db.Column(db.String(20), nullable=True)  # player, club, auto
    
    # Métadonnées
    title = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    user = db.relationship('User', backref='recording_sessions')
    court = db.relationship('Court', backref='recording_sessions')
    club = db.relationship('Club', backref='recording_sessions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'recording_id': self.recording_id,
            'user_id': self.user_id,
            'court_id': self.court_id,
            'club_id': self.club_id,
            'planned_duration': self.planned_duration,
            'max_duration': self.max_duration,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'status': self.status,
            'stopped_by': self.stopped_by,
            'title': self.title,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'elapsed_minutes': self.get_elapsed_minutes(),
            'remaining_minutes': self.get_remaining_minutes(),
            'is_expired': self.is_expired()
        }
    
    def get_elapsed_minutes(self):
        """Calculer le temps écoulé en minutes"""
        if not self.start_time:
            return 0
        end_time = self.end_time or datetime.utcnow()
        delta = end_time - self.start_time
        return int(delta.total_seconds() / 60)
    
    def get_remaining_minutes(self):
        """Calculer le temps restant en minutes"""
        if self.status != 'active':
            return 0
        elapsed = self.get_elapsed_minutes()
        return max(0, self.planned_duration - elapsed)
    
    def is_expired(self):
        """Vérifier si l'enregistrement a expiré
        
        L'enregistrement est considéré comme expiré si la durée planifiée est dépassée.
        """
        # Si l'enregistrement n'est pas actif, il n'est pas expiré (déjà arrêté)
        if self.status != 'active':
            return False
            
        # Calcul du temps écoulé
        elapsed = self.get_elapsed_minutes()
        
        # L'enregistrement expire si la durée planifiée est dépassée
        return elapsed >= self.planned_duration

class ClubActionHistory(db.Model):
    __tablename__ = 'club_action_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=True)
    performed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    action_details = db.Column(db.Text, nullable=True)
    performed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='actions_suffered')
    club = db.relationship('Club', backref='history_actions')
    performed_by = db.relationship('User', foreign_keys=[performed_by_id], backref='actions_performed')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'club_id': self.club_id,
            'performed_by_id': self.performed_by_id,
            'action_type': self.action_type,
            'action_details': self.action_details,
            'performed_at': self.performed_at.isoformat() if self.performed_at else None
        }

class Transaction(db.Model):
    """Modèle pour gérer les transactions de paiement et d'achat de crédits"""
    __tablename__ = 'transaction'
    
    id = db.Column(db.Integer, primary_key=True)
    # Identifiant unique pour l'idempotence
    idempotency_key = db.Column(db.String(100), unique=True, nullable=True)
    
    # Relation utilisateur
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='transactions')
    
    # Type et détails de la transaction
    transaction_type = db.Column(db.String(50), nullable=False)  # 'credit_purchase', 'credit_usage', 'refund'
    package_name = db.Column(db.String(100), nullable=True)  # '10_credits', '50_credits', etc.
    credits_amount = db.Column(db.Integer, nullable=False)  # Nombre de crédits
    
    # Montant financier (en centimes pour éviter les problèmes de virgule)
    amount_cents = db.Column(db.Integer, nullable=True)  # Prix en centimes
    currency = db.Column(db.String(3), default='EUR')  # Code devise ISO
    
    # Statut et prestataire de paiement
    status = db.Column(db.Enum(TransactionStatus), nullable=False, default=TransactionStatus.PENDING)
    payment_gateway = db.Column(db.String(50), nullable=True)  # 'stripe', 'paypal', etc.
    payment_gateway_id = db.Column(db.String(100), nullable=True)  # ID transaction chez le prestataire
    payment_intent_id = db.Column(db.String(100), nullable=True)  # Stripe Payment Intent ID
    
    # Métadonnées
    description = db.Column(db.Text, nullable=True)
    failure_reason = db.Column(db.Text, nullable=True)
    
    # Dates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'idempotency_key': self.idempotency_key,
            'user_id': self.user_id,
            'transaction_type': self.transaction_type,
            'package_name': self.package_name,
            'credits_amount': self.credits_amount,
            'amount_euros': self.amount_cents / 100.0 if self.amount_cents else None,
            'currency': self.currency,
            'status': self.status.value,
            'payment_gateway': self.payment_gateway,
            'payment_gateway_id': self.payment_gateway_id,
            'description': self.description,
            'failure_reason': self.failure_reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'cancelled_at': self.cancelled_at.isoformat() if self.cancelled_at else None
        }

class Notification(db.Model):
    """Modèle pour gérer les notifications utilisateur"""
    __tablename__ = 'notification'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relation utilisateur
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='notifications')
    
    # Contenu de la notification
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.Enum(NotificationType), nullable=False)
    
    # Statut et priorité
    is_read = db.Column(db.Boolean, default=False)
    is_archived = db.Column(db.Boolean, default=False)
    priority = db.Column(db.String(10), default='normal')  # 'low', 'normal', 'high', 'urgent'
    
    # Métadonnées optionnelles pour des actions spécifiques
    related_resource_type = db.Column(db.String(50), nullable=True)  # 'video', 'transaction', 'recording'
    related_resource_id = db.Column(db.String(100), nullable=True)  # ID de la ressource liée
    
    # Actions possibles (pour les notifications interactives)
    action_url = db.Column(db.String(500), nullable=True)  # URL d'action (bouton dans la notification)
    action_label = db.Column(db.String(100), nullable=True)  # Texte du bouton
    
    # Dates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)  # Date d'expiration de la notification
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'message': self.message,
            'notification_type': self.notification_type.value,
            'is_read': self.is_read,
            'is_archived': self.is_archived,
            'priority': self.priority,
            'related_resource_type': self.related_resource_type,
            'related_resource_id': self.related_resource_id,
            'action_url': self.action_url,
            'action_label': self.action_label,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }
        
    def mark_as_read(self):
        """Marquer la notification comme lue"""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()
            
    def is_expired(self):
        """Vérifier si la notification a expiré"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at

class IdempotencyKey(db.Model):
    """Modèle pour gérer l'idempotence des requêtes critiques"""
    __tablename__ = 'idempotency_key'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Optionnel
    endpoint = db.Column(db.String(100), nullable=False)  # Endpoint concerné
    
    # Réponse stockée pour rejouer la même réponse
    response_status_code = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.Text, nullable=True)
    response_headers = db.Column(db.Text, nullable=True)  # JSON stringifié
    
    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)  # Clé expire après 24h
    
    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'user_id': self.user_id,
            'endpoint': self.endpoint,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }
        
    def is_expired(self):
        """Vérifier si la clé d'idempotence a expiré"""
        return datetime.utcnow() > self.expires_at

class SharedVideo(db.Model):
    """Modèle pour gérer le partage de vidéos entre utilisateurs"""
    __tablename__ = 'shared_videos'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Relations
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shared_with_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Métadonnées
    shared_at = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.Text, nullable=True)  # Message optionnel du partageur
    
    # Relations
    video = db.relationship('Video', backref='shared_instances')
    owner = db.relationship('User', foreign_keys=[owner_user_id], backref='videos_shared_by_me')
    shared_with = db.relationship('User', foreign_keys=[shared_with_user_id], backref='videos_shared_with_me')
    
    def to_dict(self):
        """Sérialise en dictionnaire pour l'API"""
        return {
            'id': self.id,
            'video_id': self.video_id,
            'owner_user_id': self.owner_user_id,
            'shared_with_user_id': self.shared_with_user_id,
            'shared_at': self.shared_at.isoformat() if self.shared_at else None,
            'message': self.message,
            'video': self.video.to_dict() if self.video else None,
            'owner': {
                'id': self.owner.id,
                'name': self.owner.name,
                'email': self.owner.email
            } if self.owner else None
        }


# ====================================================================
# CONFIGURATION DE LA SYNCHRONISATION BIDIRECTIONNELLE
# ====================================================================

# Synchronisation User -> Club
@event.listens_for(User, 'after_update')
def sync_user_to_club(mapper, connection, target):
    """Synchronise les changements d'un utilisateur club vers son club"""
    if target.role == UserRole.CLUB and target.club_id:
        try:
            # Cette fonction est appelée dans une transaction, on doit utiliser la session actuelle
            club = db.session.query(Club).get(target.club_id)
            if club:
                changed = False
                
                # Synchroniser les attributs
                if club.name != target.name:
                    club.name = target.name
                    changed = True
                
                if club.email != target.email:
                    club.email = target.email
                    changed = True
                
                if club.phone_number != target.phone_number:
                    club.phone_number = target.phone_number
                    changed = True
                
                # Log des changements
                if changed:
                    logger.info(f"Synchronisation User→Club: Club {club.id} mis à jour depuis User {target.id}")
        except Exception as e:
            logger.error(f"Erreur lors de la synchronisation User→Club: {e}")

# Synchronisation Club -> User
@event.listens_for(Club, 'after_update')
def sync_club_to_user(mapper, connection, target):
    """Synchronise les changements d'un club vers son utilisateur associé"""
    try:
        # Trouver l'utilisateur associé - on doit utiliser la session active
        user = db.session.query(User).filter_by(club_id=target.id, role=UserRole.CLUB).first()
        if user:
            changed = False
            
            # Synchroniser les attributs
            if user.name != target.name:
                user.name = target.name
                changed = True
            
            if user.email != target.email:
                user.email = target.email
                changed = True
            
            if user.phone_number != target.phone_number:
                user.phone_number = target.phone_number
                changed = True
            
            # Log des changements
            if changed:
                logger.info(f"Synchronisation Club→User: User {user.id} mis à jour depuis Club {target.id}")
    except Exception as e:
        logger.error(f"Erreur lors de la synchronisation Club→User: {e}")
