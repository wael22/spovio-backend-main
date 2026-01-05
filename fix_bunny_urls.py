# -*- coding: utf-8 -*-
# Script pour corriger les file_url des videos deja uploadees sur Bunny CDN

import sys
sys.path.append('c:\\Users\\PC\\Desktop\\e171abab-6030-4c66-be1d-b73969cd489a-files\\padelvar-backend-main')

from src.models.database import db
from src.models.user import Video
from src.main import create_app

app = create_app()

with app.app_context():
    # Trouver les videos avec bunny_video_id MAIS file_url incorrect
    videos_to_fix = Video.query.filter(
        Video.bunny_video_id.isnot(None),
        ~Video.file_url.like('https://vz-f2c97d0e-5d4.b-cdn.net/%')
    ).all()
    
    print("="*60)
    print(f"VIDEOS A CORRIGER: {len(videos_to_fix)}")
    print("="*60)
    
    if len(videos_to_fix) == 0:
        print("Aucune video a corriger!")
        exit(0)
    
    print("\nVideos avec bunny_video_id mais file_url incorrect:")
    for video in videos_to_fix:
        print(f"\nID {video.id}: {video.title}")
        print(f"  bunny_video_id: {video.bunny_video_id}")
        print(f"  file_url actuel: {video.file_url}")
        correct_url = f"https://vz-f2c97d0e-5d4.b-cdn.net/{video.bunny_video_id}/play.mp4"
        print(f"  file_url corrige: {correct_url}")
    
    print("\n" + "="*60)
    response = input(f"Corriger ces {len(videos_to_fix)} videos? (y/N): ")
    
    if response.lower() == 'y':
        fixed_count = 0
        for video in videos_to_fix:
            video.file_url = f"https://vz-f2c97d0e-5d4.b-cdn.net/{video.bunny_video_id}/play.mp4"
            fixed_count += 1
        
        db.session.commit()
        print(f"\n✅ {fixed_count} videos corrigees!")
    else:
        print("\nAnnule.")
