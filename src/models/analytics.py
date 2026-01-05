# padelvar-backend/src/models/analytics.py

from datetime import datetime
from .database import db
from sqlalchemy import Index

class PlatformMetrics(db.Model):
    """Daily aggregated platform-wide metrics for historical tracking"""
    __tablename__ = 'platform_metrics'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    
    # User metrics
    total_users = db.Column(db.Integer, default=0)
    new_users_today = db.Column(db.Integer, default=0)
    active_users_today = db.Column(db.Integer, default=0)
    
    # Club metrics
    total_clubs = db.Column(db.Integer, default=0)
    new_clubs_today = db.Column(db.Integer, default=0)
    
    # Video metrics
    total_videos = db.Column(db.Integer, default=0)
    new_videos_today = db.Column(db.Integer, default=0)
    total_video_views = db.Column(db.Integer, default=0)
    
    # Financial metrics (in cents to avoid floating point issues)
    total_revenue_cents = db.Column(db.Integer, default=0)
    revenue_today_cents = db.Column(db.Integer, default=0)
    commission_earned_cents = db.Column(db.Integer, default=0)
    
    # Recording metrics
    recording_sessions_today = db.Column(db.Integer, default=0)
    total_recording_minutes = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'total_users': self.total_users,
            'new_users_today': self.new_users_today,
            'active_users_today': self.active_users_today,
            'total_clubs': self.total_clubs,
            'new_clubs_today': self.new_clubs_today,
            'total_videos': self.total_videos,
            'new_videos_today': self.new_videos_today,
            'total_video_views': self.total_video_views,
            'total_revenue_euros': self.total_revenue_cents / 100 if self.total_revenue_cents else 0,
            'revenue_today_euros': self.revenue_today_cents / 100 if self.revenue_today_cents else 0,
            'commission_earned_euros': self.commission_earned_cents / 100 if self.commission_earned_cents else 0,
            'recording_sessions_today': self.recording_sessions_today,
            'total_recording_minutes': self.total_recording_minutes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class UserEngagement(db.Model):
    """Track daily user engagement and activity"""
    __tablename__ = 'user_engagement'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    
    # Activity tracking
    login_count = db.Column(db.Integer, default=0)
    videos_watched = db.Column(db.Integer, default=0)
    recordings_started = db.Column(db.Integer, default=0)
    credits_spent = db.Column(db.Integer, default=0)
    
    last_activity_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Composite index for efficient queries
    __table_args__ = (
        Index('idx_user_date', 'user_id', 'date'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'date': self.date.isoformat() if self.date else None,
            'login_count': self.login_count,
            'videos_watched': self.videos_watched,
            'recordings_started': self.recordings_started,
            'credits_spent': self.credits_spent,
            'last_activity_at': self.last_activity_at.isoformat() if self.last_activity_at else None
        }


class ClubPerformance(db.Model):
    """Track per-club performance metrics"""
    __tablename__ = 'club_performance'
    
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    
    # Video metrics
    videos_created_today = db.Column(db.Integer, default=0)
    total_videos = db.Column(db.Integer, default=0)
    total_video_views = db.Column(db.Integer, default=0)
    
    # Revenue metrics (in cents)
    revenue_today_cents = db.Column(db.Integer, default=0)
    total_revenue_cents = db.Column(db.Integer, default=0)
    
    # Usage metrics
    recording_sessions_today = db.Column(db.Integer, default=0)
    total_recording_minutes = db.Column(db.Integer, default=0)
    active_users_count = db.Column(db.Integer, default=0)
    
    # Engagement score (calculated field, 0-100)
    engagement_score = db.Column(db.Float, default=0.0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite index for efficient queries
    __table_args__ = (
        Index('idx_club_date', 'club_id', 'date'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'club_id': self.club_id,
            'date': self.date.isoformat() if self.date else None,
            'videos_created_today': self.videos_created_today,
            'total_videos': self.total_videos,
            'total_video_views': self.total_video_views,
            'revenue_today_euros': self.revenue_today_cents / 100 if self.revenue_today_cents else 0,
            'total_revenue_euros': self.total_revenue_cents / 100 if self.total_revenue_cents else 0,
            'recording_sessions_today': self.recording_sessions_today,
            'total_recording_minutes': self.total_recording_minutes,
            'active_users_count': self.active_users_count,
            'engagement_score': self.engagement_score
        }


class VideoView(db.Model):
    """Track video views for analytics"""
    __tablename__ = 'video_views'
    
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for anonymous views
    
    # View metadata
    view_duration_seconds = db.Column(db.Integer, nullable=True)  # How long they watched
    completed = db.Column(db.Boolean, default=False)  # Did they watch to the end
    
    # Device/location info (optional)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Composite index for efficient queries
    __table_args__ = (
        Index('idx_video_viewed', 'video_id', 'viewed_at'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'video_id': self.video_id,
            'user_id': self.user_id,
            'view_duration_seconds': self.view_duration_seconds,
            'completed': self.completed,
            'viewed_at': self.viewed_at.isoformat() if self.viewed_at else None
        }
