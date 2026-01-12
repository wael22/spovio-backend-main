"""
Script pour trouver quelle base de données contient la table 'video'
"""
import sqlite3
import os

def check_all_databases():
    """Vérifie toutes les bases de données possibles"""
    
    base_dir = os.path.dirname(__file__)
    db_files = [
        'padelvar.db',
        'instance/padelvar.db',
        'mysmash.db',
        'instance/mysmash.db',
        'app.db',
        'instance/app.db',
    ]
    
    for db_file in db_files:
        db_path = os.path.join(base_dir, db_file)
        if os.path.exists(db_path):
            print(f"\n📁 Base de données: {db_path}")
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Lister toutes les tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                print(f"   Tables: {[t[0] for t in tables]}")
                
                # Vérifier si la table 'video' existe
                if 'video' in [t[0] for t in tables]:
                    print(f"   ✅ Table 'video' trouvée!")
                    
                    # Lister les colonnes de la table video
                    cursor.execute("PRAGMA table_info(video)")
                    columns = cursor.fetchall()
                    print(f"   Colonnes de 'video': {[c[1] for c in columns]}")
                    
                    if 'deleted_at' in [c[1] for c in columns]:
                        print(f"   ✅ Colonne 'deleted_at' existe déjà!")
                    else:
                        print(f"   ❌ Colonne 'deleted_at' manquante - MIGRATION NÉCESSAIRE!")
                
                conn.close()
            except Exception as e:
                print(f"   ❌ Erreur: {e}")

if __name__ == "__main__":
    check_all_databases()
