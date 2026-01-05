"""
Routes pour les messages de support
"""
from flask import Blueprint, request, jsonify, session
from src.models.database import db
from src.models.notification import (
    SupportMessage, SupportMessageStatus, SupportMessagePriority,
    Notification, NotificationType
)
from src.models.user import User, UserRole
import logging
import os
import json
from werkzeug.utils import secure_filename
import uuid

support_bp = Blueprint('support', __name__)
logger = logging.getLogger(__name__)


def require_auth():
    """Vérifier l'authentification"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return user_id


def require_admin():
    """Vérifier les droits admin"""
    user_id = session.get('user_id')
    if not user_id:
        return False
    
    user = User.query.get(user_id)
    if not user:
        return False
    
    return user.role in [UserRole.SUPER_ADMIN, UserRole.CLUB]


# ===== MESSAGES SUPPORT =====

@support_bp.route('/messages', methods=['POST'])
def create_support_message():
    """Créer un nouveau message support avec images optionnelles"""
    user_id = require_auth()
    if not user_id:
        return jsonify({"error": "Non authentifié"}), 401
    
    try:
        # Debug: log all received data
        logger.info(f"[SUPPORT DEBUG] Content-Type: {request.content_type}")
        logger.info(f"[SUPPORT DEBUG] Form data: {dict(request.form)}")
        logger.info(f"[SUPPORT DEBUG] Files: {list(request.files.keys())}")
        
        # Récupérer les données du formulaire
        subject = request.form.get('subject')
        message = request.form.get('message')
        priority = request.form.get('priority', 'medium')
        
        logger.info(f"[SUPPORT DEBUG] subject={subject}, message={message}, priority={priority}")
        
        if not subject or not message:
            return jsonify({"error": "Sujet et message requis"}), 400
        
        # Convertir priority string en enum
        try:
            priority_enum = SupportMessagePriority[priority.upper()]
        except KeyError:
            priority_enum = SupportMessagePriority.MEDIUM
        
        # Gérer les images uploadées
        image_urls = []
        if 'images' in request.files:
            files = request.files.getlist('images')
            
            # Créer le dossier uploads s'il n'existe pas
            upload_folder = os.path.join('uploads', 'support')
            os.makedirs(upload_folder, exist_ok=True)
            
            for file in files:
                if file and file.filename:
                    # Sécuriser le nom de fichier
                    filename = secure_filename(file.filename)
                    # Générer un nom unique
                    unique_filename = f"{uuid.uuid4().hex}_{filename}"
                    filepath = os.path.join(upload_folder, unique_filename)
                    
                    # Sauvegarder le fichier
                    file.save(filepath)
                    
                    # Stocker l'URL relative
                    image_url = f"/uploads/support/{unique_filename}"
                    image_urls.append(image_url)
        
        # Créer le message support
        support_message = SupportMessage(
            user_id=user_id,
            subject=subject,
            message=message,
            priority=priority_enum,
            images=json.dumps(image_urls) if image_urls else None
        )
        
        db.session.add(support_message)
        db.session.commit()
        
        # Créer une notification
        Notification.create_notification(
            user_id=user_id,
            notification_type=NotificationType.SUPPORT,
            title="Message envoyé au support",
            message=f"Votre message '{subject}' a été envoyé au support."
        )
        db.session.commit()
        
        return jsonify({
            "message": "Message envoyé au support",
            "support_message": support_message.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur création message support: {e}")
        return jsonify({"error": str(e)}), 500


@support_bp.route('/messages', methods=['GET'])
def get_support_messages():
    """Récupérer les messages support de l'utilisateur"""
    user_id = require_auth()
    if not user_id:
        return jsonify({"error": "Non authentifié"}), 401
    
    try:
        messages = SupportMessage.get_user_messages(user_id)
        
        return jsonify({
            "messages": [m.to_dict() for m in messages],
            "count": len(messages)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur récupération messages support: {e}")
        return jsonify({"error": str(e)}), 500


# ===== ADMIN ROUTES =====

@support_bp.route('/admin/messages', methods=['GET'])
def get_all_support_messages():
    """Récupérer tous les messages support (admin)"""
    if not require_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        status_filter = request.args.get('status')
        
        # Convertir status string en enum si fourni
        status_enum = None
        if status_filter:
            try:
                status_enum = SupportMessageStatus[status_filter.upper()]
            except KeyError:
                pass
        
        messages = SupportMessage.get_all_messages(status=status_enum)
        
        return jsonify({
            "messages": [m.to_dict(include_user=True) for m in messages],
            "count": len(messages)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur récupération tous messages support: {e}")
        return jsonify({"error": str(e)}), 500


@support_bp.route('/admin/messages/<int:message_id>', methods=['PATCH'])
def update_support_message(message_id):
    """Mettre à jour un message support (admin)"""
    if not require_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        admin_id = session.get('user_id')
        
        admin_response = data.get('admin_response')
        status = data.get('status')
        
        # Convertir status string en enum si fourni
        status_enum = None
        if status:
            try:
                status_enum = SupportMessageStatus[status.upper()]
            except KeyError:
                return jsonify({"error": "Statut invalide"}), 400
        
        message = SupportMessage.update_message(
            message_id=message_id,
            admin_id=admin_id,
            admin_response=admin_response,
            status=status_enum
        )
        
        if not message:
            return jsonify({"error": "Message introuvable"}), 404
        
        # Créer une notification pour l'utilisateur si l'admin a répondu
        if admin_response:
            try:
                Notification.create_notification(
                    user_id=message.user_id,
                    notification_type=NotificationType.SUPPORT,
                    title="Réponse du support",
                    message=f"Votre message '{message.subject}' a reçu une réponse",
                    link=f"/player"  # Lien vers le dashboard
                )
                logger.info(f"Notification créée pour user {message.user_id} - réponse support #{message_id}")
            except Exception as notif_error:
                logger.error(f"Erreur création notification: {notif_error}")
        
        return jsonify({
            "message": "Message mis à jour",
            "support_message": message.to_dict(include_user=True)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur mise à jour message support: {e}")
        return jsonify({"error": str(e)}), 500
