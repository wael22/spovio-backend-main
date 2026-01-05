import sqlite3
import os
from datetime import datetime

def analyze_database(db_path):
    """Analyse une base de données SQLite et retourne ses informations."""
    if not os.path.exists(db_path):
        return None
    
    size = os.path.getsize(db_path)
    if size == 0:
        return {"path": db_path, "size": 0, "tables": [], "empty": True}
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Liste des tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cursor.fetchall()]
    
    # Pour chaque table, compter les lignes et obtenir le schéma
    table_info = {}
    for table in tables:
        cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
        count = cursor.fetchone()[0]
        
        cursor.execute(f'PRAGMA table_info("{table}")')
        columns = cursor.fetchall()
        
        table_info[table] = {
            "row_count": count,
            "columns": [(col[1], col[2]) for col in columns]  # (name, type)
        }
    
    conn.close()
    
    return {
        "path": db_path,
        "size": size,
        "tables": tables,
        "table_info": table_info,
        "empty": False
    }

# Analyser toutes les bases de données
databases = [
    "instance/padelvar.db",
    "instance/app.db",
    "app.db",
    "padelvar.db"
]

print("=" * 80)
print("DIAGNOSTIC DES BASES DE DONNÉES - PADELVAR")
print("=" * 80)
print()

for db_path in databases:
    print(f"\n{'=' * 80}")
    print(f"📊 BASE DE DONNÉES: {db_path}")
    print(f"{'=' * 80}")
    
    info = analyze_database(db_path)
    
    if info is None:
        print(f"❌ N'existe pas")
        continue
    
    if info["empty"]:
        print(f"⚠️  Fichier vide (0 bytes)")
        continue
    
    print(f"📏 Taille: {info['size']:,} bytes ({info['size']/1024:.2f} KB)")
    print(f"📋 Nombre de tables: {len(info['tables'])}")
    print()
    
    if info['tables']:
        for table in info['tables']:
            table_data = info['table_info'][table]
            print(f"\n  🗂️  Table: {table}")
            print(f"     Lignes: {table_data['row_count']}")
            print(f"     Colonnes ({len(table_data['columns'])}):")
            for col_name, col_type in table_data['columns']:
                print(f"       - {col_name}: {col_type}")
    else:
        print("  ⚠️  Aucune table trouvée")

print("\n" + "=" * 80)
print("RÉSUMÉ")
print("=" * 80)

# Trouver la base de données active
active_db = None
max_size = 0
for db_path in databases:
    info = analyze_database(db_path)
    if info and not info["empty"] and info["size"] > max_size:
        max_size = info["size"]
        active_db = db_path

if active_db:
    print(f"\n✅ BASE DE DONNÉES ACTIVE (la plus volumineuse): {active_db}")
    print(f"   Taille: {max_size:,} bytes ({max_size/1024:.2f} KB)")
else:
    print("\n❌ Aucune base de données active trouvée")
