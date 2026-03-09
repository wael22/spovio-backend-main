# padelvar-backend/src/routes/auth.py

from flask import Blueprint, request, jsonify, session, make_response, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from ..models.user import User, UserRole, UserStatus, Club  # Ajout de l'import Club pour la synchronisation
from ..models.system_settings import SystemSettings
from ..models.database import db
from ..models.notification import Notification, NotificationType
from ..services.google_auth_service import verify_google_token, get_google_tokens, get_google_user_info
from ..services.email_verification_service import (
    generate_verification_code,
    send_verification_email,
    verify_email_code
)
from ..utils.jwt_helpers import generate_jwt_token, get_current_user_from_token  # 🆕 JWT Support
from ..middleware.rate_limiter import rate_limit  # 🛡️ Rate limiting protection
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
@rate_limit(max_attempts=5, window=60, block_duration=300)
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
        
        # 🔔 Créer une notification de bienvenue
        try:
            Notification.create_notification(
                user_id=new_user.id,
                notification_type=NotificationType.SYSTEM_MAINTENANCE,
                title="Bienvenue sur Spovio ! 🎾",
                message=f"Bonjour {new_user.name}, bienvenue sur la plateforme ! N'oubliez pas de vérifier votre email pour activer toutes les fonctionnalités."
            )
            db.session.commit()
        except Exception as e:
            logger.error(f"Erreur création notif bienvenue: {e}")
            # On ne bloque pas l'inscription pour une notif
        
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
@rate_limit(max_attempts=5, window=60, block_duration=300)
def login():
    try:
        data = request.get_json()
        print(f"LOGIN ATTEMPT - Data received: {data}")
        email = data['email'].strip()
        password = data['password']
        
        # Search case-insensitively (email might be stored with uppercase)
        user = User.query.filter(User.email.ilike(email)).first()
        
        print(f"LOGIN ATTEMPT - User found: {user is not None}")
        if user:
            print(f"LOGIN ATTEMPT - User email: {user.email}, role: {user.role}, verified: {user.email_verified}")

        # Vérifier si c'est un super admin - rediriger vers l'endpoint dédié
        if user and user.role == UserRole.SUPER_ADMIN:
            print("LOGIN FAIL: Super admin attempted regular login")
            return jsonify({
                'error': 'Les super administrateurs doivent utiliser la page de connexion dédiée.',
                'redirect_to_super_admin': True
            }), 403
        
        if not user:
             print("LOGIN FAIL: User not found in DB")
             return jsonify({'error': 'Email ou mot de passe incorrect'}), 401

        if not user.password_hash:
             print("LOGIN FAIL: User has no password hash")
             return jsonify({'error': 'Email ou mot de passe incorrect'}), 401

        is_valid_pwd = check_password_hash(user.password_hash, password)
        print(f"LOGIN ATTEMPT - Password valid: {is_valid_pwd}")

        if not is_valid_pwd:
            return jsonify({'error': 'Email ou mot de passe incorrect'}), 401
        
        # Vérifier que l'email est vérifié (sauf pour Google OAuth)
        if not user.email_verified and not user.google_id:
            logger.warning(f"⚠️ Tentative de connexion avec email non vérifié: {email}")
            print("LOGIN FAIL: Email not verified")
            return jsonify({
                'error': 'Veuillez vérifier votre adresse email avant de vous connecter.',
                'requires_verification': True,
                'email': email
            }), 403
        
        # 🆕 Générer JWT token pour cross-origin auth
        jwt_token = generate_jwt_token(user.id, user.role.value)
        
        # Maintenir la session pour backward compatibility
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        logger.info(f"✅ Login réussi: {email} - Token JWT généré")
        
        response = make_response(jsonify({
            'message': 'Connexion réussie',
            'user': user.to_dict(),
            'token': jwt_token  # 🆕 JWT token for frontend
        }), 200)
        return response
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la connexion'}), 500


