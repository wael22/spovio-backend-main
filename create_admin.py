#!/usr/bin/env python3
"""
Script pour créer un nouveau super admin dans la base de données de production
"""
import sqlite3
from werkzeug.security import generate_password_hash

# Configuration du nouvel admin
NEW_ADMIN_EMAIL = "admin@sopvio.net"
NEW_ADMIN_PASSWORD = "password123"
NEW_ADMIN_NAME = "Super Admin Spovio"
NEW_ADMIN_ROLE = "SUPER_ADMIN"
NEW_ADMIN_CREDITS = 10000

try:
    # Connexion à la base de données
    conn = sqlite3.connect('/app/instance/padelvar.db')
    cursor = conn.cursor()
    
    # Vérifier si l'utilisateur existe déjà
    cursor.execute("SELECT email FROM user WHERE email = ?", (NEW_ADMIN_EMAIL,))
    existing = cursor.fetchone()
    
    if existing:
        print(f"❌ Un utilisateur avec l'email {NEW_ADMIN_EMAIL} existe déjà")
    else:
        # Hasher le mot de passe
        password_hash = generate_password_hash(NEW_ADMIN_PASSWORD)
        
        # Insérer le nouvel admin
        cursor.execute("""
            INSERT INTO user (email, password_hash, name, role, credits_balance, is_verified)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (NEW_ADMIN_EMAIL, password_hash, NEW_ADMIN_NAME, NEW_ADMIN_ROLE, NEW_ADMIN_CREDITS, 1))
        
        conn.commit()
        print(f"✅ Super admin créé avec succès!")
        print(f"   Email: {NEW_ADMIN_EMAIL}")
        print(f"   Nom: {NEW_ADMIN_NAME}")
        print(f"   Mot de passe: {NEW_ADMIN_PASSWORD}")
        print(f"   Rôle: {NEW_ADMIN_ROLE}")
        print(f"   Crédits: {NEW_ADMIN_CREDITS}")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Erreur: {e}")
    if conn:
        conn.rollback()
        conn.close()
