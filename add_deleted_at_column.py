"""
Migration: Ajouter la colonne deleted_at à la table video pour le soft delete
"""
import sqlite3
import os
from datetime import datetime

def migrate_database(db_path):
    """Ajoute la colonne deleted_at à une base de données"""
    
    print(f"\n📁 Migration de: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Vérifier si la colonne existe déjà
        cursor.execute("PRAGMA table_info(video)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'deleted_at' in columns:
            print("   ✅ La colonne 'deleted_at' existe déjà")
            conn.close()
            return True
        
        # Ajouter la colonne deleted_at
        print("   📝 Ajout de la colonne 'deleted_at'...")
        cursor.execute("""
            ALTER TABLE video 
            ADD COLUMN deleted_at DATETIME NULL
        """)
        
        conn.commit()
        print("   ✅ Colonne 'deleted_at' ajoutée avec succès!")
        
        # Vérifier
        cursor.execute("PRAGMA table_info(video)")
        columns_after = [column[1] for column in cursor.fetchall()]
        
        if 'deleted_at' in columns_after:
            print("   ✅ Migration réussie!")
        else:
            print("   ❌ Erreur - La colonne n'a pas été ajoutée")
            return False
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"   ❌ Erreur lors de la migration: {e}")
        return False

def add_deleted_at_column():
    """Ajoute la colonne deleted_at à toutes les bases de données"""
    
    # Chercher les bases de données avec la table video
    base_dir = os.path.dirname(__file__)
    db_files = [
        'instance/padelvar.db',
        'instance/app.db',
        'instance/mysmash.db',
    ]
    
    migrated_count = 0
    error_count = 0
    
    for db_file in db_files:
        db_path = os.path.join(base_dir, db_file)
        if os.path.exists(db_path):
            # Vérifier si la table video existe
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='video';")
                has_video_table = cursor.fetchone() is not None
                conn.close()
                
                if has_video_table:
                    if migrate_database(db_path):
                        migrated_count += 1
                    else:
                        error_count += 1
            except Exception as e:
                print(f"   ❌ Erreur lors de la vérification de {db_path}: {e}")
                error_count += 1
    
    return migrated_count, error_count

if __name__ == "__main__":
    print("🚀 Démarrage de la migration...")
    print(f"⏰ Heure: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    migrated, errors = add_deleted_at_column()
    
    print()
    print(f"📊 Résultats:")
    print(f"   ✅ Bases de données migrées: {migrated}")
    print(f"   ❌ Erreurs: {errors}")
    print()
    
    if migrated > 0 and errors == 0:
        print("✅ Migration terminée avec succès!")
        print("🔄 Redémarrez l'application Flask pour appliquer les changements")
    elif errors > 0:
        print("⚠️ La migration a rencontré des erreurs")
    else:
        print("ℹ️ Aucune base de données à migrer")

