"""
Modèles pour le système de notifications
"""
from datetime import datetime
from enum import Enum as PyEnum
from src.models.database import db
from sqlalchemy import Enum
import json

class NotificationType(PyEnum):
    """Types de notifications - must match PostgreSQL enum"""
    VIDEO_READY = "VIDEO_READY"
    RECORDING_STARTED = "RECORDING_STARTED"
    RECORDING_STOPPED = "RECORDING_STOPPED"
    CREDITS_ADDED = "CREDITS_ADDED"
    PAYMENT_SUCCESS = "PAYMENT_SUCCESS"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SYSTEM_MAINTENANCE = "SYSTEM_MAINTENANCE"
    
    # Nouveaux types (à ajouter à l'enum Postgres)
    VIDEO_SHARED = "VIDEO_SHARED"
    SUPPORT = "SUPPORT"
    CREDIT = "CREDIT"  # ✅ Fix: Value found in DB causing crashes

class Notification(db.Model):
    """Modèle pour les notifications utilisateur"""
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    notification_type = db.Column(Enum(NotificationType), nullable=False, default=NotificationType.SYSTEM_MAINTENANCE)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    link = db.Column(db.String(500), nullable=True)  # URL optionnelle
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relations
    user = db.relationship('User', backref='user_notifications', foreign_keys=[user_id])
    
    def to_dict(self):
        """Convertir en dictionnaire"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'type': self.notification_type.value,
            'title': self.title,
            'message': self.message,
            'is_read': self.is_read,
            'link': self.link,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
    
    @staticmethod
    def create_notification(user_id, notification_type, title, message, link=None):
        """Créer une nouvelle notification
        
        Note: Cette méthode N'effectue PAS de commit automatique.
        L'appelant doit faire db.session.commit() pour persister la notification.
        """
        notification = Notification(
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link
        )
        db.session.add(notification)
        # PAS de commit ici - l'appelant doit faire db.session.commit()
        return notification
    
    @staticmethod
    def get_user_notifications(user_id, limit=50, unread_only=False):
        """Récupérer les notifications d'un utilisateur"""
        query = Notification.query.filter_by(user_id=user_id)
        
        if unread_only:
            query = query.filter_by(is_read=False)
        
        return query.order_by(Notification.created_at.desc()).limit(limit).all()
    
    @staticmethod
    def get_unread_count(user_id):
        """Compter les notifications non lues"""
        return Notification.query.filter_by(user_id=user_id, is_read=False).count()
    
    @staticmethod
    def mark_as_read(notification_id, user_id):
        """Marquer une notification comme lue"""
        notification = Notification.query.filter_by(id=notification_id, user_id=user_id).first()
        if notification:
            notification.is_read = True
            db.session.commit()
            return True
        return False
    
    @staticmethod
    def mark_all_as_read(user_id):
        """Marquer toutes les notifications comme lues"""
        Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
        db.session.commit()


class SupportMessageStatus(PyEnum):
    """Statuts des messages support"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

class SupportMessagePriority(PyEnum):
    """Priorités des messages support"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class SupportMessage(db.Model):
    """Modèle pour les messages au support"""
    __tablename__ = 'support_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(Enum(SupportMessageStatus), nullable=False, default=SupportMessageStatus.PENDING)
    priority = db.Column(Enum(SupportMessagePriority), nullable=False, default=SupportMessagePriority.MEDIUM)
    admin_response = db.Column(db.Text, nullable=True)
    responded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    images = db.Column(db.Text, nullable=True)  # JSON array of image URLs
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relations
    user = db.relationship('User', foreign_keys=[user_id], backref='user_support_messages')
    admin = db.relationship('User', foreign_keys=[responded_by], backref='admin_support_responses')
    
    def to_dict(self, include_user=False):
        """Convertir en dictionnaire"""
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'subject': self.subject,
            'message': self.message,
            'status': self.status.value,
            'priority': self.priority.value,
            'admin_response': self.admin_response,
            'responded_by': self.responded_by,
            'images': json.loads(self.images) if self.images else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_user and self.user:
            data['user_name'] = self.user.name
            data['user_email'] = self.user.email
        
        if self.admin:
            data['admin_name'] = self.admin.name
        
        return data
    
    @staticmethod
    def create_message(user_id, subject, message, priority=SupportMessagePriority.MEDIUM):
        """Créer un nouveau message support"""
        support_message = SupportMessage(
            user_id=user_id,
            subject=subject,
            message=message,
            priority=priority
        )
        db.session.add(support_message)
        db.session.commit()
        
        # Créer une notification pour l'utilisateur
        Notification.create_notification(
            user_id=user_id,
            notification_type=NotificationType.SUPPORT,
            title="Message envoyé au support",
            message=f"Votre message '{subject}' a été envoyé au support. Nous vous répondrons dans les plus brefs délais."
        )
        
        return support_message
    
    @staticmethod
    def get_user_messages(user_id):
        """Récupérer les messages d'un utilisateur"""
        return SupportMessage.query.filter_by(user_id=user_id).order_by(SupportMessage.created_at.desc()).all()
    
    @staticmethod
    def get_all_messages(status=None):
        """Récupérer tous les messages (admin)"""
        query = SupportMessage.query
        
        if status:
            query = query.filter_by(status=status)
        
        return query.order_by(SupportMessage.created_at.desc()).all()
    
    @staticmethod
    def update_message(message_id, admin_id, admin_response=None, status=None):
        """Mettre à jour un message support (admin)"""
        message = SupportMessage.query.get(message_id)
        
        if not message:
            return None
        
        if admin_response:
            message.admin_response = admin_response
            message.responded_by = admin_id
            
            # Créer une notification pour l'utilisateur
            Notification.create_notification(
                user_id=message.user_id,
                notification_type=NotificationType.SUPPORT,
                title="Réponse du support",
                message=f"Le support a répondu à votre message: '{message.subject}'"
            )
        
        if status:
            message.status = status
        
        message.updated_at = datetime.utcnow()
        db.session.commit()
        
        return message
