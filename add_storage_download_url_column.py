"""
Migration: Add storage_download_url column to user_clip table
Permet de stocker l'URL de téléchargement MP4 depuis Bunny Storage (en plus du streaming HLS)
"""

import sqlite3
import os

def add_storage_download_url_column():
    """Ajoute la colonne storage_download_url à la table user_clip"""
    
    # Chemins possibles pour la base de données (ordre de priorité)
    db_paths = [
        'instance/padelvar.db',  # Base de données principale
        'instance/app.db',
        'app.db',
        'padelvar.db'
    ]
    
    # Trouver la base de données active
    db_path = None
    for path in db_paths:
        if os.path.exists(path):
            db_path = path
            print(f"✅ Base de données trouvée: {path}")
            break
    
    if not db_path:
        print("❌ Aucune base de données trouvée!")
        print(f"   Chemins recherchés: {db_paths}")
        return False
    
    try:
        # Connexion à la base de données
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"📊 Connexion à {db_path}...")
        
        # Vérifier si la table user_clip existe
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='user_clip'
        """)
        
        if not cursor.fetchone():
            print("❌ Table user_clip n'existe pas!")
            conn.close()
            return False
        
        # Vérifier si la colonne existe déjà
        cursor.execute("PRAGMA table_info(user_clip)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'storage_download_url' in columns:
            print("ℹ️  La colonne storage_download_url existe déjà")
            conn.close()
            return True
        
        # Ajouter la colonne
        print("📝 Ajout de la colonne storage_download_url...")
        cursor.execute("""
            ALTER TABLE user_clip 
            ADD COLUMN storage_download_url VARCHAR(500) DEFAULT NULL
        """)
        
        conn.commit()
        print("✅ Colonne storage_download_url ajoutée avec succès!")
        
        # Vérifier que la colonne a été ajoutée
        cursor.execute("PRAGMA table_info(user_clip)")
        columns_after = [column[1] for column in cursor.fetchall()]
        
        if 'storage_download_url' in columns_after:
            print("✅ Vérification: Colonne présente dans la table")
        else:
            print("⚠️  Attention: La colonne n'apparaît pas dans la table")
        
        # Afficher le schéma mis à jour
        print("\n📋 Colonnes de la table user_clip:")
        cursor.execute("PRAGMA table_info(user_clip)")
        for col in cursor.fetchall():
            col_name = col[1]
            col_type = col[2]
            marker = "🆕" if col_name == 'storage_download_url' else "  "
            print(f"   {marker} {col_name}: {col_type}")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Erreur SQLite: {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

if __name__ == "__main__":
    print("="*60)
    print("Migration: Ajout storage_download_url à user_clip")
    print("="*60)
    print()
    
    success = add_storage_download_url_column()
    
    print()
    if success:
        print("✅ Migration terminée avec succès!")
        print()
        print("📌 Prochaines étapes:")
        print("   1. Redémarrer le backend (python app.py)")
        print("   2. Créer un clip de test")
        print("   3. Vérifier que storage_download_url est bien rempli")
    else:
        print("❌ Migration échouée")
    
    print("="*60)
