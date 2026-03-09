from app import create_app
from src.models.database import db
from src.models.user import Court

app = create_app()

with app.app_context():
    court = Court.query.get(3)
    if court:
        print(f"Old URL: {court.camera_url}")
        # Update to local IP
        court.camera_url = "rtsp://admin:Sgs_2025_@192.168.100.208:554/camira1"
        db.session.commit()
        print(f"New URL: {court.camera_url}")
    else:
        print("Court 3 not found")
