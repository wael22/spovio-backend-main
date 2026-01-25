import os
import secrets
import string
import datetime
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import jwt
except ImportError:
    from .google_auth_service import jwt, logger

# Configuration d'un logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration pour le service de réinitialisation de mot de passe
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'default_jwt_secret_key_for_reset_password')
PASSWORD_RESET_EXPIRY = int(os.environ.get('PASSWORD_RESET_EXPIRY', '3600'))  # 1 heure par défaut
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', 'noreply@mysmash.tn')
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:5000')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

def generate_reset_token(user_id, email):
    """Génère un token JWT pour la réinitialisation du mot de passe"""
    try:
        logger.info(f"🔑 Génération d'un token de réinitialisation pour l'utilisateur {user_id}")
        
        # Date d'expiration (1 heure par défaut)
        expiry = datetime.datetime.utcnow() + datetime.timedelta(seconds=PASSWORD_RESET_EXPIRY)
        
        # Créer le payload du token
        payload = {
            'sub': str(user_id),
            'email': email,
            'exp': expiry,
            'type': 'password_reset'
        }
        
        # Générer le token JWT
        token = jwt.encode(
            payload,
            JWT_SECRET_KEY,
            algorithm='HS256'
        )
        
        logger.info(f"✅ Token de réinitialisation généré avec succès pour {email}")
        return token
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la génération du token de réinitialisation: {str(e)}")
        return None

def verify_reset_token(token):
    """Vérifie un token de réinitialisation de mot de passe"""
    try:
        logger.info(f"🔍 Vérification du token de réinitialisation...")
        
        # Décoder et vérifier le token
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=['HS256']
        )
        
        # Vérifier le type de token
        if payload.get('type') != 'password_reset':
            logger.error("❌ Type de token invalide")
            return None
        
        # Retourner les informations du token
        return {
            'user_id': payload['sub'],
            'email': payload['email']
        }
        
    except jwt.ExpiredSignatureError:
        logger.error("❌ Token de réinitialisation expiré")
        return None
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification du token de réinitialisation: {str(e)}")
        return None

def send_password_reset_email(email, token):
    """Envoie un email avec le lien de réinitialisation du mot de passe"""
    try:
        logger.info(f"📧 Envoi d'un email de réinitialisation à {email}")
        
        # Construire l'URL de réinitialisation
        reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
        
        # Créer le message
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = email
        msg['Subject'] = "Spovio - Réinitialisation de votre mot de passe"
        
        # Corps du message HTML
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e9e9e9; border-radius: 5px;">
                <h2 style="color: #333;">Réinitialisation de votre mot de passe Spovio</h2>
                <p>Vous avez demandé la réinitialisation de votre mot de passe. Veuillez cliquer sur le lien ci-dessous pour créer un nouveau mot de passe :</p>
                <p style="margin: 25px 0;">
                    <a href="{reset_url}" style="background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%); color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">
                        Réinitialiser mon mot de passe
                    </a>
                </p>
                <p>Ce lien expirera dans 1 heure.</p>
                <p>Si vous n'avez pas demandé cette réinitialisation, vous pouvez ignorez cet email.</p>
                <p>Cordialement,<br>L'équipe Spovio</p>
            </div>
        </body>
        </html>
        """
        
        # Ajouter le corps du message
        msg.attach(MIMEText(html_body, 'html'))
        
        # Vérifier la configuration SMTP
        if not SMTP_USERNAME or not SMTP_PASSWORD:
            logger.error("❌ Configuration SMTP incomplète - Email non envoyé")
            logger.warning("⚠️ Définissez SMTP_USERNAME et SMTP_PASSWORD dans les variables d'environnement")
            
            # En mode développement, afficher simplement l'URL
            logger.info(f"🔗 URL de réinitialisation (DEV ONLY): {reset_url}")
            return True
        
        # Envoyer l'email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email de réinitialisation envoyé à {email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi de l'email de réinitialisation: {str(e)}")
        return False

def generate_random_password(length=12):
    """Génère un mot de passe aléatoire"""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password

def request_password_reset(email, user_service):
    """Traite une demande de réinitialisation de mot de passe"""
    try:
        logger.info(f"🔄 Traitement de la demande de réinitialisation pour {email}")
        
        # Vérifier si l'utilisateur existe
        user = user_service.get_user_by_email(email)
        if not user:
            logger.warning(f"⚠️ Tentative de réinitialisation pour un email non enregistré: {email}")
            # Toujours retourner True pour éviter les fuites d'information sur les emails existants
            return True
        
        # Générer un token de réinitialisation
        token = generate_reset_token(user.id, email)
        if not token:
            logger.error(f"❌ Échec de génération du token pour {email}")
            return False
        
        # Envoyer l'email de réinitialisation
        return send_password_reset_email(email, token)
    
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement de la demande de réinitialisation: {str(e)}")
        return False

def reset_password(token, new_password, user_service):
    """Réinitialise le mot de passe d'un utilisateur"""
    try:
        logger.info(f"🔄 Traitement de la réinitialisation de mot de passe...")
        
        # Vérifier le token
        token_data = verify_reset_token(token)
        if not token_data:
            logger.error("❌ Token de réinitialisation invalide ou expiré")
            return False
        
        # Récupérer l'utilisateur
        user = user_service.get_user_by_id(token_data['user_id'])
        if not user:
            logger.error(f"❌ Utilisateur non trouvé pour l'ID {token_data['user_id']}")
            return False
        
        # Vérifier que l'email correspond
        if user.email != token_data['email']:
            logger.error(f"❌ L'email de l'utilisateur ne correspond pas à celui du token")
            return False
        
        # Mettre à jour le mot de passe
        result = user_service.update_password(user.id, new_password)
        
        if result:
            # Auto-vérifier l'email lors du reset (si l'utilisateur a accès à l'email, il le contrôle)
            if not user.email_verified:
                from ..models.database import db
                user.email_verified = True
                user.email_verified_at = datetime.datetime.utcnow()
                user.email_verification_token = None
                db.session.commit()
                logger.info(f"📧 Email auto-vérifié lors du reset de mot de passe pour {user.email}")
            
            logger.info(f"✅ Mot de passe réinitialisé avec succès pour {user.email}")
        else:
            logger.error(f"❌ Échec de la mise à jour du mot de passe pour {user.email}")
        
        return result
    
    except Exception as e:
        logger.error(f"❌ Erreur lors de la réinitialisation du mot de passe: {str(e)}")
        return False
