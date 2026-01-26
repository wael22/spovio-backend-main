# padelvar-backend/src/routes/admin.py

from flask import Blueprint, request, jsonify, session
from src.models.user import db, User, Club, Court, Video, UserRole, ClubActionHistory, RecordingSession, ClubOverlay, SharedVideo, UserClip, HighlightJob, HighlightVideo, Transaction, IdempotencyKey
from src.models.system_configuration import SystemConfiguration, ConfigType
from src.models.notification import Notification, NotificationType, SupportMessage
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, joinedload
import uuid
import logging
import json
import random
import os
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)

# --- Fonctions Utilitaires ---

def require_super_admin():
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    
    # Debug logging pour comprendre le problème
    logger.info(f"🔍 Vérification admin - user_id: {user_id}, user_role: {user_role}")
    logger.info(f"🔍 UserRole.SUPER_ADMIN.value: {UserRole.SUPER_ADMIN.value}")
    
    if not user_id:
        logger.warning("❌ Pas d'user_id dans la session")
        return False
        
    if not user_role:
        logger.warning("❌ Pas de user_role dans la session")
        return False
    
    # Vérification flexible du rôle admin
    admin_roles = [
        UserRole.SUPER_ADMIN.value,
        "SUPER_ADMIN",
        "super_admin",
        "ADMIN",
        "admin"
    ]
    
    if user_role not in admin_roles:
        logger.warning(f"❌ Rôle '{user_role}' n'est pas admin. Rôles acceptés: {admin_roles}")
        return False
    
    logger.info(f"✅ Accès admin accordé pour user_id: {user_id} avec rôle: {user_role}")
    return True

def log_club_action(user_id, club_id, action_type, details=None, performed_by_id=None):
    """Log d'action avec normalisation du type d'action"""
    try:
        if performed_by_id is None:
            performed_by_id = user_id
        
        if not club_id:
            db.session.commit()
            return

        # Normaliser le type d'action avant de l'enregistrer
        normalized_action_type = action_type.lower().strip().replace('-', '_').replace(' ', '_')
        
        # S'assurer que les détails sont en format JSON
        details_json = None
        if details:
            if isinstance(details, dict):
                details_json = json.dumps(details)
            elif isinstance(details, str):
                try:
                    # Vérifier si c'est déjà du JSON valide
                    json.loads(details)
                    details_json = details
                except json.JSONDecodeError:
                    # Si ce n'est pas du JSON, l'envelopper
                    details_json = json.dumps({"raw_details": details})
            else:
                details_json = json.dumps({"raw_details": str(details)})

        history_entry = ClubActionHistory(
            user_id=user_id,
            club_id=club_id,
            action_type=normalized_action_type,
            action_details=details_json,
            performed_by_id=performed_by_id,
            performed_at=datetime.utcnow()
        )
        db.session.add(history_entry)
        db.session.commit()
        
        logger.info(f"Action loggée: {normalized_action_type} pour utilisateur {user_id} dans club {club_id}")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'enregistrement de l'historique: {e}")
        # Ne pas lever l'exception pour éviter d'interrompre le flux principal

# --- ROUTES DE GESTION DES UTILISATEURS (CRUD COMPLET) ---

@admin_bp.route("/users", methods=["GET"])
def get_all_users():
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    users = User.query.all()
    users_data = []
    for user in users:
        user_dict = user.to_dict()
        # Compter les vidéos de cet utilisateur
        video_count = Video.query.filter_by(user_id=user.id).count()
        user_dict['video_count'] = video_count
        users_data.append(user_dict)
    return jsonify({"users": users_data}), 200

@admin_bp.route("/users", methods=["POST"])
def create_user():
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    data = request.get_json()
    try:
        new_user = User(
            email=data["email"].lower().strip(),
            name=data["name"].strip(),
            role=UserRole(data["role"]),
            phone_number=data.get("phone_number"),
            credits_balance=data.get("credits_balance", 0)
        )
        if data.get("password"):
            new_user.password_hash = generate_password_hash(data["password"])
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": "Utilisateur créé", "user": new_user.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Erreur lors de la création"}), 500

