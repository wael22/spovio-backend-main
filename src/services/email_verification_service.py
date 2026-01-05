"""Service de vérification d'email pour les nouveaux utilisateurs"""
import os
import secrets
import string
import datetime
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configuration du logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration SMTP (réutilise la config du service de réinitialisation de mot de passe)
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', 'noreply@mysmash.tn')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Durée de validité du code de vérification (24 heures par défaut)
VERIFICATION_CODE_EXPIRY_HOURS = int(os.environ.get('VERIFICATION_CODE_EXPIRY_HOURS', '24'))


def generate_verification_code():
    """Génère un code de vérification à 6 chiffres"""
    return ''.join(secrets.choice(string.digits) for _ in range(6))


def is_code_expired(sent_at):
    """Vérifie si un code de vérification a expiré
    
    Args:
        sent_at: DateTime du moment où le code a été envoyé
        
    Returns:
        bool: True si le code a expiré, False sinon
    """
    if not sent_at:
        return True
    
    expiry_time = sent_at + datetime.timedelta(hours=VERIFICATION_CODE_EXPIRY_HOURS)
    return datetime.datetime.utcnow() > expiry_time


def send_verification_email(email, code, name=None):
    """Envoie un email avec le code de vérification
    
    Args:
        email: Email du destinataire
        code: Code de vérification à 6 chiffres
        name: Nom de l'utilisateur (optionnel)
        
    Returns:
        bool: True si l'email a été envoyé avec succès, False sinon
    """
    try:
        logger.info(f"📧 Envoi d'un email de vérification à {email}")
        
        # Créer le message
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = email
        msg['Subject'] = "MySmash - Vérifiez votre adresse email"
        
        # Nom d'affichage
        display_name = name if name else email.split('@')[0]
        
        # Corps du message HTML
        verification_url = f"{FRONTEND_URL}/verify-email?email={email}"
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; background-color: #f5f5f5;">
            <div style="max-width: 600px; margin: 40px auto; padding: 0; background-color: #ffffff;">
                <!-- Header -->
                <div style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); text-align: center; padding: 40px 20px; border-radius: 10px 10px 0 0;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 32px;">MySmash</h1>
                    <p style="color: #ffffff; font-size: 16px; margin: 10px 0 0 0; opacity: 0.95;">Votre plateforme d'enregistrement de matchs de padel</p>
                </div>
                
                <!-- Content -->
                <div style="padding: 40px 30px;">
                    <h2 style="color: #1f2937; margin: 0 0 20px 0; font-size: 24px;">Bienvenue {display_name} ! 🎾</h2>
                    
                    <p style="color: #4b5563; font-size: 16px; margin-bottom: 25px; line-height: 1.6;">
                        Merci de vous être inscrit sur <strong>MySmash</strong>. Vous êtes à une étape de profiter de tous les avantages de notre plateforme !
                    </p>
                    
                    <p style="color: #4b5563; font-size: 16px; margin-bottom: 30px;">
                        Pour <strong>activer votre compte</strong> et commencer à enregistrer vos matchs, veuillez vérifier votre adresse email en utilisant le code ci-dessous :
                    </p>
                    
                    <!-- Code Box -->
                    <div style="background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); padding: 30px 20px; border-radius: 12px; text-align: center; margin: 30px 0; border: 2px solid #10b981;">
                        <p style="margin: 0 0 15px 0; color: #059669; font-size: 14px; text-transform: uppercase; letter-spacing: 2px; font-weight: 600;">Votre code de vérification</p>
                        <p style="font-size: 42px; font-weight: bold; color: #10b981; margin: 10px 0; letter-spacing: 12px; font-family: 'Courier New', monospace;">{code}</p>
                        <p style="margin: 15px 0 0 0; color: #059669; font-size: 13px;">Saisissez ce code sur la page de vérification</p>
                    </div>
                    
                    <!-- CTA Button -->
                    <div style="text-align: center; margin: 35px 0;">
                        <a href="{verification_url}" 
                           style="display: inline-block; background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 8px; font-size: 16px; font-weight: 600; box-shadow: 0 4px 6px rgba(16, 185, 129, 0.3); transition: all 0.3s;">
                            ✅ Activer mon compte
                        </a>
                    </div>
                    
                    <p style="color: #6b7280; font-size: 14px; text-align: center; margin: 25px 0;">
                        Ou cliquez sur ce lien : <a href="{verification_url}" style="color: #10b981; text-decoration: none;">{verification_url}</a>
                    </p>
                    
                    <!-- Warning Box -->
                    <div style="background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px 20px; margin: 30px 0; border-radius: 4px;">
                        <p style="margin: 0; color: #92400e; font-size: 14px;">
                            <strong>⏰ Attention :</strong> Ce code expirera dans <strong>{VERIFICATION_CODE_EXPIRY_HOURS} heures</strong>. Pensez à vérifier votre compte rapidement !
                        </p>
                    </div>
                    
                    <!-- Security Notice -->
                    <div style="background-color: #f3f4f6; padding: 15px 20px; border-radius: 8px; margin: 25px 0;">
                        <p style="color: #6b7280; font-size: 13px; margin: 0; line-height: 1.5;">
                            <strong>🔒 Sécurité :</strong> Si vous n'avez pas créé de compte sur MySmash, ignorez simplement cet email. Votre adresse email restera protégée.
                        </p>
                    </div>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; border-top: 1px solid #e5e7eb;">
                    <p style="color: #6b7280; font-size: 14px; margin: 0 0 10px 0; text-align: center;">
                        Besoin d'aide ? Contactez-nous à <a href="mailto:support@mysmash.com" style="color: #10b981; text-decoration: none;">support@mysmash.com</a>
                    </p>
                    <p style="color: #9ca3af; font-size: 12px; margin: 15px 0 0 0; text-align: center;">
                        © 2024 MySmash - Tous droits réservés<br>
                        Votre passion du padel, notre technologie
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Ajouter le corps du message
        msg.attach(MIMEText(html_body, 'html'))
        
        # Vérifier la configuration SMTP
        if not SMTP_USERNAME or not SMTP_PASSWORD:
            logger.warning("⚠️ Configuration SMTP incomplète - Email non envoyé")
            logger.warning("⚠️ Définissez SMTP_USERNAME et SMTP_PASSWORD dans les variables d'environnement")
            
            # En mode développement, afficher simplement le code
            logger.info(f"🔑 CODE DE VÉRIFICATION (DEV ONLY): {code}")
            logger.info(f"📧 Email destinataire: {email}")
            return True
        
        # Envoyer l'email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email de vérification envoyé à {email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi de l'email de vérification: {str(e)}")
        return False


