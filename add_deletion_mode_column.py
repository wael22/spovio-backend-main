"""
Migration: Ajouter colonne deletion_mode à la table video
"""
import sqlite3
import os

def add_deletion_mode_column():
    # Chemins des bases de données
    db_paths = [
        'instance/padelvar.db',
        'instance/app.db'
    ]
    
    for db_path in db_paths:
        if not os.path.exists(db_path):
            print(f"⏭️  Base de données {db_path} n'existe pas, ignorée")
            continue
            
        print(f"\n📂 Traitement de {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            # Vérifier si la colonne existe déjà
            cursor.execute("PRAGMA table_info(video)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'deletion_mode' in columns:
                print(f"   ✅ Colonne deletion_mode existe déjà")
            else:
                # Ajouter la colonne
                cursor.execute("""
                    ALTER TABLE video 
                    ADD COLUMN deletion_mode VARCHAR(20) NULL
                """)
                conn.commit()
                print(f"   ✅ Colonne deletion_mode ajoutée")
            
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    print("\n✅ Migration terminée")

if __name__ == "__main__":
    add_deletion_mode_column()
