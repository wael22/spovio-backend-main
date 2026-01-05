#!/usr/bin/env python3
"""
Script d'initialisation rapide de la base de données PadelVar
Crée les tables, applique les migrations, et crée des données de test
"""
import os
import sys
import logging

# Ajouter le chemin du projet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask
from src.config import Config
from src.models.database import db
from src.models.user import User, UserStatus, Transaction, TransactionStatus
from src.models.recording import RecordingSession

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    """Crée l'application Flask pour l'initialisation"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Désactiver les logs SQL pour l'initialisation
    app.config['SQLALCHEMY_ECHO'] = False
    
    db.init_app(app)
    return app

def init_database():
    """Initialise la base de données"""
    app = create_app()
    
    with app.app_context():
        try:
            logger.info("🚀 Initialisation de la base de données PadelVar...")
            
            # Vérifier la connexion
            db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
            logger.info(f"📍 Connexion à: {db_uri}")
            
            # Créer toutes les tables
            db.create_all()
            logger.info("✅ Tables créées avec succès")
            
            # Vérifier les tables créées
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            logger.info(f"📊 Tables disponibles: {', '.join(tables)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'initialisation: {e}")
            return False

def create_test_data():
    """Crée des données de test pour le développement"""
    app = create_app()
    
    with app.app_context():
        try:
            logger.info("👥 Création des données de test...")
            
            # Créer un administrateur de test
            admin_email = "admin@mysmash.com"
            if not User.query.filter_by(email=admin_email).first():
                admin = User(
                    email=admin_email,
                    name="Super Admin",
                    role="admin",
                    status=UserStatus.ACTIVE.value if hasattr(UserStatus, 'ACTIVE') else "active",
                    credits=1000
                )
                admin.set_password("admin123")
                db.session.add(admin)
                logger.info(f"✅ Administrateur créé: {admin_email}")
            
            # Créer un club de test
            club_email = "club@mysmash.com"
            if not User.query.filter_by(email=club_email).first():
                club = User(
                    email=club_email,
                    name="Club Test",
                    role="club",
                    status=UserStatus.ACTIVE.value if hasattr(UserStatus, 'ACTIVE') else "active",
                    credits=500
                )
                club.set_password("club123")
                db.session.add(club)
                logger.info(f"✅ Club créé: {club_email}")
            
            # Créer un joueur de test
            player_email = "player@mysmash.com"
            if not User.query.filter_by(email=player_email).first():
                player = User(
                    email=player_email,
                    name="Joueur Test",
                    role="player",
                    status=UserStatus.ACTIVE.value if hasattr(UserStatus, 'ACTIVE') else "active",
                    credits=100
                )
                player.set_password("player123")
                db.session.add(player)
                logger.info(f"✅ Joueur créé: {player_email}")
            
            db.session.commit()
            logger.info("✅ Données de test créées avec succès")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création des données de test: {e}")
            db.session.rollback()
            return False

def show_test_accounts():
    """Affiche les comptes de test créés"""
    logger.info("\n🔑 Comptes de test disponibles:")
    logger.info("  👑 Admin: admin@mysmash.com / admin123")
    logger.info("  🏢 Club: club@mysmash.com / club123") 
    logger.info("  👤 Player: player@mysmash.com / player123")
    logger.info("\n🌐 Démarrez le serveur avec: python src/main.py")

def main():
    """Fonction principale"""
    env = os.environ.get('FLASK_ENV', 'development')
    logger.info(f"🌍 Environnement: {env}")
    
    # Initialiser la base de données
    if not init_database():
        sys.exit(1)
    
    # Créer des données de test en développement
    if env == 'development':
        if create_test_data():
            show_test_accounts()
    
    logger.info("🎉 Initialisation terminée avec succès!")

if __name__ == '__main__':
    main()