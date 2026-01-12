"""
Script pour marquer les vidéos supprimées de Bunny comme 'failed'
Utilisation: python fix_bunny_404_videos.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.main import create_app
from src.models.database import db
from src.models.user import Video

def fix_bunny_404_videos():
    """Marque les vidéos 77 et 78 comme failed (supprimées de Bunny)"""
    
    app = create_app('development')
    
    with app.app_context():
        # IDs des vidéos qui retournent 404 sur Bunny
        video_ids = [77, 78]
        
        print("🔧 Correction des vidéos supprimées de Bunny...")
        print()
        
        for video_id in video_ids:
            video = Video.query.get(video_id)
            
            if not video:
                print(f"⚠️  Vidéo {video_id} introuvable dans la BDD")
                continue
            
            print(f"📹 Vidéo {video_id}: {video.title}")
            print(f"   Statut actuel: {video.processing_status}")
            print(f"   Bunny ID: {video.bunny_video_id}")
            
            # Marquer comme failed
            video.processing_status = 'failed'
            
            print(f"   ✅ Nouveau statut: failed")
            print()
        
        # Sauvegarder les changements
        db.session.commit()
        
        print("✅ Vidéos marquées comme 'failed'")
        print("✅ Les warnings 404 devraient disparaître")

if __name__ == "__main__":
    fix_bunny_404_videos()
