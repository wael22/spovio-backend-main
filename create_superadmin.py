#!/usr/bin/env python3
"""
Script pour créer un nouveau super admin en utilisant l'ORM SQLAlchemy
Cela garantit que l'énumération UserRole est correctement gérée
"""
import sys
import os
from pathlib import Path

# Ajouter le répertoire parent au path pour les imports
sys.path.insert(0, '/app')

# Chargement des variables d'environnement depuis .env si le fichier existe
project_root = Path(__file__).parent.absolute()
env_file = project_root / '.env'
if env_file.exists():
    print(f"📁 Chargement des variables d'environnement depuis {env_file}")
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

from werkzeug.security import generate_password_hash
from src.models.user import User, UserRole, UserStatus
from src.models.database import db
from src.main import create_app

# Configuration du nouveau super admin
NEW_ADMIN_EMAIL = "superadmin@spovio.net"
NEW_ADMIN_PASSWORD = "Spovio2024!"
NEW_ADMIN_NAME = "Super Admin Spovio"
NEW_ADMIN_CREDITS = 10000

def create_super_admin():
    try:
        # Créer l'application Flask
        app = create_app('production')
        
        with app.app_context():
            # Vérifier si l'utilisateur existe déjà
            existing = User.query.filter_by(email=NEW_ADMIN_EMAIL).first()
            
            if existing:
                print(f"❌ Un utilisateur avec l'email {NEW_ADMIN_EMAIL} existe déjà")
                print(f"   ID: {existing.id}, Role: {existing.role}, Nom: {existing.name}")
                return False
            
            # Créer le nouveau super admin avec l'ORM
            new_admin = User(
                email=NEW_ADMIN_EMAIL,
                password_hash=generate_password_hash(NEW_ADMIN_PASSWORD),
                name=NEW_ADMIN_NAME,
                role=UserRole.SUPER_ADMIN,  # Utiliser l'énumération directement
                status=UserStatus.ACTIVE,
                credits_balance=NEW_ADMIN_CREDITS,
                email_verified=True
            )
            
            # Ajouter à la base de données
            db.session.add(new_admin)
            db.session.commit()
            
            print("✅ Super admin créé avec succès!")
            print(f"   Email: {NEW_ADMIN_EMAIL}")
            print(f"   Nom: {NEW_ADMIN_NAME}")
            print(f"   Mot de passe: {NEW_ADMIN_PASSWORD}")
            print(f"   Rôle: {new_admin.role}")
            print(f"   Rôle (valeur): {new_admin.role.value}")
            print(f"   ID: {new_admin.id}")
            print(f"   Crédits: {NEW_ADMIN_CREDITS}")
            
            return True
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    create_super_admin()
