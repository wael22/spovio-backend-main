"""
Routes pour le partage de vidéos entre utilisateurs
"""
from flask import Blueprint, request, jsonify, session
from src.models.user import db, User, Video, SharedVideo
from functools import wraps
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)
video_sharing_bp = Blueprint('video_sharing', __name__)

# Configuration SMTP
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.environ.get('SMTP_FROM_EMAIL', 'noreply@mysmash.tn')
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:8080')


def send_share_email(recipient_email, recipient_name, sender_name, video_title, message=None):
    """Envoie un email de notification de partage de vidéo
    
    Args:
        recipient_email: Email du destinataire
        recipient_name: Nom du destinataire
        sender_name: Nom de l'expéditeur
        video_title: Titre de la vidéo partagée
        message: Message optionnel du partageur
        
    Returns:
        bool: True si l'email a été envoyé avec succès, False sinon
    """
    try:
        logger.info(f"📧 Envoi d'un email de partage de vidéo à {recipient_email}")
        
        # Créer le message
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM_EMAIL
        msg['To'] = recipient_email
        msg['Subject'] = f"MySmash - {sender_name} a partagé une vidéo avec vous"
        
        # URL pour accéder aux vidéos partagées
        shared_videos_url = f"{FRONTEND_URL}/shared-with-me"
        
        # Message personnalisé
        personal_message_html = ""
        if message:
            personal_message_html = f"""
            <div style="background-color: #f3f4f6; padding: 20px; border-radius: 8px; margin: 25px 0; border-left: 4px solid #10b981;">
                <p style="color: #374151; font-size: 14px; margin: 0; line-height: 1.6;">
                    <strong>💬 Message de {sender_name} :</strong><br>
                    "{message}"
                </p>
            </div>
            """
        
        # Corps du message HTML
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
                    <h2 style="color: #1f2937; margin: 0 0 20px 0; font-size: 24px;">Bonjour {recipient_name} ! 🎾</h2>
                    
                    <p style="color: #4b5563; font-size: 16px; margin-bottom: 25px; line-height: 1.6;">
                        <strong>{sender_name}</strong> a partagé une vidéo avec vous sur <strong>MySmash</strong> !
                    </p>
                    
                    <!-- Video Info Box -->
                    <div style="background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); padding: 25px 20px; border-radius: 12px; margin: 25px 0; border: 2px solid #10b981;">
                        <p style="margin: 0 0 10px 0; color: #059669; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">📹 Vidéo partagée</p>
                        <p style="font-size: 20px; font-weight: bold; color: #10b981; margin: 5px 0;">"{video_title}"</p>
                    </div>
                    
                    {personal_message_html}
                    
                    <!-- CTA Button -->
                    <div style="text-align: center; margin: 35px 0;">
                        <a href="{shared_videos_url}" 
                           style="display: inline-block; background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: #ffffff; text-decoration: none; padding: 16px 40px; border-radius: 8px; font-size: 16px; font-weight: 600; box-shadow: 0 4px 6px rgba(16, 185, 129, 0.3); transition: all 0.3s;">
                            ▶️ Voir la vidéo partagée
                        </a>
                    </div>
                    
                    <p style="color: #6b7280; font-size: 14px; text-align: center; margin: 25px 0;">
                        Ou cliquez sur ce lien : <a href="{shared_videos_url}" style="color: #10b981; text-decoration: none;">{shared_videos_url}</a>
                    </p>
                    
                    <!-- Info Box -->
                    <div style="background-color: #eff6ff; border-left: 4px solid #3b82f6; padding: 15px 20px; margin: 30px 0; border-radius: 4px;">
                        <p style="margin: 0; color: #1e40af; font-size: 14px;">
                            <strong>ℹ️ Astuce :</strong> Vous pouvez consulter toutes vos vidéos partagées dans la section "Partagé avec moi" de votre tableau de bord MySmash.
                        </p>
                    </div>
                </div>
                
                <!-- Footer -->
                <div style="background-color: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; border-top: 1px solid #e5e7eb;">
                    <p style="color: #6b7280; font-size: 14px; margin: 0 0 10px 0; text-align: center;">
                        Besoin d'aide ? Contactez-nous à <a href="mailto:support@mysmash.tn" style="color: #10b981; text-decoration: none;">support@mysmash.tn</a>
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
            
            # En mode développement, juste logger
            logger.info(f"📧 [DEV MODE] Email de partage non envoyé à {recipient_email}")
            logger.info(f"📧 [DEV MODE] Vidéo: {video_title} | De: {sender_name}")
            return True
        
        # Envoyer l'email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email de partage envoyé à {recipient_email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi de l'email de partage: {str(e)}")
        return False

# Helper: Login required
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return wrapper

def get_current_user():
    """Récupère l'utilisateur courant depuis la session"""
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def api_response(data=None, message=None, status=200, error=None):
    """Format de réponse API standardisé"""
    resp = {}
    if data is not None:
        resp.update(data)
    if message:
        resp['message'] = message
    if error:
        resp['error'] = error
    return jsonify(resp), status

# ================= ENDPOINTS DE PARTAGE =================

