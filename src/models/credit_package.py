from src.models.user import db
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime

class CreditPackage(db.Model):
    """Modèle pour stocker les packages de crédits configurables"""
    __tablename__ = 'credit_package'
    
    id = Column(String(50), primary_key=True)  # Ex: "pack_100", "pack_custom_1"
    credits = Column(Integer, nullable=False)
    price_dt = Column(Integer, nullable=False)  # Prix en Dinars Tunisiens
    package_type = Column(String(20), nullable=False)  # 'player' ou 'club'
    description = Column(String(200))
    is_active = Column(Boolean, default=True, nullable=False)
    is_popular = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convertir le package en dictionnaire"""
        package_dict = {
            'id': self.id,
            'credits': self.credits,
            'price_dt': self.price_dt,
            'type': self.package_type,
            'description': self.description,
            'popular': self.is_popular,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        # Ajouter les champs optionnels pour compatibilité avec l'UI existante
        # Calculer l'économie si c'est un gros package
        if self.package_type == 'player':
            base_price = self.credits * 7  # Prix de base : 7 DT par crédit si acheté à l'unité
            if self.price_dt < base_price:
                package_dict['original_price_dt'] = base_price
                package_dict['savings_dt'] = base_price - self.price_dt
                percentage = int((package_dict['savings_dt'] / base_price) * 100)
                if percentage > 0:
                    package_dict['badge'] = f'Économie {percentage}%'
        elif self.package_type == 'club':
            base_price = self.credits * 7  # Prix de base : 7 DT par crédit
            if self.price_dt < base_price:
                package_dict['original_price_dt'] = base_price
                package_dict['savings_dt'] = base_price - self.price_dt
                percentage = int((package_dict['savings_dt'] / base_price) * 100)
                if percentage > 0:
                    package_dict['badge'] = f'Économie {percentage}%'
        
        return package_dict
    
    def __repr__(self):
        return f'<CreditPackage {self.id}: {self.credits} crédits à {self.price_dt} DT ({self.package_type})>'
