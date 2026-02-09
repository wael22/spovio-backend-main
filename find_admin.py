#!/usr/bin/env python3
import sqlite3

try:
    conn = sqlite3.connect('instance/padelvar.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT email, name, role FROM user WHERE role LIKE '%super_admin%' OR role LIKE '%SUPER_ADMIN%'")
    results = cursor.fetchall()
    
    if results:
        print("Super Admins trouvés:")
        for email, name, role in results:
            print(f"  Email: {email}")
            print(f"  Nom: {name}")
            print(f"  Rôle: {role}")
            print("---")
    else:
        print("Aucun super admin trouvé")
    
    conn.close()
except Exception as e:
    print(f"Erreur: {e}")
