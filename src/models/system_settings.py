"""
Modèle pour les paramètres système configurables
"""
from src.models.database import db
from datetime import datetime

class SystemSettings(db.Model):
    __tablename__ = 'system_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    welcome_credits = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    @staticmethod
    def get_instance():
        """Récupérer ou créer l'instance unique de SystemSettings"""
        settings = SystemSettings.query.first()
        if not settings:
            settings = SystemSettings(welcome_credits=1)
            db.session.add(settings)
            db.session.commit()
        return settings
    
    @staticmethod
    def get_welcome_credits():
        """Récupérer le nombre de crédits gratuits à donner"""
        return SystemSettings.get_instance().welcome_credits
    
    @staticmethod
    def set_welcome_credits(credits, updated_by_user_id=None):
        """Mettre à jour le nombre de crédits gratuits"""
        settings = SystemSettings.get_instance()
        settings.welcome_credits = credits
        settings.updated_by = updated_by_user_id
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        return settings
    
    def to_dict(self):
        return {
            'id': self.id,
            'welcome_credits': self.welcome_credits,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by': self.updated_by
        }
