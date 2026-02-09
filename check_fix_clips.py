import sqlite3
import sys

def check_and_fix_clips():
    try:
        conn = sqlite3.connect('/app/instance/padelvar.db')
        cursor = conn.cursor()
        
        # Check recent clips
        cursor.execute("SELECT id, title, file_url FROM user_clip ORDER BY id DESC LIMIT 5")
        clips = cursor.fetchall()
        
        print("📋 Recent clips:")
        for clip_id, title, url in clips:
            hostname = "UNKNOWN"
            if url:
                if "vz-cc4565cd-4e9" in url:
                    hostname = "OLD (vz-cc4565cd-4e9)"
                elif "vz-9b857324-07d" in url:
                    hostname = "NEW (vz-9b857324-07d)"
            print(f"  ID {clip_id}: {title} -> {hostname}")
            if url:
                print(f"     URL: {url[:80]}...")
        
        # Count clips with old hostname
        cursor.execute("SELECT COUNT(*) FROM user_clip WHERE file_url LIKE '%vz-cc4565cd-4e9%'")
        old_count = cursor.fetchone()[0]
        print(f"\n📊 Clips with old hostname: {old_count}")
        
        if old_count > 0:
            print(f"\n🔧 Updating {old_count} clips...")
            cursor.execute("""
                UPDATE user_clip 
                SET file_url = REPLACE(file_url, 'vz-cc4565cd-4e9.b-cdn.net', 'vz-9b857324-07d.b-cdn.net')
                WHERE file_url LIKE '%vz-cc4565cd-4e9%'
            """)
            conn.commit()
            print(f"✅ Updated {cursor.rowcount} clips")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_and_fix_clips()
