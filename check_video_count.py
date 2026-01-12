import sqlite3
import os

db_path = 'instance/padelvar.db'

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=== VIDEO COUNT PAR UTILISATEUR ===")
    cursor.execute("""
        SELECT u.id, u.name, u.email, COUNT(v.id) as video_count
        FROM user u
        LEFT JOIN video v ON v.user_id = u.id
        GROUP BY u.id
        ORDER BY video_count DESC
        LIMIT 15
    """)
    
    results = cursor.fetchall()
    for row in results:
        print(f"User {row[0]} - {row[1]}: {row[3]} vidéos")
    
    print("\n=== VIDEO COUNT PAR CLUB ===")
    cursor.execute("""
        SELECT c.id, c.name, COUNT(v.id) as video_count
        FROM club c
        LEFT JOIN court co ON co.club_id = c.id
        LEFT JOIN video v ON v.court_id = co.id
        GROUP BY c.id
        ORDER BY video_count DESC
    """)
    
    results = cursor.fetchall()
    for row in results:
        print(f"Club {row[0]} - {row[1]}: {row[2]} vidéos")
    
    conn.close()
else:
    print(f"Base de données {db_path} introuvable")