@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    try:
        if "name" in data: user.name = data["name"]
        if "phone_number" in data: user.phone_number = data["phone_number"]
        if "credits_balance" in data: user.credits_balance = data["credits_balance"]
        if "role" in data: user.role = UserRole(data["role"])
        db.session.commit()
        return jsonify({"message": "Utilisateur mis à jour", "user": user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Erreur lors de la mise à jour"}), 500

@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    user = User.query.get_or_404(user_id)
    try:
        print(f"🗑️ Suppression de l'utilisateur ID: {user_id} - {user.name} ({user.email})")
        
        # 1. Gérer les vidéos associées
        # D'abord, nettoyer les partages de vidéos impliquant cet utilisateur
        SharedVideo.query.filter(
            (SharedVideo.owner_user_id == user_id) | 
            (SharedVideo.shared_with_user_id == user_id)
        ).delete(synchronize_session=False)
        print(f"   🔗 Partages de vidéos supprimés pour l'utilisateur")

        videos = Video.query.filter_by(user_id=user_id).all()
        for video in videos:
            # Supprimer les partages liés à cette vidéo spécifique
            SharedVideo.query.filter_by(video_id=video.id).delete(synchronize_session=False)
            
            # Supprimer les clips utilisateur liés à cette vidéo
            UserClip.query.filter_by(video_id=video.id).delete(synchronize_session=False)
            
            # Supprimer les jobs de highlights liés à cette vidéo
            HighlightJob.query.filter_by(video_id=video.id).delete(synchronize_session=False)
            
            # Supprimer les vidéos highlights générées liées à cette vidéo
            HighlightVideo.query.filter_by(original_video_id=video.id).delete(synchronize_session=False)
            
            print(f"   📹 Suppression vidéo {video.id} (cascade: shares, clips, highlights)")
            db.session.delete(video)
        
        # 2. Gérer les sessions d'enregistrement
        recording_sessions = RecordingSession.query.filter_by(user_id=user_id).all()
        for session in recording_sessions:
            print(f"   🎬 Suppression session: {session.recording_id}")
            db.session.delete(session)
        
        # 3. Gérer l'historique des actions
        history_entries = ClubActionHistory.query.filter_by(user_id=user_id).all()
        for entry in history_entries:
            db.session.delete(entry)  # Supprimer l'entrée (user_id ne peut pas être NULL)
            print(f"   📝 Historique {entry.id} supprimé")
        
        # 4. Gérer l'historique où l'utilisateur était le performeur
        performed_entries = ClubActionHistory.query.filter_by(performed_by_id=user_id).all()
        for entry in performed_entries:
            db.session.delete(entry)  # Supprimer l'entrée (performed_by_id ne peut pas être NULL)
            print(f"   📝 Historique {entry.id} supprimé (performed_by)")
        
        # 5. Si c'est un utilisateur club, gérer les relations club
        if user.role == UserRole.CLUB and user.club_id:
            club = Club.query.get(user.club_id)
            if club:
                print(f"   🏢 Utilisateur club détecté pour: {club.name}")
                # Optionnel: supprimer le club aussi ou le laisser orphelin
                # Pour l'instant, on le laisse orphelin
        
        # 6. Gérer les relations many-to-many (follows)
        if hasattr(user, 'followed_clubs'):
            # Pour les relations many-to-many, il faut supprimer les relations explicitement
            user.followed_clubs = []  # Vider la relation
            print(f"   🔗 Relations de suivi supprimées")
        
        # 7. Supprimer les notifications de l'utilisateur
        Notification.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        print(f"   🔔 Notifications supprimées pour l'utilisateur")
        
        # 8. Supprimer les transactions de l'utilisateur
        Transaction.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        print(f"   💰 Transactions supprimées pour l'utilisateur")
        
        # 9. Supprimer les messages de support de l'utilisateur
        SupportMessage.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        print(f"   📞 Messages support supprimés pour l'utilisateur")
        
        # 10. Supprimer les clés d'idempotence
        IdempotencyKey.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 11. Supprimer les clips créés PAR l'utilisateur (sur n'importe quelle vidéo)
        UserClip.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        print(f"   ✂️ Clips utilisateur supprimés")

        # 12. Supprimer les jobs de highlights demandés PAR l'utilisateur
        HighlightJob.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        print(f"   ✨ Jobs highlights supprimés")

        # 13. Supprimer l'utilisateur lui-même
        print(f"   👤 Suppression de l'utilisateur: {user.name}")
        db.session.delete(user)
        
        db.session.commit()
        
        return jsonify({
            "message": "Utilisateur supprimé avec succès",
            "videos_orphaned": len(videos),
            "recording_sessions_deleted": len(recording_sessions),
            "history_entries_deleted": len(history_entries) + len(performed_entries)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur lors de la suppression de l'utilisateur {user_id}: {e}")
        logger.error(f"Erreur lors de la suppression de l'utilisateur {user_id}: {e}")
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500

@admin_bp.route("/users/<int:user_id>/credits", methods=["POST"])
def add_credits(user_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    credits_to_add = data.get("credits", 0)
    
    if not isinstance(credits_to_add, int) or credits_to_add <= 0:
        return jsonify({"error": "Le nombre de crédits doit être un entier positif"}), 400

    try:
        old_balance = user.credits_balance
        user.credits_balance += credits_to_add
        
        log_club_action(
            user_id=user.id, 
            club_id=user.club_id,
            action_type='add_credits', 
            details={'credits_added': credits_to_add, 'old_balance': old_balance, 'new_balance': user.credits_balance}, 
            performed_by_id=session.get('user_id')
        )
        
        # Créer une notification pour le joueur
        try:
            notification = Notification(
                user_id=user.id,
                notification_type=NotificationType.CREDIT,
                title="🎁 Crédits offerts !",
                message=f"L'administrateur vous a offert {credits_to_add} crédits. Nouveau solde : {user.credits_balance} crédits",
                link="/player"
            )
            db.session.add(notification)
            logger.info(f"✅ Notification créée pour le joueur {user.id} - {credits_to_add} crédits offerts par l'admin")
        except Exception as notif_error:
            logger.error(f"❌ Erreur création notification pour crédits offerts par admin: {notif_error}")
        
        db.session.commit()
        
        return jsonify({"message": "Crédits ajoutés", "user": user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'ajout de crédits: {e}")
        return jsonify({"error": "Erreur lors de l'ajout de crédits"}), 500

@admin_bp.route("/clubs/<int:club_id>/credits", methods=["POST"])
def add_credits_to_club(club_id):
    """Offrir des crédits à un club (admin uniquement)"""
    if not require_super_admin(): 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    club = Club.query.get_or_404(club_id)
    data = request.get_json()
    credits_to_add = data.get("credits", 0)
    
    if not isinstance(credits_to_add, int) or credits_to_add <= 0:
        return jsonify({"error": "Le nombre de crédits doit être un entier positif"}), 400

    try:
        old_balance = club.credits_balance
        club.credits_balance += credits_to_add
        
        # Récupérer l'utilisateur du club pour l'historique
        club_user = User.query.filter_by(club_id=club.id, role=UserRole.CLUB).first()
        
        # Logger dans l'historique
        log_club_action(
            user_id=club_user.id if club_user else session.get('user_id'),  # Utiliser l'ID de l'utilisateur du club ou celui de l'admin
            club_id=club.id,
            action_type='receive_credits_from_admin', 
            details={
                'credits_received': credits_to_add, 
                'old_balance': old_balance, 
                'new_balance': club.credits_balance
            }, 
            performed_by_id=session.get('user_id')
        )
        
        # Créer une notification pour l'utilisateur club
        if club_user:
            try:
                notification = Notification(
                    user_id=club_user.id,
                    notification_type=NotificationType.CREDIT,
                    title="🎁 Crédits offerts !",
                    message=f"L'administrateur a offert {credits_to_add} crédits à votre club. Nouveau solde : {club.credits_balance} crédits",
                    link="/club"
                )
                db.session.add(notification)
                logger.info(f"✅ Notification créée pour le club {club.id} - {credits_to_add} crédits offerts par l'admin")
            except Exception as notif_error:
                logger.error(f"❌ Erreur création notification pour crédits offerts au club: {notif_error}")
        
        db.session.commit()
        
        return jsonify({
            "message": "Crédits ajoutés au club", 
            "club": club.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'ajout de crédits au club: {e}")
        return jsonify({"error": "Erreur lors de l'ajout de crédits"}), 500

# --- ROUTES DE GESTION DES CLUBS (CRUD COMPLET) ---

@admin_bp.route("/clubs", methods=["GET"])
def get_all_clubs():
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    clubs = Club.query.all()
    clubs_data = []
    for club in clubs:
        club_dict = club.to_dict()
        # Compter les vidéos de tous les courts de ce club
        video_count = db.session.query(Video).join(Court).filter(Court.club_id == club.id).count()
        club_dict['video_count'] = video_count
        clubs_data.append(club_dict)
    return jsonify({"clubs": clubs_data}), 200

@admin_bp.route("/clubs", methods=["POST"])
def create_club():
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    data = request.get_json()
    try:
        new_club = Club(name=data["name"], email=data["email"], address=data.get("address"), phone_number=data.get("phone_number"))
        db.session.add(new_club)
        db.session.flush()
        club_user = User(email=data["email"], name=data["name"], role=UserRole.CLUB, club_id=new_club.id, email_verified=True, email_verified_at=datetime.utcnow())
        if data.get("password"):
            club_user.password_hash = generate_password_hash(data["password"])
        db.session.add(club_user)
        db.session.commit()
        return jsonify({"message": "Club créé", "club": new_club.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Erreur lors de la création"}), 500


# ====================================================================
# CORRECTION DE LA SYNCHRONISATION (ADMIN -> CLUB)
# ====================================================================

@admin_bp.route("/sync/club-user-data", methods=["POST"])
def sync_club_user_data():
    """Synchroniser les données entre les clubs et leurs utilisateurs associés"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        logger.info("Début de la synchronisation club-utilisateur")
        
        # Récupérer tous les clubs avec leurs utilisateurs associés
        clubs = Club.query.all()
        sync_results = {
            'clubs_processed': 0,
            'sync_corrections': 0,
            'errors': [],
            'details': []
        }
        
        for club in clubs:
            sync_results['clubs_processed'] += 1
            club_user = User.query.filter_by(club_id=club.id, role=UserRole.CLUB).first()
            
            if club_user:
                corrections_needed = []
                
                # Vérifier les divergences
                if club.name != club_user.name:
                    corrections_needed.append(f"Nom: '{club_user.name}' → '{club.name}'")
                    club_user.name = club.name
                
                if club.email != club_user.email:
                    corrections_needed.append(f"Email: '{club_user.email}' → '{club.email}'")
                    club_user.email = club.email
                
                if club.phone_number != club_user.phone_number:
                    corrections_needed.append(f"Téléphone: '{club_user.phone_number}' → '{club.phone_number}'")
                    club_user.phone_number = club.phone_number
                
                if corrections_needed:
                    sync_results['sync_corrections'] += 1
                    sync_results['details'].append({
                        'club_id': club.id,
                        'club_name': club.name,
                        'corrections': corrections_needed
                    })
                    logger.info(f"Synchronisation club {club.id}: {corrections_needed}")
                    
            else:
                # Club sans utilisateur associé - créer l'utilisateur
                try:
                    from werkzeug.security import generate_password_hash
                    new_club_user = User(
                        email=club.email,
                        password_hash=generate_password_hash('default123'),  # Mot de passe temporaire
                        name=club.name,
                        role=UserRole.CLUB,
                        club_id=club.id,
                        phone_number=club.phone_number,
                        credits_balance=0
                    )
                    db.session.add(new_club_user)
                    sync_results['details'].append({
                        'club_id': club.id,
                        'club_name': club.name,
                        'corrections': ['Utilisateur créé - mot de passe: default123']
                    })
                    logger.info(f"Utilisateur créé pour le club {club.id}")
                except Exception as e:
                    sync_results['errors'].append(f"Erreur création utilisateur club {club.id}: {str(e)}")
        
        db.session.commit()
        
        return jsonify({
            'message': 'Synchronisation terminée',
            'results': sync_results
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la synchronisation: {e}")
        return jsonify({'error': f'Erreur synchronisation: {str(e)}'}), 500

@admin_bp.route("/clubs/<int:club_id>", methods=["PUT"])
def update_club(club_id):
    if not require_super_admin(): 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    club = Club.query.get_or_404(club_id)
    # On trouve l'utilisateur associé à ce club
    club_user = User.query.filter_by(club_id=club_id, role=UserRole.CLUB).first()
    
    data = request.get_json()
    
    try:
        # Mettre à jour l'objet Club
        if "name" in data: 
            club.name = data["name"].strip()
        if "address" in data: 
            club.address = data["address"]
        if "phone_number" in data: 
            club.phone_number = data["phone_number"]
        if "email" in data: 
            club.email = data["email"].strip()
        
        # SYNCHRONISATION BIDIRECTIONNELLE: Mettre à jour l'utilisateur associé
        if club_user:
            if "name" in data:
                club_user.name = club.name
            if "email" in data:
                club_user.email = club.email  
            if "phone_number" in data:
                club_user.phone_number = club.phone_number
                
            logger.info(f"Synchronisation admin→club: Club {club_id} et utilisateur {club_user.id} mis à jour")
        else:
            logger.warning(f"Aucun utilisateur associé trouvé pour le club {club_id}")
        
        db.session.commit()
        
        # Log de l'action pour traçabilité
        log_club_action(
            user_id=club_user.id if club_user else None,
            club_id=club_id,
            action_type='admin_update_club',
            details={
                'updated_fields': list(data.keys()),
                'admin_user_id': session.get('user_id'),
                'sync_user_updated': club_user is not None
            },
            performed_by_id=session.get('user_id')
        )
        
        return jsonify({
            "message": "Club mis à jour avec succès", 
            "club": club.to_dict(),
            "user_synchronized": club_user is not None
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la mise à jour du club par l'admin: {e}")
        return jsonify({"error": "Erreur lors de la mise à jour"}), 500

@admin_bp.route("/clubs/<int:club_id>", methods=["DELETE"])
def delete_club(club_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    club = Club.query.get_or_404(club_id)
    try:
        # Importer les modèles nécessaires
        from src.models.user import Video, RecordingSession, ClubActionHistory
        
        print(f"🗑️ Suppression du club ID: {club_id} - {club.name}")
        
        # 1. Gérer les terrains et leurs contraintes
        courts = Court.query.filter_by(club_id=club_id).all()
        videos_orphaned = 0
        recording_sessions_deleted = 0
        
        for court in courts:
            print(f"   🏟️ Traitement du terrain: {court.name}")
            
            # Gérer les vidéos de ce terrain
            court_videos = Video.query.filter_by(court_id=court.id).all()
            for video in court_videos:
                video.court_id = None
                videos_orphaned += 1
                print(f"     📹 Vidéo {video.id} rendue orpheline")
            
            # Gérer les sessions d'enregistrement de ce terrain
            court_sessions = RecordingSession.query.filter_by(court_id=court.id).all()
            for session in court_sessions:
                print(f"     🎬 Suppression session: {session.recording_id}")
                db.session.delete(session)
                recording_sessions_deleted += 1
        
        # 2. Supprimer tous les terrains du club
        Court.query.filter_by(club_id=club_id).delete()
        print(f"   🏟️ {len(courts)} terrain(s) supprimé(s)")
        
        # 3. Gérer les utilisateurs du club
        club_users = User.query.filter_by(club_id=club_id).all()
        for user in club_users:
            print(f"   👤 Traitement utilisateur: {user.name} ({user.role.value})")
            
            # Gérer les vidéos de cet utilisateur (les rendre orphelines)
            user_videos = Video.query.filter_by(user_id=user.id).all()
            for video in user_videos:
                if video.user_id == user.id:  # Éviter les doublons
                    video.user_id = None
                    print(f"     📹 Vidéo {video.id} rendue orpheline")
            
            # Gérer les sessions d'enregistrement de cet utilisateur
            user_sessions = RecordingSession.query.filter_by(user_id=user.id).all()
            for session in user_sessions:
                if session not in [s for s in RecordingSession.query.filter_by(court_id=None).all()]:
                    print(f"     🎬 Suppression session utilisateur: {session.recording_id}")
                    db.session.delete(session)
            
            # Gérer les relations many-to-many (follows)
            if hasattr(user, 'followed_clubs'):
                user.followed_clubs = []
        
        # 4. Gérer l'historique du club
        history_entries = ClubActionHistory.query.filter_by(club_id=club_id).all()
        for entry in history_entries:
            entry.club_id = None  # Anonymiser plutôt que supprimer
            print(f"   📝 Historique {entry.id} anonymisé")
        
        # 5. Supprimer les utilisateurs du club
        User.query.filter_by(club_id=club_id).delete()
        print(f"   👤 {len(club_users)} utilisateur(s) supprimé(s)")
        
        # 6. Gérer les relations many-to-many avec les followers
        if hasattr(club, 'followers'):
            # Supprimer toutes les relations de suivi de ce club
            club.followers = []
            print(f"   🔗 Relations de suivi du club supprimées")
        
        # 7. Supprimer le club lui-même
        print(f"   🏢 Suppression du club: {club.name}")
        db.session.delete(club)
        
        db.session.commit()
        
        return jsonify({
            "message": "Club supprimé avec succès",
            "courts_deleted": len(courts),
            "users_deleted": len(club_users),
            "videos_orphaned": videos_orphaned,
            "recording_sessions_deleted": recording_sessions_deleted,
            "history_entries_anonymized": len(history_entries)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur lors de la suppression du club {club_id}: {e}")
        logger.error(f"Erreur lors de la suppression du club {club_id}: {e}")
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500

# --- ROUTES DE GESTION DES TERRAINS (CRUD COMPLET) ---

@admin_bp.route("/clubs/<int:club_id>/courts", methods=["GET"])
def get_club_courts(club_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    club = Club.query.get_or_404(club_id)
    return jsonify({"courts": [court.to_dict() for court in club.courts]}), 200

@admin_bp.route("/clubs/<int:club_id>/courts", methods=["POST"])
def create_court(club_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    data = request.get_json()
    try:
        new_court = Court(name=data["name"], camera_url=data["camera_url"], club_id=club_id, qr_code=str(uuid.uuid4()))
        db.session.add(new_court)
        db.session.commit()
        return jsonify({"message": "Terrain créé", "court": new_court.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Erreur lors de la création"}), 500

@admin_bp.route("/courts/<int:court_id>", methods=["PUT"])
def update_court(court_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    court = Court.query.get_or_404(court_id)
    data = request.get_json()
    try:
        if "name" in data: court.name = data["name"]
        if "camera_url" in data: court.camera_url = data["camera_url"]
        
        # Allow admin to update QR code
        if "qr_code" in data:
            new_qr_code = data["qr_code"].strip()
            # Check if QR code is unique (excluding current court)
            existing_court = Court.query.filter(
                Court.qr_code == new_qr_code,
                Court.id != court_id
            ).first()
            if existing_court:
                return jsonify({"error": f"Ce code QR est déjà utilisé par le terrain '{existing_court.name}'"}), 400
            court.qr_code = new_qr_code
        
        db.session.commit()
        return jsonify({"message": "Terrain mis à jour", "court": court.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Erreur lors de la mise à jour"}), 500

@admin_bp.route("/courts/<int:court_id>", methods=["DELETE"])
def delete_court(court_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    court = Court.query.get_or_404(court_id)
    try:
        print(f"🗑️ Suppression du terrain ID: {court_id} - {court.name}")
        
        # 1. Gérer les vidéos associées (les déplacer vers NULL)
        videos = Video.query.filter_by(court_id=court_id).all()
        for video in videos:
            video.court_id = None
            print(f"   📹 Vidéo {video.id} déplacée: court_id -> NULL")
        
        # 2. Gérer les sessions d'enregistrement (les supprimer ou les marquer)
        recording_sessions = RecordingSession.query.filter_by(court_id=court_id).all()
        for session in recording_sessions:
            print(f"   🎬 Suppression session: {session.recording_id} (statut: {session.status})")
            db.session.delete(session)
        
        # 3. Supprimer le terrain lui-même
        print(f"   🏟️ Suppression du terrain: {court.name}")
        db.session.delete(court)
        
        db.session.commit()
        
        return jsonify({
            "message": "Terrain supprimé avec succès",
            "videos_updated": len(videos),
            "recording_sessions_deleted": len(recording_sessions)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Erreur lors de la suppression du terrain {court_id}: {e}")
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500


# --- NOUVELLES ROUTES ADMIN POUR CONTRÔLE DES TERRAINS ---

@admin_bp.route("/courts/<int:court_id>/toggle-status", methods=["POST"])
def toggle_court_status(court_id):
    """Basculer manuellement l'état de disponibilité d'un terrain (admin uniquement)"""
    if not require_super_admin(): 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    court = Court.query.get_or_404(court_id)
    
    try:
        # Inverser l'état is_recording
        court.is_recording = not court.is_recording
        db.session.commit()
        
        status_text = "Indisponible" if court.is_recording else "Disponible"
        
        logger.info(f"Admin: Terrain {court.id} ({court.name}) -> {status_text}")
        
        return jsonify({
            "message": f"Statut du terrain modifié: {status_text}",
            "court": court.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la modification du statut du terrain: {e}")
        return jsonify({"error": "Erreur lors de la modification"}), 500


@admin_bp.route("/recordings/<recording_id>/stop", methods=["POST"])
def admin_stop_recording(recording_id):
    """Arrêter un enregistrement en cours (admin uniquement)"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Récupérer la session d'enregistrement
        active_recording = RecordingSession.query.filter_by(
            recording_id=recording_id,
            status='active'
        ).first()
        
        if not active_recording:
            return jsonify({"error": "Session d'enregistrement non trouvée ou déjà terminée"}), 404
        
        # Récupérer le terrain
        court = Court.query.get(active_recording.court_id)
        if not court:
            return jsonify({"error": "Terrain non trouvé"}), 404
        
        # Marquer la session comme terminée
        active_recording.status = 'stopped'
        active_recording.end_time = datetime.utcnow()
        active_recording.stopped_by = 'admin'
        
        # Libérer le terrain
        court.is_recording = False
        court.current_recording_id = None
        logger.info(f"🔓 Terrain {court.name} libéré (enregistrement admin)")

        # Calculer la durée estimée
        duration_minutes = 1
        if active_recording.start_time:
            duration_seconds = (active_recording.end_time - active_recording.start_time).total_seconds()
            duration_minutes = max(1, int(duration_seconds / 60))

        # 🆕 Arrêter l'enregistrement vidéo via NOUVEAU système
        from src.video_system.session_manager import session_manager
        from src.video_system.recording import video_recorder
        
        video_file_url = None
        try:
            # Arrêter enregistrement FFmpeg
            video_file_path = video_recorder.stop_recording(active_recording.recording_id)
            logger.info(f"Arrêt enregistrement via nouveau système: {video_file_path}")
            
            # Fermer session proxy
            session = session_manager.get_session(active_recording.recording_id)
            if session:
                session.recording_active = False
            session_manager.close_session(active_recording.recording_id)
            
            # Déterminer URL fichier
            if video_file_path and os.path.exists(video_file_path):
                video_file_url = video_file_path
            else:
                # Fallback search
                possible_paths = [
                    f"static/videos/{court.club_id}/{active_recording.recording_id}.mp4",
                    f"static/videos/{active_recording.recording_id}.mp4"
                ]
                for path in possible_paths:
                    if os.path.exists(path):
                        video_file_url = path
                        break
                
        except Exception as e:
            logger.warning(f"Erreur lors de l'arrêt du service vidéo: {e}")

        # Créer la vidéo en base
        # Format: "Match [jour/mois], Terrain [n°], [nom club]"
        recorded_date = active_recording.start_time.strftime('%d/%m') if active_recording.start_time else datetime.now().strftime('%d/%m')
        club = Club.query.get(court.club_id) if court.club_id else None
        club_name = club.name if club else "Club"
        video_title = active_recording.title or f"Match {recorded_date}, {court.name}, {club_name}"
        
        new_video = Video(
            title=video_title,
            description=f"Arrêté par administrateur le {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            duration=duration_minutes * 60, # Temporaire, sera affiné
            user_id=active_recording.user_id,
            court_id=court.id,
            recorded_at=active_recording.start_time,
            file_url=video_file_url,
            local_file_path=video_file_url,  # ✅ AJOUTÉ: Sauvegarder le chemin local du fichier
            is_unlocked=True,
            credits_cost=0
        )
        
        # Vérification durée réelle avec FFprobe
        if video_file_url and os.path.exists(video_file_url):
            try:
                import time
                time.sleep(1) # Attendre flush disque
                
                from src.services.ffmpeg_runner import FFmpegRunner
                runner = FFmpegRunner()
                ffprobe_result = runner.probe_video_info(video_file_url)
                
                if ffprobe_result:
                    real_duration_seconds = ffprobe_result['duration']
                    new_video.duration = int(real_duration_seconds)
                    logger.info(f"🎯 Durée réelle FFprobe appliquée: {new_video.duration}s")
            except Exception as e:
                logger.warning(f"⚠️ Erreur lecture durée réelle: {e}")

        db.session.add(new_video)
        db.session.flush() # Pour avoir l'ID
        
        # Upload Bunny CDN
        if video_file_url and os.path.exists(video_file_url):
            try:
                from src.services.bunny_storage_service import bunny_storage_service
                logger.info(f"🚀 Début upload vers Bunny CDN: {video_file_url}")
                
                upload_id = bunny_storage_service.queue_upload(
                    local_path=video_file_url,
                    title=new_video.title,
                    metadata={
                        'video_id': new_video.id,
                        'user_id': active_recording.user_id,
                        'court_id': court.id,
                        'recording_id': active_recording.recording_id,
                        'duration': new_video.duration
                    }
                )
                logger.info(f"✅ Upload Bunny programmé: {upload_id}")
                
                # ✨ NEW: Wait briefly for upload to complete and extract bunny_video_id
                import time
                time.sleep(3)  # Give queue time to process and create video
                
                upload_status = bunny_storage_service.get_upload_status(upload_id)
                if upload_status and upload_status.get('bunny_video_id'):
                    new_video.bunny_video_id = upload_status['bunny_video_id']
                    # ✨ NEW: Also update file_url to Bunny CDN URL
                    new_video.file_url = f"https://vz-cc4565cd-4e9.b-cdn.net/{new_video.bunny_video_id}/playlist.m3u8"
                    logger.info(f"✅ Bunny video ID saved: {new_video.bunny_video_id}")
                    logger.info(f"✅ Bunny URL updated: {new_video.file_url}")
                else:
                    logger.warning(f"⚠️ Upload status: {upload_status}")
            except Exception as e:
                logger.warning(f"⚠️ Erreur upload Bunny: {e}")
        
        db.session.commit()
        
        logger.info(f"✅ Enregistrement {recording_id} arrêté par admin - Vidéo ID: {new_video.id}")
        
        # Créer une notification pour l'utilisateur
        try:
            from src.models.notification import Notification, NotificationType
            
            Notification.create_notification(
                user_id=new_video.user_id,
                notification_type=NotificationType.VIDEO,
                title="Vidéo prête !",
                message=f"Votre enregistrement est terminé et disponible ({duration_seconds}s)",
                link="/player"  # Lien vers le dashboard
            )
            logger.info(f"✅ Notification créée pour user {new_video.user_id} - vidéo #{new_video.id}")
        except Exception as notif_error:
            logger.error(f"❌ Erreur création notification: {notif_error}")
        
        return jsonify({
            "message": "Enregistrement arrêté avec succès",
            "recording_id": recording_id,
            "video_id": new_video.id,
            "duration_seconds": new_video.duration
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur arrêt admin: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erreur lors de l'arrêt: {str(e)}"}), 500


@admin_bp.route("/recordings/active", methods=["GET"])
def get_all_active_recordings():
    """Récupérer tous les enregistrements actifs de tous les clubs (admin uniquement)"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Récupérer toutes les sessions actives
        active_sessions = RecordingSession.query.filter_by(status='active').all()
        
        recordings_data = []
        for session in active_sessions:
            session_data = session.to_dict()
            
            # Ajouter les infos utilisateur
            player = User.query.get(session.user_id)
            if player:
                session_data['player'] = {
                    'id': player.id,
                    'name': player.name,
                    'email': player.email
                }
            
            # Ajouter les infos terrain et club
            court = Court.query.get(session.court_id)
            if court:
                session_data['court'] = court.to_dict()
                club = Club.query.get(court.club_id)
                if club:
                    session_data['club'] = club.to_dict()
            
            recordings_data.append(session_data)
        
        return jsonify({
            'active_recordings': recordings_data,
            'count': len(recordings_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des enregistrements actifs: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

# --- ROUTES VIDÉOS & HISTORIQUE ---

@admin_bp.route("/videos", methods=["GET"])
def get_all_clubs_videos():
    if not require_super_admin(): 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Requête simplifiée sans les colonnes problématiques - TRIÉE PAR DATE DÉCROISSANTE
        videos = db.session.query(Video).order_by(Video.created_at.desc()).all()

        videos_data = []
        for video in videos:
            # 🆕 Utiliser to_dict() pour avoir tous les champs (has_local_file, has_cloud_file, etc.)
            video_dict = video.to_dict()
            
            # Ajouter les informations relationnelles
            if hasattr(video, 'owner') and video.owner:
                video_dict['player_name'] = video.owner.name
            else:
                # Requête manuelle si la relation ne fonctionne pas
                user = User.query.get(video.user_id)
                video_dict['player_name'] = user.name if user else "Utilisateur supprimé"
            
            if hasattr(video, 'court') and video.court:
                video_dict['court_name'] = video.court.name
                if hasattr(video.court, 'club') and video.court.club:
                    video_dict['club_name'] = video.court.club.name
                else:
                    club = Club.query.get(video.court.club_id)
                    video_dict['club_name'] = club.name if club else "Club inconnu"
            else:
                # Requête manuelle si la relation ne fonctionne pas
                court = Court.query.get(video.court_id)
                if court:
                    video_dict['court_name'] = court.name
                    club = Club.query.get(court.club_id)
                    video_dict['club_name'] = club.name if club else "Club inconnu"
                else:
                    video_dict['court_name'] = "Terrain inconnu"
                    video_dict['club_name'] = "Club inconnu"
            
            videos_data.append(video_dict)
        
        return jsonify({"videos": videos_data}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos: {e}")
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500

# ====================================================================
# CORRECTION MAJEURE ICI
# ====================================================================
def normalize_action_type(action_type):
    """Normalise et traduit les types d'actions pour l'affichage"""
    action_mapping = {
        'add_credits': 'Ajout de crédits',
        'buy_credits': 'Achat de crédits',
        'purchase_credits': 'Achat de crédits',
        'credit_purchase': 'Achat de crédits',
        'unlock_video': 'Déblocage vidéo',
        'follow_club': 'Suivi de club',
        'unfollow_club': 'Arrêt suivi club',
        'update_profile': 'Mise à jour profil',
        'create_user': 'Création utilisateur',
        'update_user': 'Modification utilisateur',
        'delete_user': 'Suppression utilisateur',
        'create_club': 'Création club',
        'update_club': 'Modification club',
        'delete_club': 'Suppression club',
        'create_court': 'Création terrain',
        'update_court': 'Modification terrain',
        'delete_court': 'Suppression terrain',
        'video_upload': 'Upload vidéo',
        'video_delete': 'Suppression vidéo',
        'login': 'Connexion',
        'logout': 'Déconnexion',
        'registration': 'Inscription',
        'password_change': 'Changement mot de passe',
        'payment_simulation': 'Simulation de paiement',
        'payment_konnect': 'Paiement Konnect',
        'payment_flouci': 'Paiement Flouci',
        'payment_card': 'Paiement carte bancaire',
        'unknown_action': 'Action inconnue'
    }
    
    if not action_type or action_type.strip() == '':
        return 'Action non spécifiée'
    
    # Nettoyer le type d'action
    clean_action = str(action_type).strip().lower()
    
    # Retourner la traduction ou le type original si non trouvé
    return action_mapping.get(clean_action, f'Action: {action_type}')

def parse_action_details(action_details_str):
    """Parse et nettoie les détails d'action"""
    if not action_details_str:
        return {}
    
    try:
        if isinstance(action_details_str, str):
            return json.loads(action_details_str)
        elif isinstance(action_details_str, dict):
            return action_details_str
        else:
            return {"raw_details": str(action_details_str)}
    except json.JSONDecodeError:
        return {"raw_details": str(action_details_str)}
    except Exception:
        return {}

@admin_bp.route("/clubs/history/all", methods=["GET"])
def get_all_clubs_history():
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    try:
        # Créer des alias pour joindre la table User deux fois
        Player = aliased(User, name='player')
        Performer = aliased(User, name='performer')

        # Requête unique avec des jointures externes (outerjoin) pour plus de robustesse
        history_query = (
            db.session.query(
                ClubActionHistory,
                Player.name.label('player_name'),
                Club.name.label('club_name'),
                Performer.name.label('performed_by_name')
            )
            .outerjoin(Player, ClubActionHistory.user_id == Player.id)
            .outerjoin(Performer, ClubActionHistory.performed_by_id == Performer.id)
            .outerjoin(Club, ClubActionHistory.club_id == Club.id)
            .order_by(ClubActionHistory.performed_at.desc())
            .limit(100)  # Limiter à 100 entrées pour les performances
            .all()
        )

        history_data = []
        for entry, player_name, club_name, performed_by_name in history_query:
            # Normaliser le type d'action
            normalized_action = normalize_action_type(entry.action_type)
            
            # Parser les détails d'action
            parsed_details = parse_action_details(entry.action_details)
            
            # Créer un résumé lisible de l'action
            action_summary = create_action_summary(normalized_action, parsed_details)
            
            history_data.append({
                "id": entry.id,
                "user_id": entry.user_id,
                "club_id": entry.club_id,
                "player_name": player_name or "Utilisateur supprimé",
                "club_name": club_name or "Club non spécifié",
                "action_type": normalized_action,
                "action_type_raw": entry.action_type,  # Garder l'original pour debug
                "action_details": entry.action_details,
                "action_summary": action_summary,
                "parsed_details": parsed_details,
                "performed_at": entry.performed_at.isoformat() if entry.performed_at else datetime.utcnow().isoformat(),
                "performed_by_id": entry.performed_by_id,
                "performed_by_name": performed_by_name or "Auteur inconnu"
            })
            
        return jsonify({
            "history": history_data,
            "total_count": len(history_data),
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'historique global: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

def create_action_summary(action_type, details):
    """Crée un résumé lisible de l'action"""
    try:
        if 'crédits' in action_type.lower():
            if 'achat' in action_type.lower():
                # Pour les achats de crédits
                credits = details.get('credits_purchased') or details.get('credits_amount') or details.get('credits_involved', 'N/A')
                price = details.get('price_dt') or details.get('price_paid_dt')
                payment_method = details.get('payment_method', '')
                
                if price and payment_method:
                    return f"{action_type} - {credits} crédit(s) pour {price} DT via {payment_method}"
                elif price:
                    return f"{action_type} - {credits} crédit(s) pour {price} DT"
                else:
                    return f"{action_type} - {credits} crédit(s)"
            else:
                # Pour les ajouts de crédits (par admin)
                credits = details.get('credits_added') or details.get('credits_purchased') or details.get('credits_involved', 'N/A')
                return f"{action_type} - {credits} crédit(s)"
        elif 'suivi' in action_type.lower():
            club_name = details.get('club_name', 'Club inconnu')
            return f"{action_type} - {club_name}"
        elif 'vidéo' in action_type.lower():
            video_title = details.get('video_title') or details.get('title', 'Vidéo sans titre')
            return f"{action_type} - {video_title}"
        elif 'profil' in action_type.lower():
            fields = details.get('updated_fields', [])
            if fields:
                return f"{action_type} - Champs: {', '.join(fields)}"
            return action_type
        elif 'paiement' in action_type.lower():
            amount = details.get('amount') or details.get('price_dt') or details.get('total')
            method = details.get('method') or details.get('payment_method', '')
            if amount and method:
                return f"{action_type} - {amount} DT via {method}"
            elif amount:
                return f"{action_type} - {amount} DT"
            else:
                return action_type
        else:
            # Pour les autres actions, essayer d'extraire des informations utiles
            if details:
                key_info = []
                for key in ['name', 'email', 'amount', 'status', 'player_name', 'club_name']:
                    if key in details and details[key]:
                        key_info.append(f"{key}: {details[key]}")
                if key_info:
                    return f"{action_type} - {', '.join(key_info[:2])}"  # Limiter à 2 infos
            return action_type
    except Exception:
        return action_type

# --- ROUTES DE STATISTIQUES AVANCÉES ---

@admin_bp.route("/dashboard", methods=["GET"])
def get_admin_dashboard():
    """Dashboard complet pour l'administrateur avec toutes les statistiques"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        logger.info("Récupération du tableau de bord administrateur")
        
        # 1. Statistiques générales des utilisateurs
        total_users = User.query.count()
        total_players = User.query.filter_by(role=UserRole.PLAYER).count()
        total_clubs = User.query.filter_by(role=UserRole.CLUB).count()
        total_admins = User.query.filter_by(role=UserRole.SUPER_ADMIN).count()
        
        logger.info(f"Utilisateurs: {total_users} (Joueurs: {total_players}, Clubs: {total_clubs}, Admins: {total_admins})")
        
        # 2. Statistiques des clubs
        clubs_count = Club.query.count()
        total_courts = Court.query.count()
        total_videos = Video.query.count()
        
        # 3. Statistiques des crédits
        total_credits_in_system = db.session.query(db.func.sum(User.credits_balance)).scalar() or 0
        
        # 4. Dernières activités
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        recent_clubs = Club.query.order_by(Club.created_at.desc()).limit(5).all()
        recent_videos = Video.query.order_by(Video.recorded_at.desc()).limit(10).all()
        
        # 5. Statistiques par club
        clubs_stats = []
        for club in Club.query.all():
            club_players = User.query.filter_by(club_id=club.id, role=UserRole.PLAYER).count()
            club_courts = Court.query.filter_by(club_id=club.id).count()
            club_videos = db.session.query(Video).join(Court).filter(Court.club_id == club.id).count()
            club_followers = len(club.followers.all()) if hasattr(club, 'followers') else 0
            
            clubs_stats.append({
                'club': club.to_dict(),
                'players_count': club_players,
                'courts_count': club_courts,
                'videos_count': club_videos,
                'followers_count': club_followers
            })
        
        # 6. Activité récente par type
        activity_stats = {}
        recent_history = ClubActionHistory.query.order_by(ClubActionHistory.performed_at.desc()).limit(50).all()
        for entry in recent_history:
            action_type = entry.action_type
            activity_stats[action_type] = activity_stats.get(action_type, 0) + 1
        
        dashboard_data = {
            'overview': {
                'total_users': total_users,
                'total_players': total_players,
                'total_clubs_users': total_clubs,
                'total_admins': total_admins,
                'total_clubs': clubs_count,
                'total_courts': total_courts,
                'total_videos': total_videos,
                'total_credits_in_system': total_credits_in_system
            },
            'recent_activity': {
                'users': [user.to_dict() for user in recent_users],
                'clubs': [club.to_dict() for club in recent_clubs],
                'videos': [video.to_dict() for video in recent_videos],
                'activity_breakdown': activity_stats
            },
            'clubs_statistics': clubs_stats,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(dashboard_data), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du dashboard admin: {e}")
        return jsonify({"error": "Erreur lors de la récupération du dashboard"}), 500

@admin_bp.route("/statistics/users", methods=["GET"])
def get_users_statistics():
    """Statistiques détaillées sur les utilisateurs"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Statistiques par rôle
        users_by_role = {}
        for role in UserRole:
            count = User.query.filter_by(role=role).count()
            users_by_role[role.value] = count
        
        # Utilisateurs par club
        users_by_club = []
        for club in Club.query.all():
            club_users = User.query.filter_by(club_id=club.id).count()
            users_by_club.append({
                'club_name': club.name,
                'club_id': club.id,
                'users_count': club_users
            })
        
        # Répartition des crédits
        credits_stats = {
            'total_credits': db.session.query(db.func.sum(User.credits_balance)).scalar() or 0,
            'average_credits': db.session.query(db.func.avg(User.credits_balance)).scalar() or 0,
            'users_with_credits': User.query.filter(User.credits_balance > 0).count(),
            'users_without_credits': User.query.filter(User.credits_balance == 0).count()
        }
        
        # Utilisateurs récents (dernière semaine)
        week_ago = datetime.utcnow() - timedelta(days=7)
        new_users_this_week = User.query.filter(User.created_at >= week_ago).count()
        
        return jsonify({
            'users_by_role': users_by_role,
            'users_by_club': users_by_club,
            'credits_statistics': credits_stats,
            'new_users_this_week': new_users_this_week,
            'total_users': User.query.count()
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques utilisateurs: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

@admin_bp.route("/statistics/clubs", methods=["GET"])
def get_clubs_statistics():
    """Statistiques détaillées sur les clubs"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        clubs_detailed_stats = []
        
        for club in Club.query.all():
            # Compter les éléments associés
            players_count = User.query.filter_by(club_id=club.id, role=UserRole.PLAYER).count()
            courts_count = Court.query.filter_by(club_id=club.id).count()
            
            # Compter les vidéos
            videos_count = db.session.query(Video).join(Court).filter(Court.club_id == club.id).count()
            
            # Compter les followers
            followers_count = 0
            try:
                followers_count = len(club.followers.all())
            except:
                followers_count = 0
            
            # Calculer les crédits distribués
            credits_distributed = 0
            try:
                credit_entries = ClubActionHistory.query.filter_by(
                    club_id=club.id,
                    action_type='add_credits'
                ).all()
                
                for entry in credit_entries:
                    try:
                        if entry.action_details:
                            details = json.loads(entry.action_details)
                            credits_added = details.get('credits_added', 0)
                            if isinstance(credits_added, (int, float)):
                                credits_distributed += int(credits_added)
                    except:
                        pass
            except:
                credits_distributed = 0
            
            # Activité récente du club
            recent_activity_count = ClubActionHistory.query.filter_by(club_id=club.id).filter(
                ClubActionHistory.performed_at >= datetime.utcnow() - timedelta(days=30)
            ).count()
            
            clubs_detailed_stats.append({
                'club': club.to_dict(),
                'statistics': {
                    'players_count': players_count,
                    'courts_count': courts_count,
                    'videos_count': videos_count,
                    'followers_count': followers_count,
                    'credits_distributed': credits_distributed,
                    'recent_activity_count': recent_activity_count
                }
            })
        
        # Statistiques globales
        total_clubs = len(clubs_detailed_stats)
        active_clubs = len([c for c in clubs_detailed_stats if c['statistics']['recent_activity_count'] > 0])
        
        return jsonify({
            'clubs_detailed_statistics': clubs_detailed_stats,
            'global_statistics': {
                'total_clubs': total_clubs,
                'active_clubs_last_30_days': active_clubs,
                'average_players_per_club': sum(c['statistics']['players_count'] for c in clubs_detailed_stats) / total_clubs if total_clubs > 0 else 0,
                'average_courts_per_club': sum(c['statistics']['courts_count'] for c in clubs_detailed_stats) / total_clubs if total_clubs > 0 else 0
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques clubs: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

@admin_bp.route("/clubs/history/cleanup", methods=["POST"])
def cleanup_history_actions():
    """Nettoie et corrige les actions incorrectes dans l'historique"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        logger.info("Début du nettoyage de l'historique des actions")
        
        # Récupérer toutes les entrées d'historique
        all_entries = ClubActionHistory.query.all()
        
        corrections_made = 0
        invalid_entries_found = 0
        
        for entry in all_entries:
            original_action_type = entry.action_type
            needs_update = False
            
            # Nettoyer les types d'actions invalides ou malformés
            if not entry.action_type or entry.action_type.strip() == '':
                entry.action_type = 'unknown_action'
                needs_update = True
                invalid_entries_found += 1
            elif entry.action_type.strip() != entry.action_type:
                entry.action_type = entry.action_type.strip()
                needs_update = True
            
            # Corriger les types d'actions malformés courants
            action_corrections = {
                'addcredits': 'add_credits',
                'add_credit': 'add_credits',
                'buycredits': 'buy_credits',
                'buy_credit': 'buy_credits',
                'purchasecredits': 'buy_credits',
                'purchase_credit': 'buy_credits',
                'creditpurchase': 'buy_credits',
                'credit_buy': 'buy_credits',
                'achatcredits': 'buy_credits',
                'achat_credits': 'buy_credits',
                'unlookvideo': 'unlock_video',
                'unlock_videos': 'unlock_video',
                'followclub': 'follow_club',
                'follow_clubs': 'follow_club',
                'unfollowclub': 'unfollow_club',
                'unfollow_clubs': 'unfollow_club',
                'updateprofile': 'update_profile',
                'update_profiles': 'update_profile',
                'createuser': 'create_user',
                'create_users': 'create_user',
                'updateuser': 'update_user',
                'update_users': 'update_user',
                'deleteuser': 'delete_user',
                'delete_users': 'delete_user',
                'paymentkonnect': 'payment_konnect',
                'payment_via_konnect': 'payment_konnect',
                'paymentflouci': 'payment_flouci',
                'payment_via_flouci': 'payment_flouci',
                'paymentcard': 'payment_card',
                'payment_via_card': 'payment_card',
                'carte_bancaire': 'payment_card'
            }
            
            clean_action = entry.action_type.lower().replace('-', '_').replace(' ', '_')
            if clean_action in action_corrections:
                entry.action_type = action_corrections[clean_action]
                needs_update = True
            
            # Vérifier et corriger les détails d'action
            if entry.action_details:
                try:
                    if isinstance(entry.action_details, str):
                        # Vérifier si c'est du JSON valide
                        json.loads(entry.action_details)
                except json.JSONDecodeError:
                    # Si ce n'est pas du JSON valide, l'envelopper
                    entry.action_details = json.dumps({"raw_details": entry.action_details})
                    needs_update = True
            
            # Vérifier les dates
            if not entry.performed_at:
                entry.performed_at = datetime.utcnow()
                needs_update = True
            
            if needs_update:
                corrections_made += 1
                logger.info(f"Correction de l'entrée {entry.id}: {original_action_type} -> {entry.action_type}")
        
        # Sauvegarder les changements
        db.session.commit()
        
        # Statistiques des types d'actions après nettoyage
        action_type_stats = {}
        for entry in ClubActionHistory.query.all():
            action_type = entry.action_type
            action_type_stats[action_type] = action_type_stats.get(action_type, 0) + 1
        
        return jsonify({
            "message": "Nettoyage de l'historique terminé avec succès",
            "corrections_made": corrections_made,
            "invalid_entries_found": invalid_entries_found,
            "total_entries": len(all_entries),
            "action_type_distribution": action_type_stats,
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du nettoyage de l'historique: {e}")
        return jsonify({"error": f"Erreur lors du nettoyage: {str(e)}"}), 500

@admin_bp.route("/clubs/history/statistics", methods=["GET"])
def get_history_statistics():
    """Statistiques détaillées sur l'historique des actions"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Statistiques par type d'action
        action_type_stats = {}
        all_entries = ClubActionHistory.query.all()
        
        for entry in all_entries:
            action_type = normalize_action_type(entry.action_type)
            action_type_stats[action_type] = action_type_stats.get(action_type, 0) + 1
        
        # Statistiques par mois
        monthly_stats = {}
        for entry in all_entries:
            if entry.performed_at:
                month_key = entry.performed_at.strftime("%Y-%m")
                monthly_stats[month_key] = monthly_stats.get(month_key, 0) + 1
        
        # Statistiques par club
        club_stats = {}
        for entry in all_entries:
            if entry.club_id:
                club = Club.query.get(entry.club_id)
                club_name = club.name if club else f"Club {entry.club_id}"
                club_stats[club_name] = club_stats.get(club_name, 0) + 1
        
        # Actions récentes (dernières 24h)
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_actions = ClubActionHistory.query.filter(
            ClubActionHistory.performed_at >= yesterday
        ).count()
        
        return jsonify({
            "action_type_statistics": action_type_stats,
            "monthly_statistics": monthly_stats,
            "club_statistics": club_stats,
            "recent_actions_24h": recent_actions,
            "total_actions": len(all_entries),
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques d'historique: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

# --- ROUTES DE DIAGNOSTIC ET DEBUG ---

@admin_bp.route("/debug/fix-unknown-actions", methods=["POST"])
def fix_unknown_actions():
    """Fix immediate des actions inconnues dans l'historique"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        logger.info("Début de la correction des actions inconnues")
        
        # Récupérer toutes les entrées avec des actions potentiellement problématiques
        all_entries = ClubActionHistory.query.all()
        
        fixed_count = 0
        entries_updated = []
        
        for entry in all_entries:
            original_action = entry.action_type
            
            # Identifier les actions qui apparaissent comme "inconnues"
            normalized = normalize_action_type(original_action)
            
            if (not original_action or 
                original_action.strip() == '' or 
                normalized.startswith('Action:') or 
                'inconnue' in normalized.lower()):
                
                # Essayer de deviner le type d'action à partir des détails
                suggested_action = suggest_action_from_details(entry.action_details)
                
                if suggested_action and suggested_action != original_action:
                    entry.action_type = suggested_action
                    fixed_count += 1
                    entries_updated.append({
                        'id': entry.id,
                        'original': original_action,
                        'fixed': suggested_action,
                        'normalized': normalize_action_type(suggested_action)
                    })
                elif not original_action or original_action.strip() == '':
                    entry.action_type = 'unknown_action'
                    fixed_count += 1
                    entries_updated.append({
                        'id': entry.id,
                        'original': original_action,
                        'fixed': 'unknown_action',
                        'normalized': 'Action inconnue'
                    })
        
        if fixed_count > 0:
            db.session.commit()
            logger.info(f"Correction terminée: {fixed_count} entrées mises à jour")
        
        return jsonify({
            'message': f'Correction terminée: {fixed_count} actions corrigées',
            'entries_fixed': fixed_count,
            'updates_made': entries_updated,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la correction des actions inconnues: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

def suggest_action_from_details(action_details_str):
    """Suggère un type d'action basé sur les détails"""
    if not action_details_str:
        return 'unknown_action'
    
    try:
        if isinstance(action_details_str, str):
            details = json.loads(action_details_str)
        else:
            details = action_details_str
        
        # Analyser les clés pour deviner l'action
        if any(key in details for key in ['credits_added', 'credits_purchased', 'credits_amount']):
            if 'purchased' in str(details) or 'payment_method' in details or 'price' in str(details):
                return 'buy_credits'
            else:
                return 'add_credits'
        elif any(key in details for key in ['video_title', 'video_id', 'unlock']):
            return 'unlock_video'
        elif any(key in details for key in ['club_name', 'follow']):
            if 'unfollow' in str(details).lower():
                return 'unfollow_club'
            else:
                return 'follow_club'
        elif any(key in details for key in ['player_name', 'user_name', 'name']):
            return 'update_user'
        else:
            return 'unknown_action'
            
    except Exception:
        return 'unknown_action'

@admin_bp.route("/debug/action-types", methods=["GET"])
def debug_action_types():
    """Debug: Afficher tous les types d'actions dans la base"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Récupérer tous les types d'actions uniques
        action_types = db.session.query(
            ClubActionHistory.action_type,
            db.func.count(ClubActionHistory.action_type).label('count')
        ).group_by(ClubActionHistory.action_type).all()
        
        # Analyser et normaliser
        action_analysis = []
        for action_type, count in action_types:
            normalized = normalize_action_type(action_type)
            action_analysis.append({
                'original': action_type,
                'normalized': normalized,
                'count': count,
                'needs_cleanup': normalized.startswith('Action:') or 'inconnue' in normalized.lower()
            })
        
        # Statistiques
        total_entries = ClubActionHistory.query.count()
        unknown_actions = [a for a in action_analysis if a['needs_cleanup']]
        
        return jsonify({
            'total_history_entries': total_entries,
            'unique_action_types': len(action_analysis),
            'unknown_actions_count': len(unknown_actions),
            'action_types_analysis': action_analysis,
            'unknown_actions': unknown_actions,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du debug des types d'actions: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

@admin_bp.route("/debug/system", methods=["GET"])
def debug_system():
    """Diagnostic complet du système"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Vérification des tables
        tables_status = {
            'User': db.engine.has_table('user'),
            'Club': db.engine.has_table('club'),
            'Court': db.engine.has_table('court'),
            'Video': db.engine.has_table('video'),
            'ClubActionHistory': db.engine.has_table('club_action_history'),
            'player_club_follows': db.engine.has_table('player_club_follows')
        }
        
        # Vérification de l'intégrité des données
        integrity_checks = {
            'users_with_invalid_club_id': User.query.filter(
                User.club_id.isnot(None),
                ~User.club_id.in_(db.session.query(Club.id))
            ).count(),
            'courts_with_invalid_club_id': Court.query.filter(
                ~Court.club_id.in_(db.session.query(Club.id))
            ).count(),
            'videos_with_invalid_user_id': Video.query.filter(
                ~Video.user_id.in_(db.session.query(User.id))
            ).count(),
            'videos_with_invalid_court_id': Video.query.filter(
                ~Video.court_id.in_(db.session.query(Court.id))
            ).count()
        }
        
        # Statistiques générales
        system_stats = {
            'database_tables': tables_status,
            'data_integrity': integrity_checks,
            'total_records': {
                'users': User.query.count(),
                'clubs': Club.query.count(),
                'courts': Court.query.count(),
                'videos': Video.query.count(),
                'history_entries': ClubActionHistory.query.count()
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(system_stats), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du diagnostic système: {e}")
        return jsonify({"error": f"Erreur lors du diagnostic: {str(e)}"}), 500

# --- ROUTES DE GESTION DES DONNÉES DE TEST ---

@admin_bp.route("/test-data/create-complete", methods=["POST"])
def create_complete_test_data():
    """Création de données de test complètes pour tout le système"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        logger.info("Début de la création de données de test complètes")
        
        # 1. Créer des clubs de test
        clubs_created = []
        test_clubs_data = [
            {'name': 'Club Padel Excellence', 'email': 'excellence@test.com', 'address': '123 Rue du Sport, Paris'},
            {'name': 'Tennis Club Premium', 'email': 'premium@test.com', 'address': '456 Avenue des Champions, Lyon'},
            {'name': 'Padel Center Pro', 'email': 'pro@test.com', 'address': '789 Boulevard du Tennis, Marseille'}
        ]
        
        for club_data in test_clubs_data:
            existing_club = Club.query.filter_by(email=club_data['email']).first()
            if not existing_club:
                new_club = Club(
                    name=club_data['name'],
                    email=club_data['email'],
                    address=club_data['address'],
                    phone_number=f"+33{random.randint(100000000, 999999999)}"
                )
                db.session.add(new_club)
                db.session.flush()
                
                # Créer l'utilisateur club associé
                club_user = User(
                    email=club_data['email'],
                    name=club_data['name'],
                    role=UserRole.CLUB,
                    club_id=new_club.id,
                    password_hash=generate_password_hash('password123')
                )
                db.session.add(club_user)
                clubs_created.append(new_club)
                logger.info(f"Club créé: {new_club.name}")
        
        db.session.flush()
        
        # 2. Créer des terrains pour chaque club
        courts_created = 0
        for club in clubs_created:
            for i in range(1, random.randint(2, 5)):  # 1-4 terrains par club
                court = Court(
                    club_id=club.id,
                    name=f"Terrain {i}",
                    qr_code=f"QR_{club.id}_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    camera_url=f"http://example.com/camera/{club.id}/{i}"
                )
                db.session.add(court)
                courts_created += 1
        
        db.session.flush()
        
        # 3. Créer des joueurs pour chaque club
        players_created = 0
        for club in clubs_created:
            for i in range(1, random.randint(5, 11)):  # 4-10 joueurs par club
                player_email = f"player{i}_club{club.id}@test.com"
                existing_player = User.query.filter_by(email=player_email).first()
                if not existing_player:
                    player = User(
                        email=player_email,
                        name=f"Joueur {i} - {club.name}",
                        password_hash=generate_password_hash('password123'),
                        role=UserRole.PLAYER,
                        club_id=club.id,
                        credits_balance=random.randint(5, 50)
                    )
                    db.session.add(player)
                    players_created += 1
        
        db.session.flush()
        
        # 4. Créer des followers externes
        followers_created = 0
        all_clubs = Club.query.all()
        for i in range(1, 11):  # 10 followers externes
            follower_email = f"external_follower{i}@test.com"
            existing_follower = User.query.filter_by(email=follower_email).first()
            if not existing_follower:
                follower = User(
                    email=follower_email,
                    name=f"Follower Externe {i}",
                    password_hash=generate_password_hash('password123'),
                    role=UserRole.PLAYER,
                    credits_balance=random.randint(1, 20)
                )
                db.session.add(follower)
                db.session.flush()
                
                # Faire suivre des clubs aléatoires
                clubs_to_follow = random.sample(all_clubs, random.randint(1, min(3, len(all_clubs))))
                for club in clubs_to_follow:
                    follower.followed_clubs.append(club)
                
                followers_created += 1
        
        # 5. Créer des vidéos
        videos_created = 0
        courts = Court.query.all()
        players = User.query.filter_by(role=UserRole.PLAYER).all()
        
        for court in courts:
            # Sélectionner des joueurs aléatoires pour ce terrain
            court_players = random.sample(players, min(random.randint(2, 6), len(players)))
            for player in court_players:
                for v in range(1, random.randint(2, 4)):  # 1-3 vidéos par joueur par terrain
                    video = Video(
                        title=f"Match {player.name} - {court.name} - Video {v}",
                        description=f"Enregistrement automatique du {datetime.now().strftime('%d/%m/%Y')}",
                        file_url=f"http://example.com/videos/{court.club_id}/{court.id}/{player.id}/{v}.mp4",
                        thumbnail_url=f"http://example.com/thumbs/{court.club_id}/{court.id}/{player.id}/{v}.jpg",
                        duration=random.randint(600, 7200),
                        is_unlocked=random.choice([True, False]),
                        credits_cost=random.randint(1, 5),
                        user_id=player.id,
                        court_id=court.id,
                        recorded_at=datetime.utcnow() - timedelta(days=random.randint(0, 30)),
                        created_at=datetime.utcnow()
                    )
                    db.session.add(video)
                    videos_created += 1
        
        # 6. Créer des entrées d'historique
        history_entries_created = 0
        club_users = User.query.filter_by(role=UserRole.CLUB).all()
        
        for club_user in club_users:
            club_players = User.query.filter_by(club_id=club_user.club_id, role=UserRole.PLAYER).all()
            for player in club_players:
                # Historique d'ajout de crédits
                for _ in range(random.randint(1, 4)):
                    credits_amount = random.randint(5, 25)
                    history_entry = ClubActionHistory(
                        user_id=player.id,
                        club_id=club_user.club_id,
                        performed_by_id=club_user.id,
                        action_type='add_credits',
                        action_details=json.dumps({
                            'credits_added': credits_amount,
                            'player_name': player.name,
                            'reason': 'Données de test'
                        }),
                        performed_at=datetime.utcnow() - timedelta(days=random.randint(1, 60))
                    )
                    db.session.add(history_entry)
                    history_entries_created += 1
                
                # Historique d'ajout de joueur
                history_entry = ClubActionHistory(
                    user_id=player.id,
                    club_id=club_user.club_id,
                    performed_by_id=club_user.id,
                    action_type='add_player',
                    action_details=json.dumps({
                        'player_name': player.name,
                        'player_email': player.email
                    }),
                    performed_at=datetime.utcnow() - timedelta(days=random.randint(1, 90))
                )
                db.session.add(history_entry)
                history_entries_created += 1
        
        # Commit final
        db.session.commit()
        
        logger.info(f"Données de test créées avec succès")
        
        return jsonify({
            'message': 'Données de test complètes créées avec succès',
            'created': {
                'clubs': len(clubs_created),
                'courts': courts_created,
                'players': players_created,
                'followers': followers_created,
                'videos': videos_created,
                'history_entries': history_entries_created
            },
            'verification': {
                'total_users': User.query.count(),
                'total_clubs': Club.query.count(),
                'total_courts': Court.query.count(),
                'total_videos': Video.query.count(),
                'total_history': ClubActionHistory.query.count()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la création des données de test: {e}")
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

@admin_bp.route("/test-data/cleanup", methods=["POST"])
def cleanup_test_data():
    """Nettoyer toutes les données de test"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Supprimer les données de test identifiables
        test_users_deleted = User.query.filter(User.email.like('%@test.com')).delete(synchronize_session=False)
        test_clubs_deleted = Club.query.filter(Club.email.like('%@test.com')).delete(synchronize_session=False)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Données de test supprimées avec succès',
            'deleted': {
                'users': test_users_deleted,
                'clubs': test_clubs_deleted
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du nettoyage des données de test: {e}")
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

# --- ROUTES DE MAINTENANCE ---

@admin_bp.route("/maintenance/database-check", methods=["GET"])
def database_maintenance_check():
    """Vérification de maintenance de la base de données"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        maintenance_report = {
            'orphaned_data': {
                'users_without_valid_club': User.query.filter(
                    User.club_id.isnot(None),
                    ~User.club_id.in_(db.session.query(Club.id))
                ).count(),
                'courts_without_valid_club': Court.query.filter(
                    ~Court.club_id.in_(db.session.query(Club.id))
                ).count(),
                'videos_without_valid_user': Video.query.filter(
                    ~Video.user_id.in_(db.session.query(User.id))
                ).count(),
                'videos_without_valid_court': Video.query.filter(
                    ~Video.court_id.in_(db.session.query(Court.id))
                ).count(),
                'history_without_valid_club': ClubActionHistory.query.filter(
                    ClubActionHistory.club_id.isnot(None),
                    ~ClubActionHistory.club_id.in_(db.session.query(Club.id))
                ).count()
            },
            'duplicate_checks': {
                'duplicate_emails': db.session.query(User.email, db.func.count(User.email)).group_by(User.email).having(db.func.count(User.email) > 1).count(),
                'duplicate_club_emails': db.session.query(Club.email, db.func.count(Club.email)).group_by(Club.email).having(db.func.count(Club.email) > 1).count()
            },
            'data_consistency': {
                'clubs_without_admin_user': Club.query.filter(
                    ~Club.id.in_(db.session.query(User.club_id).filter(User.role == UserRole.CLUB))
                ).count(),
                'users_with_negative_credits': User.query.filter(User.credits_balance < 0).count()
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(maintenance_report), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification de maintenance: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

# --- ROUTES DE BULK OPERATIONS ---

@admin_bp.route("/bulk/update-credits", methods=["POST"])
def bulk_update_credits():
    """Mise à jour en masse des crédits utilisateurs"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    data = request.get_json()
    operation = data.get('operation')  # 'add', 'set', 'multiply'
    amount = data.get('amount', 0)
    user_ids = data.get('user_ids', [])
    
    if operation not in ['add', 'set', 'multiply']:
        return jsonify({"error": "Opération non valide"}), 400
    
    try:
        users_updated = 0
        
        if user_ids:
            users = User.query.filter(User.id.in_(user_ids)).all()
        else:
            users = User.query.filter_by(role=UserRole.PLAYER).all()
        
        for user in users:
            old_balance = user.credits_balance
            
            if operation == 'add':
                user.credits_balance += amount
            elif operation == 'set':
                user.credits_balance = amount
            elif operation == 'multiply':
                user.credits_balance = int(user.credits_balance * amount)
            
            # Log the action
            log_club_action(
                user_id=user.id,
                club_id=user.club_id,
                action_type='bulk_update_credits',
                details={
                    'operation': operation,
                    'amount': amount,
                    'old_balance': old_balance,
                    'new_balance': user.credits_balance
                },
                performed_by_id=session.get('user_id')
            )
            
            users_updated += 1
        
        db.session.commit()
        
        return jsonify({
            'message': f'{len(users)} utilisateurs mis à jour',
            'operation': operation,
            'amount': amount,
            'users_updated': len(users)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la mise à jour en lot: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

# --- ROUTE DE DEBUG POUR TESTER L'AUTHENTIFICATION ADMIN ---

@admin_bp.route("/debug/auth", methods=["GET"])
def debug_admin_auth():
    """Route de debug pour tester l'authentification admin"""
    
    debug_info = {
        "session_data": dict(session),
        "user_id": session.get("user_id"),
        "user_role": session.get("user_role"),
        "user_email": session.get("user_email"),
        "user_name": session.get("user_name"),
        "expected_admin_role": UserRole.SUPER_ADMIN.value,
        "is_admin": require_super_admin(),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    logger.info(f"🔍 Debug auth admin: {debug_info}")
    
    return jsonify({
        "message": "Debug authentification admin",
        "debug": debug_info
    }), 200

@admin_bp.route("/test/simple", methods=["GET"])
def test_simple_admin():
    """Route de test simple pour admin (sans vérification stricte)"""
    
    user_role = session.get("user_role")
    
    # Test avec différents formats de rôle admin
    is_admin = (
        user_role == "SUPER_ADMIN" or
        user_role == "super_admin" or
        user_role == "ADMIN" or
        user_role == "admin" or
        (user_role and "admin" in user_role.lower())
    )
    
    return jsonify({
        "message": "Test admin simple",
        "user_role": user_role,
        "is_admin": is_admin,
        "session_user_id": session.get("user_id"),
        "session_user_name": session.get("user_name")
    }), 200


# --- ROUTES DE CONFIGURATION SYSTÈME ---

@admin_bp.route("/config", methods=["GET"])
def get_system_config():
    """Récupère toutes les configurations système"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        configs = SystemConfiguration.query.all()
        
        # Grouper par type
        configs_by_type = {}
        for config in configs:
            config_type = config.config_type.value
            if config_type not in configs_by_type:
                configs_by_type[config_type] = []
            
            configs_by_type[config_type].append(
                config.to_dict(include_value=True, decrypt=False, mask_sensitive=True)
            )
        
        return jsonify({
            "configs": configs_by_type,
            "total": len(configs)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur récupération config: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/bunny-cdn", methods=["GET"])
def get_bunny_cdn_config():
    """Récupère la configuration Bunny CDN"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        config = SystemConfiguration.get_bunny_cdn_config()
        
        # Masquer l'API key
        if config.get('api_key'):
            config['api_key_masked'] = '********'
            config.pop('api_key')
        
        return jsonify(config), 200
        
    except Exception as e:
        logger.error(f"Erreur récupération Bunny config: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/bunny-cdn", methods=["PUT"])
def update_bunny_cdn_config():
    """Met à jour la configuration Bunny CDN"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        user_id = session.get("user_id")
        
        api_key = data.get('api_key')
        library_id = data.get('library_id')
        cdn_hostname = data.get('cdn_hostname')
        storage_zone = data.get('storage_zone')
        
        if not all([api_key, library_id, cdn_hostname]):
            return jsonify({"error": "Tous les champs obligatoires doivent être remplis"}), 400
        
        SystemConfiguration.set_bunny_cdn_config(
            api_key=api_key,
            library_id=library_id,
            cdn_hostname=cdn_hostname,
            storage_zone=storage_zone,
            updated_by=user_id
        )
        
        logger.info(f"Configuration Bunny CDN mise à jour par utilisateur {user_id}")
        
        return jsonify({
            "message": "Configuration Bunny CDN mise à jour avec succès",
            "config": {
                "library_id": library_id,
                "cdn_hostname": cdn_hostname,
                "storage_zone": storage_zone
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur mise à jour Bunny config: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/config/test-bunny", methods=["POST"])
def test_bunny_connection():
    """Test la connexion Bunny CDN"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        import requests
        data = request.get_json()
        api_key = data.get('api_key')
        library_id = data.get('library_id')
        
        if not api_key or not library_id:
            return jsonify({"error": "API Key et Library ID requis"}), 400
        
        test_url = f"https://video.bunnycdn.com/library/{library_id}/videos"
        headers = {"AccessKey": api_key, "Accept": "application/json"}
        
        response = requests.get(test_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return jsonify({"success": True, "message": "Connexion Bunny CDN réussie"}), 200
        elif response.status_code == 401:
            return jsonify({"success": False, "message": "Authentification échouée"}), 401
        else:
            return jsonify({"success": False, "message": f"Erreur: {response.status_code}"}), 400
            
    except Exception as e:
        logger.error(f"Erreur test Bunny: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# --- ROUTES DE VISUALISATION DES LOGS ---

@admin_bp.route("/logs", methods=["GET"])
def get_system_logs():
    """Récupère les logs système"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        lines = min(request.args.get('lines', 100, type=int), 1000)
        log_level = request.args.get('level', 'all')
        
        log_file_path = None
        for path in ['logs/system_20251207.log', 'logs/system_*.log', 'app.log', 'logs/app.log', '../app.log', 'padelvar.log']:
            if os.path.exists(path):
                log_file_path = path
                break
            # Try glob pattern for dated logs
            if '*' in path:
                import glob
                matching_files = glob.glob(path)
                if matching_files:
                    # Get the most recent file
                    log_file_path = max(matching_files, key=os.path.getmtime)
                    break
        
        if not log_file_path:
            return jsonify({"logs": [], "message": "Fichier de log introuvable"}), 200
        
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        
        recent_lines = all_lines[-lines:]
        
        if log_level != 'all':
            recent_lines = [line for line in recent_lines if log_level.upper() in line]
        
        parsed_logs = []
        for line in recent_lines:
            level = 'INFO'
            if 'ERROR' in line:
                level = 'ERROR'
            elif 'WARNING' in line:
                level = 'WARNING'
            elif 'DEBUG' in line:
                level = 'DEBUG'
            
            parsed_logs.append({
                'raw': line.strip(),
                'level': level,
                'message': line.strip()
            })
        
        return jsonify({
            "logs": parsed_logs,
            "total_lines": len(parsed_logs),
            "log_file": log_file_path
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lecture logs: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/logs/download", methods=["GET"])
def download_logs():
    """Télécharge le fichier de log"""
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        from flask import send_file
        
        for path in ['logs/system_*.log', 'app.log', 'logs/app.log', '../app.log']:
            if '*' in path:
                import glob
                matching_files = glob.glob(path)
                if matching_files:
                    path = max(matching_files, key=os.path.getmtime)
            if os.path.exists(path):
                return send_file(
                    path,
                    as_attachment=True,
                    download_name=f'padelvar_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
                    mimetype='text/plain'
                )
        
        return jsonify({"error": "Fichier de log introuvable"}), 404
        
    except Exception as e:
        logger.error(f"Erreur téléchargement logs: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================
# GESTION DES PACKAGES DE CRÉDITS (CRUD)
# ============================================

@admin_bp.route('/credit-packages', methods=['GET'])
def get_credit_packages():
    """Récupérer la liste des packages de crédits"""
    if not require_super_admin():
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        from src.models.credit_package import CreditPackage
        
        package_type = request.args.get('type')  # 'player' ou 'club'
        
        query = CreditPackage.query
        if package_type:
            query = query.filter_by(package_type=package_type)
        
        packages = query.order_by(CreditPackage.credits.asc()).all()
        
        return jsonify({
            'packages': [pkg.to_dict() for pkg in packages]
        }), 200
        
    except Exception as e:
        logger.error(f'Erreur lors de la récupération des packages: {e}')
        return jsonify({'error': 'Erreur serveur'}), 500


@admin_bp.route('/credit-packages', methods=['POST'])
def create_credit_package():
    """Créer un nouveau package de crédits"""
    if not require_super_admin():
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        from src.models.credit_package import CreditPackage
        
        data = request.get_json()
        
        # Validation
        if not all(k in data for k in ['credits', 'price_dt', 'package_type']):
            return jsonify({'error': 'Champs manquants'}), 400
        
        if data['credits'] <= 0 or data['price_dt'] <= 0:
            return jsonify({'error': 'Les crédits et le prix doivent être positifs'}), 400
        
        if data['package_type'] not in ['player', 'club']:
            return jsonify({'error': 'Type de package invalide'}), 400
        
        # Générer un ID unique        
        pkg_id = data.get('id') or f"pack_custom_{uuid.uuid4().hex[:8]}"
        
        # Vérifier si l'ID existe déjà
        existing = CreditPackage.query.get(pkg_id)
        if existing:
            return jsonify({'error': 'Un package avec cet ID existe déjà'}), 400
        
        # Créer le package
        new_package = CreditPackage(
            id=pkg_id,
            credits=data['credits'],
            price_dt=data['price_dt'],
            package_type=data['package_type'],
            description=data.get('description', ''),
            is_popular=data.get('is_popular', False),
            is_active=data.get('is_active', True)
        )
        
        db.session.add(new_package)
        db.session.commit()
        
        logger.info(f'Package créé: {pkg_id}')
        return jsonify({
            'message': 'Package créé avec succès',
            'package': new_package.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f'Erreur lors de la création du package: {e}')
        db.session.rollback()
        return jsonify({'error': 'Erreur serveur'}), 500


@admin_bp.route('/credit-packages/<string:package_id>', methods=['PUT'])
def update_credit_package(package_id):
    """Mettre à jour un package de crédits"""
    if not require_super_admin():
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        from src.models.credit_package import CreditPackage
        
        package = CreditPackage.query.get(package_id)
        if not package:
            return jsonify({'error': 'Package non trouvé'}), 404
        
        data = request.get_json()
        
        # Mise à jour des champs
        if 'credits' in data:
            if data['credits'] <= 0:
                return jsonify({'error': 'Les crédits doivent être positifs'}), 400
            package.credits = data['credits']
        
        if 'price_dt' in data:
            if data['price_dt'] <= 0:
                return jsonify({'error': 'Le prix doit être positif'}), 400
            package.price_dt = data['price_dt']
        
        if 'description' in data:
            package.description = data['description']
        
        if 'is_popular' in data:
            package.is_popular = data['is_popular']
        
        if 'is_active' in data:
            package.is_active = data['is_active']
        
        package.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f'Package mis à jour: {package_id}')
        return jsonify({
            'message': 'Package mis à jour avec succès',
            'package': package.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f'Erreur lors de la mise à jour du package: {e}')
        db.session.rollback()
        return jsonify({'error': 'Erreur serveur'}), 500


@admin_bp.route('/credit-packages/<string:package_id>', methods=['DELETE'])
def delete_credit_package(package_id):
    """Supprimer un package de crédits (si jamais acheté)"""
    if not require_super_admin():
        return jsonify({'error': 'Accès non autorisé'}), 403
    
    try:
        from src.models.credit_package import CreditPackage
        
        package = CreditPackage.query.get(package_id)
        if not package:
            return jsonify({'error': 'Package non trouvé'}), 404
        
        # Vérifier si le package a été acheté
        # TODO: Ajouter une vérification dans l'historique d'achats
        # Pour l'instant, on permet la suppression
        
        db.session.delete(package)
        db.session.commit()
        
        logger.info(f'Package supprimé: {package_id}')
        return jsonify({
            'message': 'Package supprimé avec succès'
        }), 200
        
    except Exception as e:
        logger.error(f'Erreur lors de la suppression du package: {e}')
        db.session.rollback()
        return jsonify({'error': 'Erreur serveur'}), 500
        return jsonify({"error": f"Erreur lors de la suppression: {str(e)}"}), 500


# --- UTILITAIRES UPLOAD ---

@admin_bp.route("/uploads/image", methods=["POST"])
def upload_image():
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nom de fichier vide"}), 400
        
    if file:
        try:
            # Sécuriser le nom de fichier
            from werkzeug.utils import secure_filename
            import os
            
            filename = secure_filename(file.filename)
            # Ajouter un UUID pour éviter les collisions
            unique_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
            
            # Chemin de sauvegarde (assumant src/static/overlays existe)
            upload_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'overlays')
            os.makedirs(upload_folder, exist_ok=True)
            
            file_path = os.path.join(upload_folder, unique_filename)
            file.save(file_path)
            
            # Retourner l'URL relative
            url = f"/static/overlays/{unique_filename}"
            return jsonify({"url": url}), 201
            
        except Exception as e:
            return jsonify({"error": f"Erreur upload: {str(e)}"}), 500

# --- GESTION DES OVERLAYS (SUPER ADMIN) ---

@admin_bp.route("/clubs/<int:club_id>/overlays", methods=["GET"])
def get_club_overlays(club_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    club = Club.query.get_or_404(club_id)
    return jsonify({"overlays": [overlay.to_dict() for overlay in club.overlays]}), 200

@admin_bp.route("/clubs/<int:club_id>/overlays", methods=["POST"])
def create_club_overlay(club_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    club = Club.query.get_or_404(club_id)
    data = request.get_json()
    
    try:
        new_overlay = ClubOverlay(
            club_id=club.id,
            name=data.get("name", "Overlay"),
            image_url=data["image_url"],
            position_x=float(data.get("position_x", 5)),
            position_y=float(data.get("position_y", 5)),
            width=float(data.get("width", 10)),
            opacity=float(data.get("opacity", 1.0)),
            is_active=data.get("is_active", True)
        )
        db.session.add(new_overlay)
        db.session.commit()
        return jsonify({"message": "Overlay créé", "overlay": new_overlay.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Erreur lors de la création de l'overlay: {str(e)}"}), 500

@admin_bp.route("/clubs/<int:club_id>/overlays/<int:overlay_id>", methods=["PUT"])
def update_club_overlay(club_id, overlay_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    overlay = ClubOverlay.query.get_or_404(overlay_id)
    if overlay.club_id != club_id:
        return jsonify({"error": "Overlay n'appartient pas à ce club"}), 400
        
    data = request.get_json()
    try:
        if "name" in data: overlay.name = data["name"]
        if "image_url" in data: overlay.image_url = data["image_url"]
        if "position_x" in data: overlay.position_x = float(data["position_x"])
        if "position_y" in data: overlay.position_y = float(data["position_y"])
        if "width" in data: overlay.width = float(data["width"])
        if "opacity" in data: overlay.opacity = float(data["opacity"])
        if "is_active" in data: overlay.is_active = data["is_active"]
        
        db.session.commit()
        return jsonify({"message": "Overlay mis à jour", "overlay": overlay.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Erreur lors de la mise à jour: {str(e)}"}), 500

@admin_bp.route("/clubs/<int:club_id>/overlays/<int:overlay_id>", methods=["DELETE"])
def delete_club_overlay(club_id, overlay_id):
    if not require_super_admin(): return jsonify({"error": "Accès non autorisé"}), 403
    overlay = ClubOverlay.query.get_or_404(overlay_id)
    if overlay.club_id != club_id:
        return jsonify({"error": "Overlay n'appartient pas à ce club"}), 400
        
    try:
        db.session.delete(overlay)
        db.session.commit()
        return jsonify({"message": "Overlay supprimé"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Erreur lors de la suppression"}), 500


# --- VIDEO DELETION (SUPER ADMIN ONLY) ---

@admin_bp.route("/videos/<int:video_id>", methods=["DELETE"])
def delete_video(video_id):
    """
    Soft delete d'une vidéo avec choix de localisation de suppression.
    Super admin uniquement.
    
    La vidéo reste dans la base de données avec deleted_at timestamp pour préserver les statistiques.
    
    Body JSON:
    {
        "mode": "local_only" |"cloud_only" | "local_and_cloud" | "database"
    }
    
    Modes:
    - local_only: Supprime fichier local uniquement (libère espace serveur)
    - cloud_only: Supprime du cloud uniquement (expire la vidéo, garde stats)
    - local_and_cloud: Supprime les deux (nettoyage complet, garde stats)
    - database: Hard delete (supprime tout, stats perdues)
    """
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    video = Video.query.get_or_404(video_id)
    data = request.get_json() or {}
    mode = data.get("mode", "local_and_cloud").lower()
    
    # Valider le mode
    valid_modes = ["local_only", "cloud_only", "local_and_cloud", "database"]
    if mode not in valid_modes:
        return jsonify({
            "error": f"Mode invalide. Options: {', '.join(valid_modes)}"
        }), 400
    
    import os
    from datetime import datetime
    
    try:
        logger.info(f"🗑️ Suppression vidéo {video_id} ({video.title}) - Mode: {mode}")
        
        # MODE 1: Supprimer fichier LOCAL seulement
        if mode == "local_only":
            # Construire les chemins possibles pour le fichier
            file_paths_to_check = []
            
            # Obtenir le club_id (les fichiers sont organisés par club, pas par court!)
            club_id = video.court.club_id if video.court else None
            
            logger.info(f"🔍 DEBUG - Données vidéo:")
            logger.info(f"   video.id: {video.id}")
            logger.info(f"   video.title: {video.title}")
            logger.info(f"   video.court_id: {video.court_id}")
            logger.info(f"   club_id (via court): {club_id}")
            logger.info(f"   video.local_file_path: {video.local_file_path}")
            
            # 1. Utiliser local_file_path si disponible
            if video.local_file_path:
                file_paths_to_check.append(video.local_file_path)
                logger.info(f"   ✓ Ajouté local_file_path: {video.local_file_path}")
            
            # 2. Essayer de reconstruire le chemin
            # Note: recording_session_id peut ne pas exister dans les anciennes versions du schéma
            if club_id:
                # Essayer d'obtenir recording_session_id si le champ existe
                recording_session_id = getattr(video, 'recording_session_id', None)
                logger.info(f"   recording_session_id: {recording_session_id}")
                
                if recording_session_id:
                    # Format: static/videos/{club_id}/{recording_session_id}.mp4
                    filename = f"{recording_session_id}.mp4"
                    reconstructed_path = os.path.join("static", "videos", str(club_id), filename)
                    file_paths_to_check.append(reconstructed_path)
                    file_paths_to_check.append(os.path.abspath(reconstructed_path))
                    logger.info(f"   ✓ Ajouté avec recording_session_id: {reconstructed_path}")
                
                # Fallback: Essayer avec le titre si disponible
                if video.title:
                    filename = f"{video.title}.mp4"
                    reconstructed_path = os.path.join("static", "videos", str(club_id), filename)
                    file_paths_to_check.append(reconstructed_path)
                    file_paths_to_check.append(os.path.abspath(reconstructed_path))
                    logger.info(f"   ✓ Ajouté avec titre: {reconstructed_path}")
            
            logger.info(f"🔍 Chemins à vérifier ({len(file_paths_to_check)}):")
            for idx, path in enumerate(file_paths_to_check, 1):
                exists = os.path.exists(path) if path else False
                logger.info(f"   [{idx}] {'✅ EXISTE' if exists else '❌ N/A'}: {path}")
            
            # Essayer de supprimer tous les fichiers trouvés
            deleted_files = []
            errors = []
            
            for file_path in file_paths_to_check:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        deleted_files.append(file_path)
                        logger.info(f"✅ Fichier local supprimé: {file_path}")
                    except Exception as e:
                        errors.append(f"{file_path}: {str(e)}")
                        logger.error(f"❌ Erreur suppression {file_path}: {e}")
            
            # Marquer en base si au moins un fichier supprimé
            if deleted_files:
                video.local_file_deleted_at = datetime.utcnow()
                db.session.commit()
                return jsonify({
                    "message": f"Fichier(s) local(aux) supprimé(s): {len(deleted_files)}",
                    "mode": "local_only",
                    "video_id": video_id,
                    "deleted_files": deleted_files,
                    "errors": errors if errors else None
                }), 200
            elif errors:
                return jsonify({
                    "error": "Erreurs lors de la suppression",
                    "video_id": video_id,
                    "errors": errors
                }), 500
            else:
                logger.warning(f"⚠️ Aucun fichier local trouvé pour vidéo {video_id}")
                return jsonify({
                    "message": "Aucun fichier local trouvé à supprimer",
                    "video_id": video_id,
                    "checked_paths": file_paths_to_check
                }), 200
        
        # MODE 2: Supprimer CLOUD seulement (expiration)
        elif mode == "cloud_only":
            if video.bunny_video_id and not video.cloud_deleted_at:
                try:
                    from src.services.bunny_deletion_service import bunny_deletion_service
                    success, error_msg = bunny_deletion_service.delete_video_from_bunny(video.bunny_video_id)
                    
                    if success:
                        video.cloud_deleted_at = datetime.utcnow()
                        video.deletion_mode = 'cloud_only'
                        video.deleted_at = datetime.utcnow()  # Pour compatibilité interface
                        db.session.commit()
                        logger.info(f"✅ Vidéo cloud supprimée (expirée): {video.bunny_video_id}")
                        return jsonify({
                            "message": "Vidéo cloud supprimée (expirée, stats préservées)",
                            "mode": "cloud_only",
                            "video_id": video_id
                        }), 200
                    else:
                        logger.error(f"❌ Échec suppression Bunny: {error_msg}")
                        return jsonify({"error": f"Bunny CDN: {error_msg}"}), 500
                        
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"❌ Exception suppression cloud: {e}")
                    return jsonify({"error": f"Erreur suppression cloud: {str(e)}"}), 500
            else:
                msg = "Vidéo cloud déjà supprimée" if video.cloud_deleted_at else "Aucune vidéo cloud à supprimer"
                return jsonify({"message": msg, "video_id": video_id}), 200
        
        # MODE 3: Supprimer LOCAL + CLOUD (nettoyage complet, stats préservées)
        elif mode == "local_and_cloud":
            errors = []
            local_deleted = False
            cloud_deleted = False
            deleted_files = []
            
            # Construire les chemins possibles pour le fichier local
            file_paths_to_check = []
            
            # Obtenir le club_id (les fichiers sont organisés par club, pas par court!)
            club_id = video.court.club_id if video.court else None
            
            # 1. Utiliser local_file_path si disponible
            if video.local_file_path:
                file_paths_to_check.append(video.local_file_path)
            
            # 2. Essayer de reconstruire le chemin
            if club_id:
                # Essayer d'obtenir recording_session_id si le champ existe
                recording_session_id = getattr(video, 'recording_session_id', None)
                
                if recording_session_id:
                    filename = f"{recording_session_id}.mp4"
                    reconstructed_path = os.path.join("static", "videos", str(club_id), filename)
                    file_paths_to_check.append(reconstructed_path)
                    file_paths_to_check.append(os.path.abspath(reconstructed_path))
                
                # Fallback: Essayer avec le titre si disponible
                if video.title:
                    filename = f"{video.title}.mp4"
                    reconstructed_path = os.path.join("static", "videos", str(club_id), filename)
                    file_paths_to_check.append(reconstructed_path)
                    file_paths_to_check.append(os.path.abspath(reconstructed_path))
            
            # Supprimer local (tous les fichiers trouvés)
            if not video.local_file_deleted_at:
                for file_path in file_paths_to_check:
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            deleted_files.append(file_path)
                            local_deleted = True
                            logger.info(f"✅ Fichier local supprimé: {file_path}")
                        except Exception as e:
                            errors.append(f"Local ({file_path}): {str(e)}")
                            logger.error(f"❌ Erreur suppression locale {file_path}: {e}")
                
                if local_deleted:
                    video.local_file_deleted_at = datetime.utcnow()

            
            # Supprimer cloud
            if video.bunny_video_id and not video.cloud_deleted_at:
                try:
                    from src.services.bunny_deletion_service import bunny_deletion_service
                    success, error_msg = bunny_deletion_service.delete_video_from_bunny(video.bunny_video_id)
                    
                    if success:
                        video.cloud_deleted_at = datetime.utcnow()
                        cloud_deleted = True
                        logger.info(f"✅ Vidéo cloud supprimée: {video.bunny_video_id}")
                    else:
                        errors.append(f"Cloud: {error_msg}")
                        logger.error(f"❌ Échec suppression cloud: {error_msg}")
                except Exception as e:
                    errors.append(f"Cloud: {str(e)}")
                    logger.error(f"❌ Exception suppression cloud: {e}")
            
            # Marquer en base
            video.deletion_mode = 'local_and_cloud'
            video.deleted_at = datetime.utcnow()
            db.session.commit()
            
            result_parts = []
            if local_deleted:
                result_parts.append(f"{len(deleted_files)} fichier(s) local(aux)")
            if cloud_deleted:
                result_parts.append("vidéo cloud")
            
            message = f"Supprimé: {' et '.join(result_parts)}" if result_parts else "Aucun fichier à supprimer"
            if errors:
                message += f" (erreurs: {', '.join(errors)})"
            
            return jsonify({
                "message": message,
                "mode": "local_and_cloud",
                "video_id": video_id,
                "local_deleted": local_deleted,
                "cloud_deleted": cloud_deleted,
                "deleted_files": deleted_files if deleted_files else None,
                "errors": errors if errors else None
            }), 200 if not errors else 207

        
        # MODE 4: Supprimer DATABASE (hard delete - TOUT disparaît)
        elif mode == "database":
            try:
                db.session.delete(video)
                db.session.commit()
                logger.info(f"✅ Vidéo {video_id} supprimée définitivement de la BDD")
                return jsonify({
                    "message": "Vidéo supprimée définitivement (stats perdues)",
                    "mode": "database",
                    "video_id": video_id
                }), 200
            except Exception as e:
                db.session.rollback()
                logger.error(f"❌ Erreur hard delete: {e}")
                return jsonify({"error": f"Erreur suppression BDD: {str(e)}"}), 500
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur inattendue suppression vidéo {video_id}: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500



# --- VIDEO LISTING (SUPER ADMIN ONLY) ---

@admin_bp.route("/videos", methods=["GET"])
def get_all_videos():
    """
    Récupère toutes les vidéos (y compris supprimées) avec infos complètes.
    Super admin uniquement.
    """
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Récupérer TOUTES les vidéos (y compris soft deleted)
        videos = Video.query.all()
        
        videos_data = []
        for video in videos:
            video_dict = video.to_dict()
            
            # Ajouter les informations de propriétaire et club
            if video.owner:
                video_dict['player_name'] = video.owner.name
                video_dict['player_email'] = video.owner.email
            
            if video.court and video.court.club:
                video_dict['club_name'] = video.court.club.name
                video_dict['court_name'] = video.court.name
            
            videos_data.append(video_dict)
        
        return jsonify({
            "videos": videos_data,
            "total": len(videos_data),
            "deleted": len([v for v in videos_data if v.get('is_deleted')])
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des vidéos: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500


# --- VIDEO UPLOAD RECOVERY (SUPER ADMIN ONLY) ---

@admin_bp.route("/videos/<int:video_id>/retry-bunny-upload", methods=["POST"])
def retry_bunny_upload(video_id):
    """
    Re-upload manuel d'une vidéo vers Bunny CDN
    Pour corriger les échecs d'upload
    
    Vérifie que le fichier local existe et ajoute la vidéo à la queue d'upload Bunny.
    """
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        video = Video.query.get_or_404(video_id)
        
        # Vérifier que fichier local existe
        if not video.local_file_path:
            return jsonify({
                "error": "Aucun chemin de fichier local enregistré pour cette vidéo"
            }), 404
        
        from pathlib import Path
        if not Path(video.local_file_path).exists():
            return jsonify({
                "error": f"Fichier local introuvable: {video.local_file_path}"
            }), 404
        
        # Importer le service Bunny Storage
        from src.services.bunny_storage_service import bunny_storage_service
        
        # Créer tâche upload avec métadonnées existantes
        bunny_video_id = video.bunny_video_id if video.bunny_video_id else None
        
        metadata = {
            'video_id': video.id,
            'title': video.title,
            'user_id': video.user_id,
            'bunny_video_id': bunny_video_id
        }
        
        # Ajouter à la queue d'upload
        task_id = bunny_storage_service.queue_upload(
            local_path=video.local_file_path,
            title=video.title,
            metadata=metadata
        )
        
        # Mettre à jour le statut en base
        video.processing_status = 'pending'
        db.session.commit()
        
        logger.info(f"✅ Upload programmé pour vidéo {video_id} (tâche: {task_id})")
        
        return jsonify({
            "message": "Upload programmé avec succès",
            "task_id": task_id,
            "video_id": video_id,
            "local_path": video.local_file_path
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur retry upload vidéo {video_id}: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500


@admin_bp.route("/videos/<int:video_id>/update-bunny-url", methods=["PATCH"])
def update_bunny_url(video_id):
    """
    Mettre à jour manuellement l'URL Bunny d'une vidéo
    Si admin a uploadé via dashboard Bunny
    
    Body JSON:
    {
        "bunny_video_id": "e660b8a0-f342-41fb-872e-3824ab90ab66",  # Requis
        "bunny_url": "https://vz-cc4565cd-4e9.b-cdn.net/..."       # Optionnel
    }
    """
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        video = Video.query.get_or_404(video_id)
        data = request.get_json()
        
        bunny_video_id = data.get('bunny_video_id')
        bunny_url = data.get('bunny_url')
        
        # Validation du bunny_video_id (doit être un GUID)
        if not bunny_video_id:
            return jsonify({"error": "bunny_video_id est requis"}), 400
        
        # Valider le format GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
        import re
        guid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        if not re.match(guid_pattern, bunny_video_id.lower()):
            return jsonify({
                "error": "Format bunny_video_id invalide. Attendu: GUID (ex: e660b8a0-f342-41fb-872e-3824ab90ab66)"
            }), 400
        
        # Mettre à jour la vidéo
        video.bunny_video_id = bunny_video_id
        
        if bunny_url:
            video.file_url = bunny_url
        else:
            # Construire l'URL à partir du bunny_video_id si non fournie
            # Format: https://vz-{library_id}.b-cdn.net/{video_id}/playlist.m3u8
            from src.config.bunny_config import BUNNY_CONFIG
            cdn_hostname = BUNNY_CONFIG.get('cdn_hostname', 'vz-cc4565cd-4e9.b-cdn.net')
            video.file_url = f"https://{cdn_hostname}/{bunny_video_id}/playlist.m3u8"
        
        # Mettre à jour le statut
        video.processing_status = 'ready'
        video.cdn_migrated_at = datetime.utcnow()
        
        db.session.commit()
        
        logger.info(f"✅ URL Bunny mise à jour pour vidéo {video_id}: {bunny_video_id}")
        
        return jsonify({
            "message": "URL Bunny mise à jour avec succès",
            "video": video.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur mise à jour URL Bunny vidéo {video_id}: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500


@admin_bp.route("/videos/create-manual", methods=["POST"])
def create_manual_video():
    """
    Créer manuellement une nouvelle vidéo pour un joueur
    Utile pour ajouter des vidéos uploadées via dashboard Bunny
    
    Body JSON:
    {
        "user_id": 123,                                              # Requis
        "bunny_video_id": "e660b8a0-f342-41fb-872e-3824ab90ab66",   # Requis
        "bunny_url": "https://vz-cc4565cd-4e9.b-cdn.net/...",       # Optionnel
        "title": "Ma vidéo de padel",                                # Requis
        "description": "Description...",                             # Optionnel
        "court_id": 5                                                # Optionnel
    }
    """
    if not require_super_admin():
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        
        # Validation des champs requis
        user_id = data.get('user_id')
        bunny_video_id = data.get('bunny_video_id')
        title = data.get('title')
        
        if not user_id:
            return jsonify({"error": "user_id est requis"}), 400
        
        if not bunny_video_id:
            return jsonify({"error": "bunny_video_id est requis"}), 400
            
        if not title:
            return jsonify({"error": "title est requis"}), 400
        
        # Vérifier que l'utilisateur existe
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": f"Utilisateur {user_id} introuvable"}), 404
        
        # Vérifier que l'utilisateur est un joueur
        if user.role != UserRole.PLAYER:
            return jsonify({"error": "L'utilisateur doit être un joueur"}), 400
        
        # Valider le format GUID du bunny_video_id
        import re
        guid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
        if not re.match(guid_pattern, bunny_video_id.lower()):
            return jsonify({
                "error": "Format bunny_video_id invalide. Attendu: GUID (ex: e660b8a0-f342-41fb-872e-3824ab90ab66)"
            }), 400
        
        # Récupérer les champs optionnels
        bunny_url = data.get('bunny_url')
        description = data.get('description', '')
        court_id = data.get('court_id')
        duration = data.get('duration')  # En secondes
        
        # Si court_id fourni, vérifier qu'il existe
        if court_id:
            court = Court.query.get(court_id)
            if not court:
                return jsonify({"error": f"Terrain {court_id} introuvable"}), 404
        
        # Générer l'URL si non fournie
        if not bunny_url:
            from src.config.bunny_config import BUNNY_CONFIG
            cdn_hostname = BUNNY_CONFIG.get('cdn_hostname', 'vz-cc4565cd-4e9.b-cdn.net')
            bunny_url = f"https://{cdn_hostname}/{bunny_video_id}/playlist.m3u8"
        
        # Si durée non fournie, essayer de la récupérer depuis Bunny API
        if not duration:
            try:
                from src.config.bunny_config import BUNNY_CONFIG
                import httpx
                
                api_key = BUNNY_CONFIG.get('api_key')
                library_id = BUNNY_CONFIG.get('library_id')
                
                if api_key and library_id:
                    url = f"https://video.bunnycdn.com/library/{library_id}/videos/{bunny_video_id}"
                    headers = {"AccessKey": api_key}
                    
                    with httpx.Client(timeout=10.0) as client:
                        response = client.get(url, headers=headers)
                        
                        if response.status_code == 200:
                            video_info = response.json()
                            duration = video_info.get('length', 0)  # Bunny retourne la durée en secondes
                            logger.info(f"📊 Durée détectée depuis Bunny: {duration}s (Video ID: {bunny_video_id})")
                        else:
                            logger.warning(f"⚠️ Impossible de récupérer la durée depuis Bunny: {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️ Erreur récupération durée depuis Bunny: {e}")
                # Continuer sans durée si échec
        
        # Créer la nouvelle vidéo
        new_video = Video(
            title=title,
            description=description,
            user_id=user_id,
            court_id=court_id,
            bunny_video_id=bunny_video_id,
            file_url=bunny_url,
            duration=duration,  # Peut être None si non fournie et non détectée
            processing_status='ready',  # Directement prête
            cdn_migrated_at=datetime.utcnow(),
            is_unlocked=True,  # Débloquée par défaut pour vidéos manuelles
            credits_cost=0,  # Pas de coût pour vidéos manuelles
            recorded_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        
        db.session.add(new_video)
        db.session.commit()
        
        logger.info(f"✅ Vidéo manuelle créée: ID {new_video.id} pour user {user.name} ({user.email})")
        
        return jsonify({
            "message": "Vidéo créée avec succès",
            "video": new_video.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur création vidéo manuelle: {e}")
        return jsonify({"error": f"Erreur: {str(e)}"}), 500