@auth_bp.route('/super-admin-login', methods=['POST'])
def super_admin_login():
    """Endpoint dédié pour la connexion des super administrateurs"""
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email et mot de passe requis'}), 400
        email = data['email'].lower().strip()
        password = data['password']
        user = User.query.filter_by(email=email).first()
        
        # Vérifier que c'est bien un super admin
        if not user or user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Accès réservé aux super administrateurs'}), 403
        
        if not user.password_hash or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'Email ou mot de passe incorrect'}), 401
        
        # Vérifier si 2FA est activé pour ce super admin
        # Pour l'instant, on skip le 2FA (à implémenter plus tard)
        requires_2fa = False  # TODO: Implémenter la vérification 2FA
        
        # Générer JWT token
        jwt_token = generate_jwt_token(user.id, user.role.value)
        
        # Créer la session
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        logger.info(f"✅ Super Admin login réussi: {email} - Token JWT généré")
        
        response = make_response(jsonify({
            'message': 'Connexion super admin réussie',
            'user': user.to_dict(),
            'token': jwt_token,
            'requires_2fa': requires_2fa
        }), 200)
        return response
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la connexion super admin'}), 500



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
    """Get current user - supports both JWT and session auth"""
    try:
        # 🆕 Support JWT token authentication
        user = get_current_user_from_token()
        
        if not user:
            return jsonify({'error': 'Non authentifié'}), 401
        
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
# GESTION DES AVATARS
# ====================================================================
from werkzeug.utils import secure_filename, safe_join
from flask import send_from_directory

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_avatars_folder():
    """Retourne le chemin du dossier avatars, compatible Docker volume et local."""
    # En Docker, le volume est monté sur /app/src/static/uploads/avatars
    # En local, c'est relatif au cwd
    docker_path = '/app/src/static/uploads/avatars'
    local_path = os.path.join(os.getcwd(), 'src', 'static', 'uploads', 'avatars')
    if os.path.exists(docker_path):
        return docker_path
    return local_path

@auth_bp.route('/static/avatars/<path:filename>', methods=['GET'])
def serve_avatar(filename):
    """Sert les fichiers avatar depuis le volume Docker — route utilisée par le frontend."""
    try:
        avatars_folder = get_avatars_folder()
        os.makedirs(avatars_folder, exist_ok=True)
        response = send_from_directory(avatars_folder, filename)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        logger.warning(f"Avatar non trouvé: {filename} — {e}")
        return jsonify({'error': 'Fichier non trouvé'}), 404

def get_overlays_folder():
    """Retourne le chemin du dossier overlays, compatible Docker volume et local."""
    docker_path = '/app/static/overlays'
    local_path = os.path.join(os.getcwd(), 'static', 'overlays')
    if os.path.exists(docker_path):
        return docker_path
    
    # Check parent dir for local dev
    alt_local_path = os.path.join(os.path.dirname(os.getcwd()), 'spovio-backend-main', 'static', 'overlays')
    if os.path.exists(alt_local_path):
        return alt_local_path
        
    return local_path

@auth_bp.route('/static/overlays/<path:filename>', methods=['GET'])
def serve_overlay(filename):
    """Sert les fichiers overlay depuis le volume Docker."""
    try:
        overlays_folder = get_overlays_folder()
        os.makedirs(overlays_folder, exist_ok=True)
        response = send_from_directory(overlays_folder, filename)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        logger.warning(f"Overlay non trouvé: {filename} — {e}")
        return jsonify({'error': 'Fichier non trouvé'}), 404

