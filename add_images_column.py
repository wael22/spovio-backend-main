import sqlite3
import os

# Path to database
db_path = os.path.join('instance', 'mysmash.db')

# Connect to database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Add images column
    cursor.execute("ALTER TABLE support_messages ADD COLUMN images TEXT")
    conn.commit()
    print("✅ Colonne 'images' ajoutée avec succès à support_messages!")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("ℹ️  La colonne 'images' existe déjà")
    else:
        print(f"❌ Erreur: {e}")
finally:
    conn.close()
