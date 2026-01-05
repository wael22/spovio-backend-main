# padelvar-backend/src/routes/super_admin_auth.py

from flask import Blueprint, request, jsonify, session, make_response
from werkzeug.security import check_password_hash
from ..models.user import User, UserRole
from ..models.database import db
from ..middleware.rate_limiter import rate_limit
import pyotp
import qrcode
import io
import base64
import json
import secrets
import logging
import traceback

logger = logging.getLogger(__name__)

# Création du Blueprint pour l'authentification super admin
super_admin_auth_bp = Blueprint('super_admin_auth', __name__)

# Configuration
SUPER_ADMIN_2FA_ISSUER = "MySmash"  # Nom affiché dans l'app 2FA


@super_admin_auth_bp.route('/login', methods=['POST'])
@rate_limit(max_attempts=5, window=60, block_duration=300)
def super_admin_login():
    """
    Étape 1: Authentification email/password pour super admin
    Si 2FA n'est pas configuré, retourne les informations pour le configurer
    Si 2FA est configuré, demande le code 2FA
    """
    try:
        data = request.get_json()
        if not data or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Email et mot de passe requis'}), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        
        # Récupérer l'utilisateur
        user = User.query.filter_by(email=email).first()
        
        # Vérifier que l'utilisateur existe et est super admin
        if not user or user.role != UserRole.SUPER_ADMIN:
            logger.warning(f"Tentative de connexion super admin échouée pour: {email}")
            return jsonify({'error': 'Identifiants invalides'}), 401
        
        # Vérifier le mot de passe
        if not user.password_hash or not check_password_hash(user.password_hash, password):
            logger.warning(f"Mot de passe incorrect pour super admin: {email}")
            return jsonify({'error': 'Identifiants invalides'}), 401
        
        # Stocker temporairement l'ID utilisateur dans la session pour la vérification 2FA
        session['pending_super_admin_id'] = user.id
        
        # Vérifier si 2FA est configuré
        if not user.two_factor_enabled or not user.two_factor_secret:
            # Générer un nouveau secret TOTP
            secret = pyotp.random_base32()
            
            # Générer des codes de secours
            backup_codes = [secrets.token_hex(4) for _ in range(8)]
            
            # Sauvegarder temporairement dans la session (sera sauvegardé en DB après vérification)
            session['temp_2fa_secret'] = secret
            session['temp_backup_codes'] = backup_codes
            
            # Générer l'URL TOTP pour le QR code
            totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=user.email,
                issuer_name=SUPER_ADMIN_2FA_ISSUER
            )
            
            logger.info(f"Configuration 2FA requise pour super admin: {user.email}")
            
            return jsonify({
                'requires_2fa_setup': True,
                'secret': secret,
                'totp_uri': totp_uri,
                'backup_codes': backup_codes,
                'user_email': user.email
            }), 200
        
        # 2FA déjà configuré - demander le code
        logger.info(f"Authentification 2FA requise pour super admin: {user.email}")
        return jsonify({
            'requires_2fa': True,
            'message': 'Veuillez entrer votre code d\'authentification à deux facteurs'
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la connexion super admin: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la connexion'}), 500


@super_admin_auth_bp.route('/setup-2fa', methods=['POST'])
def setup_2fa():
    """
    Configure 2FA pour un super admin (première fois)
    Vérifie le code TOTP et sauvegarde la configuration
    """
    try:
        user_id = session.get('pending_super_admin_id')
        if not user_id:
            return jsonify({'error': 'Session expirée. Veuillez vous reconnecter'}), 401
        
        user = User.query.get(user_id)
        if not user or user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Utilisateur non autorisé'}), 403
        
        data = request.get_json()
        verification_code = data.get('code')
        
        if not verification_code:
            return jsonify({'error': 'Code de vérification requis'}), 400
        
        # Récupérer le secret temporaire de la session
        secret = session.get('temp_2fa_secret')
        backup_codes = session.get('temp_backup_codes')
        
        if not secret or not backup_codes:
            return jsonify({'error': 'Configuration 2FA expirée. Veuillez recommencer'}), 400
        
        # Vérifier le code TOTP
        totp = pyotp.TOTP(secret)
        if not totp.verify(verification_code, valid_window=1):
            return jsonify({'error': 'Code de vérification invalide'}), 400
        
        # Sauvegarder la configuration 2FA
        user.two_factor_secret = secret
        user.two_factor_enabled = True
        user.two_factor_backup_codes = json.dumps(backup_codes)
        
        db.session.commit()
        
        # Connecter l'utilisateur
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        # Nettoyer les données temporaires
        session.pop('pending_super_admin_id', None)
        session.pop('temp_2fa_secret', None)
        session.pop('temp_backup_codes', None)
        
        logger.info(f"2FA configuré avec succès pour super admin: {user.email}")
        
        return jsonify({
            'message': 'Authentification à deux facteurs configurée avec succès',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la configuration 2FA: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la configuration'}), 500


@super_admin_auth_bp.route('/verify-2fa', methods=['POST'])
def verify_2fa():
    """
    Vérifie le code 2FA pour un super admin avec 2FA déjà configuré
    """
    try:
        user_id = session.get('pending_super_admin_id')
        if not user_id:
            return jsonify({'error': 'Session expirée. Veuillez vous reconnecter'}), 401
        
        user = User.query.get(user_id)
        if not user or user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Utilisateur non autorisé'}), 403
        
        data = request.get_json()
        verification_code = data.get('code')
        use_backup_code = data.get('use_backup_code', False)
        
        if not verification_code:
            return jsonify({'error': 'Code de vérification requis'}), 400
        
        # Vérifier le code de secours si demandé
        if use_backup_code:
            if not user.two_factor_backup_codes:
                return jsonify({'error': 'Aucun code de secours disponible'}), 400
            
            backup_codes = json.loads(user.two_factor_backup_codes)
            
            if verification_code in backup_codes:
                # Retirer le code utilisé
                backup_codes.remove(verification_code)
                user.two_factor_backup_codes = json.dumps(backup_codes)
                db.session.commit()
                
                logger.info(f"Connexion super admin réussie avec code de secours: {user.email}")
            else:
                logger.warning(f"Code de secours invalide pour super admin: {user.email}")
                return jsonify({'error': 'Code de secours invalide'}), 400
        else:
            # Vérifier le code TOTP
            if not user.two_factor_secret:
                return jsonify({'error': '2FA non configuré'}), 400
            
            totp = pyotp.TOTP(user.two_factor_secret)
            if not totp.verify(verification_code, valid_window=1):
                logger.warning(f"Code 2FA invalide pour super admin: {user.email}")
                return jsonify({'error': 'Code de vérification invalide'}), 400
            
            logger.info(f"Connexion super admin réussie avec 2FA: {user.email}")
        
        # Connecter l'utilisateur
        session.permanent = True
        session['user_id'] = user.id
        session['user_role'] = user.role.value
        
        # Nettoyer les données temporaires
        session.pop('pending_super_admin_id', None)
        
        # Mettre à jour la date de dernière connexion
        from datetime import datetime
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Connexion réussie',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la vérification 2FA: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la vérification'}), 500


@super_admin_auth_bp.route('/qr-code', methods=['GET'])
def get_qr_code():
    """
    Génère un QR code pour la configuration 2FA
    """
    try:
        user_id = session.get('pending_super_admin_id')
        if not user_id:
            return jsonify({'error': 'Session expirée'}), 401
        
        user = User.query.get(user_id)
        if not user or user.role != UserRole.SUPER_ADMIN:
            return jsonify({'error': 'Non autorisé'}), 403
        
        secret = session.get('temp_2fa_secret')
        if not secret:
            return jsonify({'error': 'Configuration 2FA non initialisée'}), 400
        
        # Générer l'URL TOTP
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email,
            issuer_name=SUPER_ADMIN_2FA_ISSUER
        )
        
        # Générer le QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convertir en base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return jsonify({
            'qr_code': f'data:image/png;base64,{img_str}',
            'secret': secret
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération du QR code: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la génération du QR code'}), 500