@auth_bp.route('/upload-avatar', methods=['POST'])
def upload_avatar():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Non authentifié'}), 401
            
        if 'avatar' not in request.files:
            return jsonify({'error': 'Aucun fichier envoyé'}), 400
            
        file = request.files['avatar']
        
        if file.filename == '':
            return jsonify({'error': 'Aucun fichier sélectionné'}), 400
            
        if file and allowed_file(file.filename):
            # Utiliser le bon dossier (compatible Docker volume)
            upload_folder = get_avatars_folder()
            os.makedirs(upload_folder, exist_ok=True)
            
            # Sécuriser le nom du fichier
            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
            filename = f"user_{user_id}_{int(datetime.now().timestamp())}.{ext}"
            file_path = os.path.join(upload_folder, filename)
            
            # Sauvegarder le fichier
            file.save(file_path)
            
            # Mettre à jour l'utilisateur
            user = User.query.get(user_id)
            avatar_url = f"/static/uploads/avatars/{filename}"
            
            user.avatar = avatar_url
            db.session.commit()
            
            return jsonify({
                'message': 'Avatar mis à jour avec succès',
                'avatar_url': avatar_url,
                'user': user.to_dict()
            }), 200
            
        return jsonify({'error': 'Type de fichier non autorisé'}), 400
            
    except Exception as e:
        logger.error(f"Erreur lors de l'upload de l'avatar: {e}")
        return jsonify({'error': 'Erreur serveur lors de l\'upload'}), 500