def verify_email_code(user, code):
    """Vérifie le code de vérification d'un utilisateur
    
    Args:
        user: Objet User à vérifier
        code: Code de vérification fourni par l'utilisateur
        
    Returns:
        dict: {'success': bool, 'error': str ou None}
    """
    try:
        logger.info(f"🔍 Vérification du code pour {user.email}")
        
        # Vérifier que l'utilisateur n'est pas déjà vérifié
        if user.email_verified:
            logger.info(f"ℹ️ L'utilisateur {user.email} est déjà vérifié")
            return {'success': True, 'error': None}
        
        # Vérifier que l'utilisateur a un code de vérification
        if not user.email_verification_token:
            logger.error(f"❌ Aucun code de vérification pour {user.email}")
            return {'success': False, 'error': 'Aucun code de vérification en attente'}
        
        # Vérifier que le code n'a pas expiré
        if is_code_expired(user.email_verification_sent_at):
            logger.warning(f"⚠️ Code de vérification expiré pour {user.email}")
            return {'success': False, 'error': 'Code de vérification expiré. Veuillez demander un nouveau code.'}
        
        # Vérifier que le code correspond
        if user.email_verification_token != code:
            logger.warning(f"⚠️ Code de vérification incorrect pour {user.email}")
            return {'success': False, 'error': 'Code de vérification incorrect'}
        
        # Tout est OK - marquer l'email comme vérifié
        logger.info(f"✅ Email vérifié avec succès pour {user.email}")
        return {'success': True, 'error': None}
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification du code: {str(e)}")
        return {'success': False, 'error': 'Erreur lors de la vérification'}
