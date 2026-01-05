"""Create shared_videos table for video sharing functionality

Migration pour créer la table shared_videos qui permet aux utilisateurs
de partager leurs vidéos avec d'autres utilisateurs.
"""

from datetime import datetime
from src.models.database import db
from src.models.user import User

def upgrade():
    """Create shared_videos table"""
    
    # Créer la table shared_videos
    db.engine.execute("""
        CREATE TABLE IF NOT EXISTS shared_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL,
            owner_user_id INTEGER NOT NULL,
            shared_with_user_id INTEGER NOT NULL,
            shared_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            message TEXT,
            FOREIGN KEY (video_id) REFERENCES video(id) ON DELETE CASCADE,
            FOREIGN KEY (owner_user_id) REFERENCES user(id) ON DELETE CASCADE,
            FOREIGN KEY (shared_with_user_id) REFERENCES user(id) ON DELETE CASCADE,
            UNIQUE (video_id, shared_with_user_id)
        )
    """)
    
    print("✅ Table shared_videos créée avec succès")

def downgrade():
    """Drop shared_videos table"""
    db.engine.execute("DROP TABLE IF EXISTS shared_videos")
    print("✅ Table shared_videos supprimée")

if __name__ == '__main__':
    print("🔄 Exécution de la migration: add_shared_videos_table")
    print("=" * 60)
    
    # Import de l'application Flask pour accéder au contexte
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
    
    from app import app
    
    with app.app_context():
        try:
            upgrade()
            print("\n✅ Migration terminée avec succès!")
        except Exception as e:
            print(f"\n❌ Erreur lors de la migration: {e}")
            import traceback
            traceback.print_exc()
