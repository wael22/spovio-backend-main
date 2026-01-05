# padelvar-backend/src/routes/auth.py

from flask import Blueprint, request, jsonify, session, make_response, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from ..models.user import User, UserRole, Club  # Ajout de l'import Club pour la synchronisation
from ..models.system_settings import SystemSettings
from ..models.database import db
from ..services.google_auth_service import verify_google_token, get_google_tokens, get_google_user_info
from ..services.email_verification_service import (
    generate_verification_code,
    send_verification_email,
    verify_email_code
)
import re
import traceback
import logging # Ajout du logger
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Récupération des variables d'environnement Google OAuth
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', 'http://localhost:5000/api/auth/google/callback')

# La définition du Blueprint doit être ici, avant les routes
auth_bp = Blueprint('auth', __name__)

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password') or not data.get('name'):
            return jsonify({'error': 'Email, mot de passe et nom requis'}), 400
        email = data['email'].lower().strip()
        password = data['password']
        name = data['name'].strip()
        phone_number = data.get('phone_number', '').strip()
        if not validate_email(email):
            return jsonify({'error': 'Format d\'email invalide'}), 400
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return jsonify({'error': 'Un utilisateur avec cet email existe déjà'}), 409
        if len(password) < 6:
            return jsonify({'error': 'Le mot de passe doit contenir au moins 6 caractères'}), 400
        
        password_hash = generate_password_hash(password)
        
        # Générer le code de vérification
        verification_code = generate_verification_code()
        
        new_user = User(
            email=email, 
            password_hash=password_hash, 
            name=name,
            phone_number=phone_number if phone_number else None,
            role=UserRole.PLAYER, 
            credits_balance=SystemSettings.get_welcome_credits(),
            email_verified=False,  # Pas encore vérifié
            email_verification_token=verification_code,
            email_verification_sent_at=datetime.utcnow()
        )
        db.session.add(new_user)
        db.session.commit()
        
        # Envoyer l'email de vérification
        send_verification_email(email, verification_code, name)
        
        logger.info(f"✅ Nouvel utilisateur créé: {email} - En attente de vérification")
        
        response = make_response(jsonify({
            'message': 'Inscription réussie. Veuillez vérifier votre email.',
            'email': email,
            'requires_verification': True
        }), 201)
        return response
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de l\'inscription'}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email et mot de passe requis'}), 400
        email = data['email'].lower().strip()
        password = data['password']
        user = User.query.filter_by(email=email).first()
        
        # Vérifier si c'est un super admin - rediriger vers l'endpoint dédié
        if user and user.role == UserRole.SUPER_ADMIN:
            return jsonify({
                'error': 'Les super administrateurs doivent utiliser la page de connexion dédiée.',
                'redirect_to_super_admin': True
            }), 403
        
        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'Email ou mot de passe incorrect'}), 401
        
        # Vérifier que l'email est vérifié (sauf pour Google OAuth)
        if not user.email_verified and not user.google_id:
            logger.warning(f"⚠️ Tentative de connexion avec email non vérifié: {email}")
            return jsonify({
                'error': 'Veuillez vérifier votre adresse email avant de vous connecter.',
                'requires_verification': True,
                'email': email
            }), 403
        
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        response = make_response(jsonify({'message': 'Connexion réussie', 'user': user.to_dict()}), 200)
        return response
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la connexion'}), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Déconnexion avec nettoyage des enregistrements actifs"""
    try:
        user_id = session.get('user_id')
        
        # 🎬 ARRÊTER LES ENREGISTREMENTS ACTIFS AVANT DÉCONNEXION
        if user_id:
            from ..models.user import RecordingSession, Court
            from ..video_system.session_manager import session_manager
            from ..video_system.recording import video_recorder
            from datetime import datetime
            
            # Les enregistrements de terrain continuent même si le joueur se déconnecte
            # Ils doivent être arrêtés manuellement par le club ou atteindre le temps max
            logger.info(f"👤 Logout user {user_id} - enregistrements continuent")
        
        # Nettoyer la session
        session.clear()
        response = make_response(jsonify({'message': 'Déconnexion réussie'}), 200)
        return response
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du logout: {e}")
        # Même en cas d'erreur, déconnecter l'utilisateur
        session.clear()
        return jsonify({'message': 'Déconnexion effectuée'}), 200


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    # ... (code de la fonction get_current_user inchangé)
    try:
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        user = User.query.get(user_id)
        if not user:
            session.clear()
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
        return jsonify({'user': user.to_dict()}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération de l\'utilisateur'}), 500


