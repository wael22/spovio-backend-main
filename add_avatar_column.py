import sqlite3
import os

# Path to database
db_path = os.path.join('instance', 'padelvar.db')

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Add avatar column
    cursor.execute("ALTER TABLE user ADD COLUMN avatar VARCHAR(255)")
    conn.commit()
    print("✅ Colonne 'avatar' ajoutée avec succès à la table user!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("ℹ️  La colonne 'avatar' existe déjà")
    else:
        print(f"❌ Erreur: {e}")
finally:
    conn.close()
