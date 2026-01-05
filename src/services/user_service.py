"""
Service pour gérer les opérations liées aux utilisateurs
"""
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from ..models.database import db
from ..models.user import User, UserRole

# Configuration d'un logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class UserService:
    """Service pour gérer les opérations sur les utilisateurs"""
    
    def get_user_by_id(self, user_id):
        """Récupère un utilisateur par son ID"""
        try:
            user = User.query.filter_by(id=user_id).first()
            return user
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération de l'utilisateur par ID: {str(e)}")
            return None
    
    def get_user_by_email(self, email):
        """Récupère un utilisateur par son email"""
        try:
            user = User.query.filter_by(email=email).first()
            return user
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération de l'utilisateur par email: {str(e)}")
            return None
    
    def update_password(self, user_id, new_password):
        """Met à jour le mot de passe d'un utilisateur"""
        try:
            user = self.get_user_by_id(user_id)
            if not user:
                logger.error(f"❌ Utilisateur non trouvé pour l'ID {user_id}")
                return False
            
            # Hasher le nouveau mot de passe
            hashed_password = generate_password_hash(new_password)
            
            # Mettre à jour le mot de passe
            user.password_hash = hashed_password
            db.session.commit()
            
            logger.info(f"✅ Mot de passe mis à jour pour l'utilisateur {user.email}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la mise à jour du mot de passe: {str(e)}")
            db.session.rollback()
            return False
    
    def create_user(self, email, password, name=None, role=UserRole.PLAYER):
        """Crée un nouvel utilisateur"""
        try:
            # Vérifier si l'email existe déjà
            existing_user = self.get_user_by_email(email)
            if existing_user:
                logger.warning(f"⚠️ Un utilisateur avec l'email {email} existe déjà")
                return None
            
            # Hasher le mot de passe
            hashed_password = generate_password_hash(password)
            
            # Créer le nouvel utilisateur
            new_user = User(
                email=email,
                password_hash=hashed_password,
                name=name or email.split('@')[0],
                role=role
            )
            
            db.session.add(new_user)
            db.session.commit()
            
            logger.info(f"✅ Nouvel utilisateur créé: {email}")
            return new_user
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création de l'utilisateur: {str(e)}")
            db.session.rollback()
            return None
    
    def verify_password(self, user, password):
        """Vérifie si le mot de passe correspond à celui de l'utilisateur"""
        try:
            if not user:
                return False
            
            return check_password_hash(user.password_hash, password)
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la vérification du mot de passe: {str(e)}")
            return False
    
    def get_user_profile(self, user_id):
        """Récupère le profil complet d'un utilisateur"""
        try:
            user = self.get_user_by_id(user_id)
            if not user:
                return None
            
            # Construire le profil (à personnaliser selon les besoins)
            profile = {
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'role': user.role.name,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None
            }
            
            return profile
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération du profil utilisateur: {str(e)}")
            return None
