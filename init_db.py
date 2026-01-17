#!/usr/bin/env python
"""
Script d'initialisation de la base de données pour Railway
Crée toutes les tables et l'utilisateur admin par défaut
"""
import os
import sys
from pathlib import Path

# Ajouter le répertoire parent au path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from src.main import create_app
from src.database import db
from src.models import User

def init_database():
    """Initialise la base de données et crée l'admin par défaut"""
    
    print("🔧 Initialisation de la base de données...")
    
    # Créer l'application
    env = os.environ.get('FLASK_ENV', 'production')
    app = create_app(env)
    
    with app.app_context():
        # Créer toutes les tables
        print("📊 Création des tables...")
        db.create_all()
        print("✅ Tables créées avec succès")
        
        # Vérifier si l'admin existe déjà
        admin_email = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@spovio.net')
        existing_admin = User.query.filter_by(email=admin_email).first()
        
        if existing_admin:
            print(f"ℹ️ Admin {admin_email} existe déjà")
        else:
            # Créer l'admin par défaut
            print(f"👤 Création de l'admin par défaut: {admin_email}")
            
            admin = User(
                email=admin_email,
                name=os.environ.get('DEFAULT_ADMIN_NAME', 'Super Admin'),
                role='SUPER_ADMIN',
                credits=int(os.environ.get('DEFAULT_ADMIN_CREDITS', 10000))
            )
            
            admin_password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'Admin2026!')
            admin.set_password(admin_password)
            
            db.session.add(admin)
            db.session.commit()
            
            print(f"✅ Admin créé: {admin_email}")
            print(f"🔑 Mot de passe: {admin_password}")
        
        print("✅ Initialisation terminée avec succès")

if __name__ == '__main__':
    try:
        init_database()
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
