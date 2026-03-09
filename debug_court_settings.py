from app import create_app
from src.models.database import db
from src.models.user import Court

app = create_app()

with app.app_context():
    court = Court.query.get(3)
    if court:
        print(f"COURT_3_URL: {court.camera_url}")
    else:
        print("COURT_3_NOT_FOUND")
