import sys
import os
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

# Rendre importable le paquet src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Charger les variables d'environnement
load_dotenv(os.path.join(os.path.abspath(os.path.dirname(__file__)), '.env'))

from src.main import create_app
from src.models.database import db
from src.models.user import User

app = create_app()

def reset_password(email, new_password):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"❌ Utilisateur {email} non trouvé.")
            return

        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        print(f"✅ Le mot de passe pour {email} a été mis à jour: {new_password}")

if __name__ == "__main__":
    print("Réinitialisation du mot de passe pour CLUB2LOCAL@spovio.net...")
    reset_password("CLUB2LOCAL@spovio.net", "club2-2026")
