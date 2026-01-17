"""
Migration: Update CDN hostname in existing video URLs
Replace old hostname vz-f6fd0c7d-d70.b-cdn.net with new vz-cc4565cd-4e9.b-cdn.net
"""

import sqlite3
import os

def update_cdn_hostname():
    """Met à jour le hostname CDN dans les URLs des vidéos existantes"""
    
    db_path = 'instance/padelvar.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Base de données introuvable: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("🔍 Recherche des vidéos avec ancien hostname...")
        
        # Compter les vidéos concernées
        cursor.execute("""
            SELECT COUNT(*) FROM video 
            WHERE file_url LIKE '%vz-f6fd0c7d-d70.b-cdn.net%'
        """)
        count_before = cursor.fetchone()[0]
        print(f"   Trouvé {count_before} vidéos avec ancien hostname")
        
        # Compter les clips concernés  
        cursor.execute("""
            SELECT COUNT(*) FROM user_clip 
            WHERE file_url LIKE '%vz-f6fd0c7d-d70.b-cdn.net%'
        """)
        clips_count = cursor.fetchone()[0]
        print(f"   Trouvé {clips_count} clips avec ancien hostname")
        
        if count_before == 0 and clips_count == 0:
            print("✅ Aucune mise à jour nécessaire")
            conn.close()
            return True
        
        # Mettre à jour les vidéos
        if count_before > 0:
            print(f"\n📝 Mise à jour de {count_before} vidéos...")
            cursor.execute("""
                UPDATE video 
                SET file_url = REPLACE(file_url, 'vz-f6fd0c7d-d70.b-cdn.net', 'vz-cc4565cd-4e9.b-cdn.net')
                WHERE file_url LIKE '%vz-f6fd0c7d-d70.b-cdn.net%'
            """)
            conn.commit()
            print(f"✅ {cursor.rowcount} vidéos mises à jour")
        
        # Mettre à jour les clips
        if clips_count > 0:
            print(f"\n📝 Mise à jour de {clips_count} clips...")
            cursor.execute("""
                UPDATE user_clip 
                SET file_url = REPLACE(file_url, 'vz-f6fd0c7d-d70.b-cdn.net', 'vz-cc4565cd-4e9.b-cdn.net')
                WHERE file_url LIKE '%vz-f6fd0c7d-d70.b-cdn.net%'
            """)
            conn.commit()
            print(f"✅ {cursor.rowcount} clips mis à jour")
        
        # Vérifier
        cursor.execute("""
            SELECT COUNT(*) FROM video 
            WHERE file_url LIKE '%vz-f6fd0c7d-d70.b-cdn.net%'
        """)
        count_after = cursor.fetchone()[0]
        
        print(f"\n✅ Migration terminée")
        print(f"   Avant: {count_before} vidéos + {clips_count} clips")
        print(f"   Après: {count_after} avec ancien hostname")
        
        # Afficher quelques exemples de nouvelles URLs
        print("\n📋 Exemples de nouvelles URLs:")
        cursor.execute("""
            SELECT id, title, file_url 
            FROM video 
            WHERE file_url LIKE '%vz-cc4565cd-4e9.b-cdn.net%'
            LIMIT 3
        """)
        for row in cursor.fetchall():
            print(f"   Video {row[0]}: {row[2][:70]}...")
        
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
    print("Migration: Mise à jour du hostname CDN")
    print("="*60)
    print()
    
    success = update_cdn_hostname()
    
    print()
    if success:
        print("✅ Migration réussie!")
        print("\n📌 Action requise:")
        print("   Redémarrez le backend pour appliquer les changements")
        print("   Les vidéos utiliseront le nouveau hostname CDN")
    else:
        print("❌ Migration échouée")
    
    print("="*60)