@auth_bp.route('/update-profile', methods=['PUT'])
def update_profile():
    # ... (code de la fonction update_profile inchangé)
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
            
        data = request.get_json()
        
        # Sauvegarder les modifications utilisateur
        if 'name' in data:
            user.name = data['name'].strip()
        if 'phone_number' in data:
            user.phone_number = data['phone_number'].strip() if data['phone_number'] else None
            
        # SYNCHRONISATION BIDIRECTIONNELLE: Pour les utilisateurs de type CLUB
        if user.role == UserRole.CLUB and user.club_id:
            club = Club.query.get(user.club_id)
            if club:
                # Synchroniser les modifications vers l'objet Club
                if 'name' in data:
                    club.name = user.name
                if 'phone_number' in data:
                    club.phone_number = user.phone_number
                    
                print(f"Synchronisation User→Club: Club {club.id} mis à jour depuis User {user.id}")
                
        db.session.commit()
        return jsonify({'message': 'Profil mis à jour avec succès', 'user': user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la mise à jour du profil'}), 500


# ====================================================================
# NOUVELLE ROUTE PLACÉE À LA FIN DU FICHIER
# ====================================================================
@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Non authentifié'}), 401
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
        
    data = request.get_json()
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({'error': 'Ancien et nouveau mots de passe requis'}), 400
        
    if not user.password_hash or not check_password_hash(user.password_hash, old_password):
        return jsonify({'error': 'Ancien mot de passe incorrect'}), 403
        
    if len(new_password) < 6:
        return jsonify({'error': 'Le nouveau mot de passe doit contenir au moins 6 caractères'}), 400
        
    try:
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        return jsonify({'message': 'Mot de passe mis à jour avec succès'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du changement de mot de passe pour l'utilisateur {user.id}: {e}")
        return jsonify({'error': 'Erreur interne lors de la mise à jour'}), 500


# Routes d'authentification Google
@auth_bp.route('/google-auth-url', methods=['GET'])
def get_google_auth_url():
    """Retourne l'URL pour démarrer le flux d'authentification Google"""
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={GOOGLE_CLIENT_ID}&response_type=code&scope=email%20profile&redirect_uri={GOOGLE_REDIRECT_URI}&prompt=select_account"
    return jsonify({'auth_url': auth_url}), 200


@auth_bp.route('/google/callback', methods=['GET'])
def google_callback():
    """Traite le callback de Google après l'autorisation de l'utilisateur"""
    try:
        # Récupérer le code d'autorisation
        code = request.args.get('code')
        if not code:
            return jsonify({'error': 'Code d\'autorisation manquant'}), 400
            
        # Échanger le code contre des tokens
        token_data = get_google_tokens(code)
        if not token_data:
            return jsonify({'error': 'Échec d\'obtention des tokens Google'}), 401
            
        access_token = token_data.get('access_token')
        id_token = token_data.get('id_token')
        
        # Obtenir les informations de l'utilisateur
        user_info = get_google_user_info(access_token)
        if not user_info:
            return jsonify({'error': 'Échec d\'obtention des informations utilisateur'}), 401
            
        # Redirection vers le frontend avec un code temporaire pour compléter l'authentification
        frontend_callback_url = f"http://localhost:3000/google-auth-callback?token={id_token}"
        return redirect(frontend_callback_url)
        
    except Exception as e:
        logger.error(f"Erreur lors du callback Google: {e}")
        return jsonify({'error': 'Erreur lors de l\'authentification Google'}), 500


@auth_bp.route('/google/authenticate', methods=['POST'])
def google_authenticate():
    """Authentifie l'utilisateur avec un token ID Google"""
    try:
        data = request.get_json()
        if not data or not data.get('token'):
            return jsonify({'error': 'Token Google requis'}), 400
            
        # Vérifier le token Google
        user_info = verify_google_token(data['token'])
        if not user_info:
            return jsonify({'error': 'Token Google invalide'}), 401
            
        email = user_info['email']
        
        # Vérifier si l'utilisateur existe déjà
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Utilisateur existant: mettre à jour les infos Google et connecter
            user.google_id = user_info['google_id']
            if not user.name and user_info.get('name'):
                user.name = user_info['name']
            db.session.commit()
        else:
            # Nouvel utilisateur: créer un compte
            user = User(
                email=email,
                name=user_info.get('name', email.split('@')[0]),
                google_id=user_info['google_id'],
                role=UserRole.PLAYER,
                credits_balance=SystemSettings.get_welcome_credits(),
                email_verified=True,  # Auto-vérifier les utilisateurs Google
                email_verified_at=datetime.utcnow()
            )
            db.session.add(user)
            db.session.commit()
            
        # Connecter l'utilisateur
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        return jsonify({
            'message': 'Authentification Google réussie',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'authentification Google: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de l\'authentification Google'}), 500


# Fonctions utilitaires pour l'authentification
from functools import wraps

def get_current_user():
    """
    Récupère l'utilisateur actuellement connecté depuis la session
    Retourne None si aucun utilisateur n'est connecté
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

def require_auth(f):
    """
    Décorateur pour protéger les routes qui nécessitent une authentification
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Authentification requise'}), 401
        return f(*args, **kwargs)
    return decorated_function

def require_admin(f):
    """
    Décorateur pour protéger les routes qui nécessitent des privilèges admin
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_current_user()
        if not current_user:
            return jsonify({'error': 'Authentification requise'}), 401
        if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
            return jsonify({'error': 'Privilèges administrateur requis'}), 403
        return f(*args, **kwargs)
    return decorated_function


# ====================================================================
# ROUTES DE VÉRIFICATION D'EMAIL
# ====================================================================

@auth_bp.route('/verify-email', methods=['POST'])
def verify_email():
    """Vérifie l'email d'un utilisateur avec le code reçu par email"""
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'error': 'Email et code de vérification requis'}), 400
        
        # Récupérer l'utilisateur
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({'error': 'Utilisateur non trouvé'}), 404
        
        # Vérifier le code
        result = verify_email_code(user, code)
        
        if not result['success']:
            return jsonify({'error': result['error']}), 400
        
        # Marquer l'email comme vérifié
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()
        user.email_verification_token = None  # Supprimer le code
        user.email_verification_sent_at = None
        db.session.commit()
        
        # Connecter automatiquement l'utilisateur
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        logger.info(f"✅ Email vérifié et utilisateur connecté: {email}")
        
        return jsonify({
            'message': 'Email vérifié avec succès',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors de la vérification de l'email: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la vérification'}), 500


@auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    """Renvoie un nouveau code de vérification"""
    try:
        data = request.get_json()
        email = data.get('email', '').lower().strip()
        
        if not email:
            return jsonify({'error': 'Email requis'}), 400
        
        # Récupérer l'utilisateur
        user = User.query.filter_by(email=email).first()
        if not user:
            # Ne pas révéler si l'email existe ou non (sécurité)
            return jsonify({'message': 'Si cet email existe, un nouveau code a été envoyé'}), 200
        
        # Vérifier si déjà vérifié
        if user.email_verified:
            return jsonify({'error': 'Cet email est déjà vérifié'}), 400
        
        # Générer un nouveau code
        verification_code = generate_verification_code()
        user.email_verification_token = verification_code
        user.email_verification_sent_at = datetime.utcnow()
        db.session.commit()
        
        # Envoyer le nouveau code
        send_verification_email(email, verification_code, user.name)
        
        logger.info(f"📧 Nouveau code de vérification envoyé à {email}")
        
        return jsonify({
            'message': 'Un nouveau code de vérification a été envoyé à votre email'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors du renvoi du code: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors du renvoi du code'}), 500