#!/usr/bin/env python3
"""
Script de création d'un administrateur PadelVar
Usage: python scripts/create_admin.py [email] [password] [name]
"""
import os
import sys
from pathlib import Path
import argparse

# Ajouter le dossier racine au path
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

from src.main import create_app, create_admin

def main():
    """Crée un administrateur"""
    parser = argparse.ArgumentParser(description='Créer un administrateur PadelVar')
    parser.add_argument('email', help='Email de l\'administrateur')
    parser.add_argument('password', help='Mot de passe de l\'administrateur')
    parser.add_argument('--name', default='Admin', help='Nom de l\'administrateur (défaut: Admin)')
    
    args = parser.parse_args()
    
    print(f"👤 Création d'un administrateur PadelVar")
    print(f"   Email: {args.email}")
    print(f"   Nom: {args.name}")
    
    # Créer l'application
    app = create_app('development')
    
    # Créer l'administrateur
    success = create_admin(app, args.email, args.password, args.name)
    
    if success:
        print("✅ Administrateur créé avec succès")
    else:
        print("❌ Échec de la création de l'administrateur")
        sys.exit(1)

if __name__ == '__main__':
    main()

