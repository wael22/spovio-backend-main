import sqlite3
import os

# Try all possible database locations
db_paths = [
    'padelvar.db',
    'instance/padelvar.db', 
    'instance/app.db',
    'app.db'
]

for db_path in db_paths:
    if os.path.exists(db_path):
        print(f"\n🔍 Fichier trouvé: {db_path}")
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='support_messages'")
            if cursor.fetchone():
                print(f"✅ Table support_messages existe dans {db_path}")
                
                # Try to add column
                try:
                    cursor.execute("ALTER TABLE support_messages ADD COLUMN images TEXT")
                    conn.commit()
                    print(f"✅ Colonne 'images' ajoutée avec succès à {db_path}!")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e).lower():
                        print(f"ℹ️  La colonne 'images' existe déjà dans {db_path}")
                    else:
                        print(f"❌ Erreur: {e}")
            else:
                print(f"❌ Table support_messages n'existe pas dans {db_path}")
                
            conn.close()
        except Exception as e:
            print(f"❌ Erreur avec {db_path}: {e}")
    else:
        print(f"❌ Fichier non trouvé: {db_path}")

print("\n✅ Terminé!")