# ====================================================================
# NOUVELLE ROUTE PLACÉE À LA FIN DU FICHIER
# ====================================================================
@auth_bp.route('/change-password', methods=['POST'])
@rate_limit(max_attempts=5, window=60, block_duration=300)
def change_password():
    # 🆕 Support JWT token authentication (same as /me endpoint)
    current_user = get_current_user_from_token()
    
    if not current_user:
        # Fallback to session
        user_id = session.get('user_id')
        if not user_id:
            logger.warning("❌ Change password: Non authentifié (ni JWT ni session)")
            return jsonify({'error': 'Non authentifié'}), 401
        current_user = User.query.get(user_id)
    
    if not current_user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404
        
    data = request.get_json()
    if not data:
        logger.warning(f"❌ Change password: Pas de données JSON pour user {current_user.id}")
        return jsonify({'error': 'Données JSON requises'}), 400
    
    old_password = data.get('old_password') or data.get('currentPassword') or data.get('current_password')
    new_password = data.get('new_password') or data.get('newPassword')
    
    if not old_password or not new_password:
        logger.warning(f"❌ Change password: Champs manquants pour user {current_user.id}. Keys reçues: {list(data.keys())}")
        return jsonify({'error': 'Ancien et nouveau mots de passe requis'}), 400
        
    if not current_user.password_hash or not check_password_hash(current_user.password_hash, old_password):
        logger.warning(f"❌ Change password: Ancien mot de passe incorrect pour user {current_user.id}")
        return jsonify({'error': 'Ancien mot de passe incorrect'}), 403
        
    if len(new_password) < 6:
        return jsonify({'error': 'Le nouveau mot de passe doit contenir au moins 6 caractères'}), 400
        
    try:
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        logger.info(f"✅ Mot de passe changé avec succès pour user {current_user.id}")
        return jsonify({'message': 'Mot de passe mis à jour avec succès'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors du changement de mot de passe pour l'utilisateur {current_user.id}: {e}")
        return jsonify({'error': 'Erreur interne lors de la mise à jour'}), 500


# Routes d'authentification Google
@auth_bp.route('/google-auth-url', methods=['GET'])
def get_google_auth_url():
    """Retourne l'URL pour démarrer le flux d'authentification Google"""
    # Fetch runtime config to allow hot-reloading and avoid init issues
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
    google_redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI', '').strip()
    
    if not google_client_id or not google_redirect_uri:
        logger.error("❌ Google OAuth misconfigured (Client ID or Redirect URI missing)")
        return jsonify({'error': 'Configuration Google OAuth manquante'}), 500

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id={google_client_id}&response_type=code&scope=email%20profile&redirect_uri={google_redirect_uri}&prompt=select_account"
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
        frontend_url = os.environ.get('FRONTEND_URL', 'http://localhost:3000')
        frontend_callback_url = f"{frontend_url}/google-auth-callback?token={id_token}"
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
            
            # Auto-vérification et activation pour les utilisateurs existants qui lient Google
            if not user.email_verified:
                user.email_verified = True
                user.email_verified_at = datetime.utcnow()
                user.status = UserStatus.ACTIVE
                user.email_verification_token = None
            
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
                email_verified_at=datetime.utcnow(),
                status=UserStatus.ACTIVE  # Auto-activer les utilisateurs Google
            )
            db.session.add(user)
            db.session.commit()
            
            # 🔔 Créer une notification de bienvenue pour Google Auth
            try:
                Notification.create_notification(
                    user_id=user.id,
                    notification_type=NotificationType.SYSTEM_MAINTENANCE,
                    title="Bienvenue sur Spovio ! 🎾",
                    message=f"Bonjour {user.name}, bienvenue sur Spovio ! Votre compte a été créé avec succès via Google."
                )
                db.session.commit()
            except Exception as e:
                logger.error(f"Erreur création notif bienvenue Google: {e}")
        
        # 🆕 Générer JWT token
        jwt_token = generate_jwt_token(user.id, user.role.value)
            
        # Connecter l'utilisateur (session pour backward compatibility)
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        logger.info(f"✅ Google auth réussi: {email} - Token JWT généré")
        
        return jsonify({
            'message': 'Authentification Google réussie',
            'user': user.to_dict(),
            'token': jwt_token  # 🆕 JWT token for frontend
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
        
        # 🆕 Générer JWT token
        jwt_token = generate_jwt_token(user.id, user.role.value)
        
        # Connecter automatiquement l'utilisateur (session pour backward compatibility)
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        logger.info(f"✅ Email vérifié et utilisateur connecté: {email} - Token JWT généré")
        
        return jsonify({
            'message': 'Email vérifié avec succès',
            'user': user.to_dict(),
            'token': jwt_token  # 🆕 JWT token for frontend
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


# ====================================================================
# ROUTES DE RÉINITIALISATION DE MOT DE PASSE
# ====================================================================
from ..services.password_reset_service import request_password_reset, reset_password as service_reset_password
from ..services.user_service import UserService

@auth_bp.route('/forgot-password', methods=['POST'])
@rate_limit(max_attempts=3, window=60, block_duration=300)
def forgot_password():
    """Demande de réinitialisation de mot de passe"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'error': 'Email requis'}), 400
            
        # Instancier le UserService
        user_service = UserService()
        
        # Traiter la demande (retourne toujours True pour sécurité)
        request_password_reset(email, user_service)
        
        return jsonify({
            'message': 'Si un compte existe avec cet email, un lien de réinitialisation a été envoyé.'
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la demande de réinitialisation: {str(e)}")
        return jsonify({'error': 'Erreur lors du traitement de la demande'}), 500


@auth_bp.route('/reset-password', methods=['POST'])
@rate_limit(max_attempts=5, window=60, block_duration=300)
def reset_password_route():
    """Réinitialisation effective du mot de passe avec token"""
    try:
        data = request.get_json()
        token = data.get('token')
        new_password = data.get('new_password')
        
        if not token or not new_password:
            return jsonify({'error': 'Token et nouveau mot de passe requis'}), 400
            
        if len(new_password) < 6:
            return jsonify({'error': 'Le mot de passe doit contenir au moins 6 caractères'}), 400
            
        # Instancier le UserService
        user_service = UserService()
        
        # Tenter la réinitialisation
        success = service_reset_password(token, new_password, user_service)
        
        if success:
            return jsonify({'message': 'Mot de passe réinitialisé avec succès'}), 200
        else:
            return jsonify({'error': 'Lien de réinitialisation invalide ou expiré'}), 400
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de la réinitialisation du mot de passe: {str(e)}")
        return jsonify({'error': 'Erreur lors de la réinitialisation'}), 500