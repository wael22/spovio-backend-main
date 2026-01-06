# Route temporaire pour créer un compte de test en production
# À SUPPRIMER après les tests!

from flask import Blueprint, jsonify
from ..models.user import User, UserRole
from ..models.database import db
from werkzeug.security import generate_password_hash
from datetime import datetime

# Blueprint temporaire
test_bp = Blueprint('test_admin', __name__)

@test_bp.route('/create-verified-user', methods=['POST'])
def create_verified_test_user():
    """
    ENDPOINT TEMPORAIRE - À SUPPRIMER APRÈS TESTS
    Crée un compte avec email déjà vérifié
    """
    try:
        email = "test@mysmash.com"
        password = "spovio2024"
        name = "Test User Production"
        
        # Vérifier si existe déjà
        existing = User.query.filter_by(email=email).first()
        if existing:
            return jsonify({
                'message': 'Utilisateur existe déjà',
                'user': {
                    'id': existing.id,
                    'email': existing.email,
                    'name': existing.name,
                    'email_verified': existing.email_verified
                }
            }), 200
        
        # Créer le compte
        new_user = User(
            email=email,
            password_hash=generate_password_hash(password),
            name=name,
            phone_number=None,
            role=UserRole.PLAYER,
            credits_balance=100,
            email_verified=True,  # ✅ Déjà vérifié
            email_verified_at=datetime.utcnow(),
            email_verification_token=None
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Compte de test créé avec succès!',
            'credentials': {
                'email': email,
                'password': password,
                'note': 'Email déjà vérifié - vous pouvez vous connecter directement'
            },
            'user': {
                'id': new_user.id,
                'email': new_user.email,
                'name': new_user.name,
                'role': new_user.role.value,
                'credits': new_user.credits_balance,
                'email_verified': new_user.email_verified
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
