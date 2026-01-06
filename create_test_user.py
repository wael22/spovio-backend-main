#!/usr/bin/env python3
"""
Script pour créer un compte de test directement dans la DB locale
Usage: python create_test_user.py
"""

import sys
import os
from datetime import datetime

# Ajouter le répertoire src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.models.database import db
from src.models.user import User, UserRole
from src.main import create_app
from werkzeug.security import generate_password_hash

def create_test_user():
    """Créer un utilisateur de test avec email vérifié"""
    
    # Configurer l'app pour accéder à la DB
    app = create_app()
    
    with app.app_context():
        # Paramètres du compte de test
        email = "test@mysmash.com"
        password = "test1234"
        name = "Test User"
        
        print(f"\n🔍 Vérification si l'utilisateur existe déjà...")
        existing_user = User.query.filter_by(email=email).first()
        
        if existing_user:
            print(f"❌ L'utilisateur {email} existe déjà!")
            print(f"   ID: {existing_user.id}")
            print(f"   Nom: {existing_user.name}")
            print(f"   Email vérifié: {existing_user.email_verified}")
            print(f"   Crédits: {existing_user.credits_balance}")
            
            # Proposer de supprimer
            choice = input("\n❓ Voulez-vous supprimer cet utilisateur et en créer un nouveau? (o/N): ")
            if choice.lower() == 'o':
                db.session.delete(existing_user)
                db.session.commit()
                print("✅ Utilisateur supprimé!")
            else:
                print("⏭️  Annulé. Utilisateur existant conservé.")
                return
        
        # Créer le nouvel utilisateur
        print(f"\n🚀 Création du compte de test...")
        print(f"   Email: {email}")
        print(f"   Mot de passe: {password}")
        print(f"   Nom: {name}")
        
        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            name=name,
            phone_number=None,
            role=UserRole.PLAYER,
            credits_balance=100,  # Crédits de bienvenue
            email_verified=True,  # ✅ Email déjà vérifié!
            email_verified_at=datetime.utcnow(),
            email_verification_token=None  # Pas besoin de code
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        print(f"\n✅✅✅ Compte créé avec succès! ✅✅✅")
        print(f"\n📋 Informations du compte:")
        print(f"   ID: {new_user.id}")
        print(f"   Email: {new_user.email}")
        print(f"   Nom: {new_user.name}")
        print(f"   Rôle: {new_user.role.value}")
        print(f"   Crédits: {new_user.credits_balance}")
        print(f"   Email vérifié: ✅ OUI")
        print(f"\n🔐 Credentials pour se connecter:")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print(f"\n🌐 Testez sur: http://localhost:5173/auth")

def create_test_user_with_verification():
    """Créer un utilisateur de test SANS email vérifié (pour tester la vérification)"""
    
    app = create_app()
    
    with app.app_context():
        email = "unverified@mysmash.com"
        password = "test1234"
        name = "Unverified User"
        verification_code = "123456"  # Code fixe pour test
        
        print(f"\n🔍 Vérification si l'utilisateur existe déjà...")
        existing_user = User.query.filter_by(email=email).first()
        
        if existing_user:
            db.session.delete(existing_user)
            db.session.commit()
            print("✅ Ancien utilisateur supprimé!")
        
        print(f"\n🚀 Création du compte NON vérifié...")
        print(f"   Email: {email}")
        print(f"   Mot de passe: {password}")
        print(f"   Code de vérification: {verification_code}")
        
        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            name=name,
            phone_number=None,
            role=UserRole.PLAYER,
            credits_balance=100,
            email_verified=False,  # ❌ Pas encore vérifié
            email_verification_token=verification_code,
            email_verification_sent_at=datetime.utcnow()
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        print(f"\n✅✅✅ Compte NON vérifié créé! ✅✅✅")
        print(f"\n📋 Informations:")
        print(f"   Email: {email}")
        print(f"   Password: {password}")
        print(f"   Code de vérification: {verification_code}")
        print(f"   Email vérifié: ❌ NON")
        print(f"\n🧪 Pour tester:")
        print(f"   1. Essayer de se connecter → Devrait bloquer")
        print(f"   2. Entrer le code: {verification_code}")
        print(f"   3. Email vérifié → Login devrait marcher")

if __name__ == "__main__":
    print("="*60)
    print("🎯 CRÉATION DE COMPTES DE TEST DANS LA DB LOCALE")
    print("="*60)
    print("\nOptions:")
    print("  1. Créer un compte VÉRIFIÉ (prêt à utiliser)")
    print("  2. Créer un compte NON VÉRIFIÉ (pour tester la vérification)")
    print("  3. Les deux")
    
    choice = input("\nVotre choix (1/2/3): ").strip()
    
    if choice == "1":
        create_test_user()
    elif choice == "2":
        create_test_user_with_verification()
    elif choice == "3":
        create_test_user()
        print("\n" + "="*60 + "\n")
        create_test_user_with_verification()
    else:
        print("❌ Choix invalide!")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("✅ Terminé!")
    print("="*60)
