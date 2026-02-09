#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('instance/padelvar.db')
cursor = conn.cursor()

# Update clips
cursor.execute("""
    UPDATE user_clip 
    SET file_url = REPLACE(file_url, 'vz-cc4565cd-4e9.b-cdn.net', 'vz-9b857324-07d.b-cdn.net')
    WHERE file_url LIKE '%vz-cc4565cd-4e9%'
""")
print(f"✅ Updated {cursor.rowcount} clips")

# Update videos
cursor.execute("""
    UPDATE video 
    SET file_url = REPLACE(file_url, 'vz-cc4565cd-4e9.b-cdn.net', 'vz-9b857324-07d.b-cdn.net')
    WHERE file_url LIKE '%vz-cc4565cd-4e9%'
""")
print(f"✅ Updated {cursor.rowcount} videos")

conn.commit()
conn.close()
print("🚀 Migration complete!")