@video_sharing_bp.route('/<int:video_id>/share-with-user', methods=['POST'])
@login_required
def share_video_with_user(video_id):
    """Partager une vidéo avec un utilisateur par email"""
    current_user = get_current_user()
    
    # Récupérer les données de la requête
    data = request.get_json() or {}
    recipient_email = (data.get('recipient_email') or '').strip()
    message_raw = data.get('message') or ''
    message = message_raw.strip() if message_raw else None
    
    # Validation
    if not recipient_email:
        return api_response(error='Email du destinataire requis', status=400)
    
    # Vérifier que la vidéo existe et appartient à l'utilisateur
    video = Video.query.get(video_id)
    if not video:
        return api_response(error='Vidéo non trouvée', status=404)
    
    if video.user_id != current_user.id:
        return api_response(error='Vous ne pouvez partager que vos propres vidéos', status=403)
    
    # Trouver l'utilisateur destinataire par email
    recipient = User.query.filter_by(email=recipient_email).first()
    if not recipient:
        return api_response(error=f'Aucun utilisateur trouvé avec l\'email {recipient_email}', status=404)
    
    # Vérifier qu'on ne partage pas avec soi-même
    if recipient.id == current_user.id:
        return api_response(error='Vous ne pouvez pas partager une vidéo avec vous-même', status=400)
    
    # Vérifier si la vidéo n'est pas déjà partagée avec cet utilisateur
    existing_share = SharedVideo.query.filter_by(
        video_id=video_id,
        shared_with_user_id=recipient.id
    ).first()
    
    if existing_share:
        return api_response(error='Cette vidéo est déjà partagée avec cet utilisateur', status=400)
    
    # Créer le partage
    try:
        shared_video = SharedVideo(
            video_id=video_id,
            owner_user_id=current_user.id,
            shared_with_user_id=recipient.id,
            message=message
        )
        db.session.add(shared_video)
        
        # Créer une notification pour le destinataire
        from src.models.notification import Notification, NotificationType
        try:
            notification = Notification(
                user_id=recipient.id,
                title='Nouvelle vidéo partagée',
                message=f'{current_user.name} a partagé une vidéo avec vous: "{video.title}"',
                notification_type=NotificationType.VIDEO,
                link=None
            )
            db.session.add(notification)
            logger.info(f"[NOTIF DEBUG] Notification créée pour user_id={recipient.id}, email={recipient.email}")
        except Exception as notif_error:
            logger.error(f"[NOTIF ERROR] Erreur lors de la création de notification: {notif_error}")
            import traceback
            logger.error(traceback.format_exc())
            # Ne pas bloquer le partage si la notification échoue
        
        # Envoyer un email de notification au destinataire
        try:
            send_share_email(
                recipient_email=recipient.email,
                recipient_name=recipient.name,
                sender_name=current_user.name,
                video_title=video.title,
                message=message
            )
            logger.info(f"[SHARE EMAIL] Email de partage envoyé à {recipient.email}")
        except Exception as email_error:
            logger.error(f"[SHARE EMAIL ERROR] Erreur lors de l'envoi de l'email: {email_error}")
            # Ne pas bloquer le partage si l'email échoue
        
        db.session.commit()
        
        logger.info(f"Vidéo {video_id} partagée par {current_user.email} avec {recipient.email}")
        
        return api_response(
            data={'shared_video': shared_video.to_dict()},
            message=f'Vidéo partagée avec succès avec {recipient.name}',
            status=201
        )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du partage de vidéo: {e}")
        return api_response(error='Erreur lors du partage de la vidéo', status=500)


@video_sharing_bp.route('/shared-with-me', methods=['GET'])
@login_required
def get_shared_with_me():
    """Récupérer toutes les vidéos partagées avec l'utilisateur courant"""
    current_user = get_current_user()
    
    try:
        shared_videos = SharedVideo.query.filter_by(
            shared_with_user_id=current_user.id
        ).order_by(SharedVideo.shared_at.desc()).all()
        
        return api_response({
            'shared_videos': [sv.to_dict() for sv in shared_videos],
            'total': len(shared_videos)
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos partagées: {e}")
        return api_response(error='Erreur lors de la récupération des vidéos partagées', status=500)


@video_sharing_bp.route('/shared/<int:shared_video_id>', methods=['DELETE'])
@login_required
def remove_shared_access(shared_video_id):
    """Supprimer l'accès partagé à une vidéo"""
    current_user = get_current_user()
    
    # Trouver le partage
    shared_video = SharedVideo.query.get(shared_video_id)
    if not shared_video:
        return api_response(error='Partage non trouvé', status=404)
    
    # Vérifier que l'utilisateur est soit le propriétaire, soit le destinataire
    if shared_video.owner_user_id != current_user.id and shared_video.shared_with_user_id != current_user.id:
        return api_response(error='Vous n\'êtes pas autorisé à supprimer ce partage', status=403)
    
    try:
        db.session.delete(shared_video)
        db.session.commit()
        
        logger.info(f"Partage {shared_video_id} supprimé par l'utilisateur {current_user.id}")
        
        return api_response(message='Partage supprimé avec succès')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la suppression du partage: {e}")
        return api_response(error='Erreur lors de la suppression du partage', status=500)


@video_sharing_bp.route('/my-shared-videos', methods=['GET'])
@login_required
def get_my_shared_videos():
    """Récupérer toutes les vidéos que l'utilisateur a partagées avec d'autres"""
    current_user = get_current_user()
    
    try:
        shared_videos = SharedVideo.query.filter_by(
            owner_user_id=current_user.id
        ).order_by(SharedVideo.shared_at.desc()).all()
        
        return api_response({
            'shared_videos': [sv.to_dict() for sv in shared_videos],
            'total': len(shared_videos)
        })
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos partagées: {e}")
        return api_response(error='Erreur lors de la récupération des vidéos partagées', status=500)
