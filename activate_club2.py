import sys
import os
from dotenv import load_dotenv

# Rendre importable le paquet src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Charger les variables d'environnement
load_dotenv(os.path.join(os.path.abspath(os.path.dirname(__file__)), '.env'))

from src.main import create_app
from src.models.database import db
from src.models.user import User

app = create_app()

def verify_and_activate(email):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"❌ Utilisateur {email} non trouvé.")
            return

        print(f"Statut actuel de vérification pour {email}: {user.email_verified}")
        
        if not user.email_verified:
            user.email_verified = True
            db.session.commit()
            print(f"✅ Le compte {email} a été forcé comme vérifié.")
        else:
            print(f"ℹ️ Le compte {email} était déjà vérifié.")

if __name__ == "__main__":
    verify_and_activate("CLUB2LOCAL@spovio.net")
