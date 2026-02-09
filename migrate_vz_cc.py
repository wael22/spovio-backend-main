import sqlite3
import os

def migrate():
    db_path = '/home/ubuntu/spovio/backend/instance/padelvar.db'
    if not os.path.exists(db_path):
        db_path = 'instance/padelvar.db' # Fallback for local
        
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    old_host = 'vz-cc4565cd-4e9.b-cdn.net'
    new_host = 'vz-9b857324-07d.b-cdn.net'

    print(f"🔄 Migrating {old_host} -> {new_host}")

    # Update Video table
    cursor.execute("UPDATE video SET file_url = REPLACE(file_url, ?, ?) WHERE file_url LIKE ?", 
                   (old_host, new_host, f'%{old_host}%'))
    print(f"✅ Updated {cursor.rowcount} videos")

    # Update UserClip table
    cursor.execute("UPDATE user_clip SET file_url = REPLACE(file_url, ?, ?) WHERE file_url LIKE ?", 
                   (old_host, new_host, f'%{old_host}%'))
    print(f"✅ Updated {cursor.rowcount} clips")

    conn.commit()
    conn.close()
    print("🚀 Migration complete!")

if __name__ == "__main__":
    migrate()
