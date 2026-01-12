import sqlite3
import os
from datetime import datetime

def add_file_tracking_columns():
    """
    Ajoute les colonnes de tracking pour les fichiers locaux et cloud
    """
    databases = [
        'instance/padelvar.db',
        'instance/app.db'
    ]
    
    for db_path in databases:
        if not os.path.exists(db_path):
            print(f"⚠️ Base de données {db_path} introuvable, passage...")
            continue
        
        print(f"\n📊 Traitement de {db_path}...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Vérifier si la table video existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='video'")
        if not cursor.fetchone():
            print(f"⚠️ Table 'video' introuvable dans {db_path}")
            conn.close()
            continue
        
        # Ajouter colonne local_file_path
        try:
            cursor.execute("""
                ALTER TABLE video 
                ADD COLUMN local_file_path TEXT
            """)
            print("✅ Colonne 'local_file_path' ajoutée")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("⚠️ Colonne 'local_file_path' existe déjà")
            else:
                print(f"❌ Erreur: {e}")
        
        # Ajouter colonne local_file_deleted_at
        try:
            cursor.execute("""
                ALTER TABLE video 
                ADD COLUMN local_file_deleted_at TIMESTAMP
            """)
            print("✅ Colonne 'local_file_deleted_at' ajoutée")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("⚠️ Colonne 'local_file_deleted_at' existe déjà")
            else:
                print(f"❌ Erreur: {e}")
        
        # Ajouter colonne cloud_deleted_at
        try:
            cursor.execute("""
                ALTER TABLE video 
                ADD COLUMN cloud_deleted_at TIMESTAMP
            """)
            print("✅ Colonne 'cloud_deleted_at' ajoutée")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print("⚠️ Colonne 'cloud_deleted_at' existe déjà")
            else:
                print(f"❌ Erreur: {e}")
        
        conn.commit()
        
        # Vérifier les colonnes ajoutées
        cursor.execute("PRAGMA table_info(video)")
        columns = cursor.fetchall()
        video_columns = [col[1] for col in columns]
        
        print(f"\n📋 Colonnes de tracking présentes:")
        print(f"   - local_file_path: {'✅' if 'local_file_path' in video_columns else '❌'}")
        print(f"   - local_file_deleted_at: {'✅' if 'local_file_deleted_at' in video_columns else '❌'}")
        print(f"   - cloud_deleted_at: {'✅' if 'cloud_deleted_at' in video_columns else '❌'}")
        
        conn.close()
        print(f"✅ Migration terminée pour {db_path}")

if __name__ == '__main__':
    print("=" * 60)
    print(" MIGRATION: Ajout colonnes de tracking fichiers")
    print("=" * 60)
    add_file_tracking_columns()
    print("\n" + "=" * 60)
    print(" ✅ MIGRATION TERMINÉE")
    print("=" * 60)
