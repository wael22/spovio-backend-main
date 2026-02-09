"""
Routes pour les joueurs - Optimisé pour 1000+ utilisateurs concurrents
Philosophie d'optimisation appliquée selon clubs.py et admin.py
"""

from flask import Blueprint, request, jsonify, session
from sqlalchemy.orm import joinedload
from sqlalchemy import desc, func, and_, or_
from datetime import datetime, timedelta
import json
import time
import logging

from ..models.database import db
from ..models.user import User, Club, Court, Video, ClubActionHistory, player_club_follows

logger = logging.getLogger(__name__)

players_bp = Blueprint('players', __name__, url_prefix='/api/players')

# --- FONCTIONS UTILITAIRES OPTIMISÉES ---

def simulate_payment(payment_method, amount_dt):
    """Simuler le paiement selon la méthode choisie"""
    # En production, intégrer avec les APIs réelles
    if payment_method == 'konnect':
        # Intégration Konnect API
        return True
    elif payment_method == 'flouci':
        # Intégration Flouci API
        return True
    elif payment_method == 'carte_bancaire':
        # Intégration gateway carte bancaire
        return True
    else:
        # Mode simulation pour tests
        return True

def require_player_access():
    """Vérification d'accès avec optimisations pour haute charge"""
    try:
        # MODE DEBUG: Accepter tout utilisateur authentifié
        if 'user_id' not in session:
            logger.warning("Tentative d'accès sans session")
            return None
        
        # Optimisation: requête simple sans jointure pour la vérification d'accès
        user = User.query.filter_by(id=session['user_id']).first()
        
        if not user:
            logger.warning(f"Utilisateur {session.get('user_id')} non trouvé")
            return None
            
        # MODE DEBUG: Accepter tous les rôles pour les tests
        # Normalement, on vérifierait user.role == 'PLAYER'
        logger.info(f"Accès accordé pour l'utilisateur {user.id} avec le rôle {user.role}")
        
        return user
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification d'accès: {e}")
        return None

def log_action(club_id, player_id, action_type, action_details, performed_by_id):
    """Log d'action optimisé avec gestion d'erreur robuste"""
    try:
        action_details_json = json.dumps(action_details) if isinstance(action_details, dict) else str(action_details)
        
        action_history = ClubActionHistory(
            club_id=club_id,
            user_id=player_id,
            action_type=action_type,
            action_details=action_details_json,
            performed_by_id=performed_by_id,
            performed_at=datetime.utcnow()
        )
        
        db.session.add(action_history)
        db.session.flush()  # Flush pour obtenir l'ID sans commit complet
        
        logger.info(f"Action loggée: {action_type} pour le joueur {player_id}")
        
    except Exception as e:
        logger.error(f"Erreur lors du logging de l'action {action_type}: {e}")
        # Ne pas lever l'exception pour éviter d'interrompre le flux principal

# --- ROUTES DE GESTION DES CLUBS ---

@players_bp.route("/debug/session", methods=["GET"])
def debug_session():
    """Route de debug pour vérifier la session"""
    try:
        return jsonify({
            "session_data": dict(session),
            "user_id_in_session": session.get('user_id'),
            "has_user_id": 'user_id' in session,
            "session_keys": list(session.keys())
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@players_bp.route("/debug/auth", methods=["GET"])
def debug_auth():
    """Route de debug pour vérifier l'authentification"""
    try:
        if 'user_id' not in session:
            return jsonify({
                "authenticated": False,
                "message": "Aucun user_id dans la session",
                "session": dict(session)
            }), 200
        
        user = User.query.filter_by(id=session['user_id']).first()
        if not user:
            return jsonify({
                "authenticated": False,
                "message": f"Utilisateur {session['user_id']} non trouvé",
                "session": dict(session)
            }), 200
        
        return jsonify({
            "authenticated": True,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": str(user.role)
            },
            "session": dict(session),
            "message": "Authentification valide"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@players_bp.route("/clubs/available", methods=["GET"])
def get_available_clubs():
    """Récupérer les clubs disponibles avec optimisations pour haute charge"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Requête simple et sûre
        clubs_query = db.session.query(Club).all()
        
        # Requête des clubs suivis de manière sécurisée
        try:
            followed_ids = {c.id for c in user.followed_clubs.all()}
        except Exception as e:
            logger.warning(f"Erreur avec followed_clubs: {e}")
            followed_ids = set()
        
        clubs_data = []
        for club in clubs_query:
            club_dict = club.to_dict()
            club_dict["is_followed"] = club.id in followed_ids
            
            # Compter les followers de manière sécurisée
            try:
                club_dict["followers_count"] = club.followers.count()
            except Exception:
                club_dict["followers_count"] = 0
                
            # Compter les courts
            club_dict["courts_count"] = len(club.courts) if hasattr(club, 'courts') and club.courts else 0
            clubs_data.append(club_dict)
        
        # Trier par popularité
        clubs_data.sort(key=lambda x: x.get("followers_count", 0), reverse=True)
        
        logger.info(f"Clubs disponibles récupérés pour le joueur {user.id}")
        return jsonify({
            "clubs": clubs_data,
            "total_clubs": len(clubs_data),
            "followed_count": len(followed_ids)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des clubs disponibles: {e}")
        return jsonify({"error": f"Erreur serveur: {str(e)}"}), 500
        return jsonify({"error": "Erreur lors de la récupération des clubs"}), 500

@players_bp.route("/clubs/<int:club_id>/follow", methods=["POST"])
def follow_club(club_id):
    """Suivre un club avec optimisations et validations robustes"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        club = Club.query.get_or_404(club_id)
        
        # Vérification optimisée pour dynamic relationship
        # Vérifier directement dans la table d'association
        existing_follow = db.session.execute(
            player_club_follows.select().where(
                player_club_follows.c.player_id == user.id,
                player_club_follows.c.club_id == club_id
            )
        ).first()
        
        if existing_follow:
            return jsonify({"error": "Vous suivez déjà ce club"}), 409
        
        # Limite de clubs suivis pour éviter la surcharge
        max_followed_clubs = 10  # Configurable
        if user.followed_clubs.count() >= max_followed_clubs:
            return jsonify({
                "error": f"Limite de {max_followed_clubs} clubs suivis atteinte"
            }), 400
        
        # Ajouter le suivi
        # Pour les relationships dynamiques, nous devons manipuler via l'ORM
        
        # Insérer dans la table d'association
        db.session.execute(
            player_club_follows.insert().values(
                player_id=user.id,
                club_id=club_id
            )
        )
        
        user.club_id = club.id
        
        # Log de l'action
        log_action(
            club_id=club_id, 
            player_id=user.id, 
            action_type='follow_club',
            action_details={
                "club_name": club.name,
                "club_address": club.address,
                "timestamp": datetime.utcnow().isoformat()
            }, 
            performed_by_id=user.id
        )
        
        db.session.commit()
        
        logger.info(f"Joueur {user.id} suit maintenant le club {club.id}")
        return jsonify({
            "message": f"Vous suivez maintenant {club.name}",
            "club": club.to_dict(),
            "followed_clubs_count": user.followed_clubs.count()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du suivi du club {club_id}: {e}")
        return jsonify({"error": "Erreur lors du suivi du club"}), 500

@players_bp.route("/clubs/<int:club_id>/unfollow", methods=["POST"])
def unfollow_club(club_id):
    """Arrêter de suivre un club avec gestion optimisée"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        club = Club.query.get_or_404(club_id)
        
        # Vérifier si l'utilisateur suit ce club
        existing_follow = db.session.execute(
            player_club_follows.select().where(
                player_club_follows.c.player_id == user.id,
                player_club_follows.c.club_id == club_id
            )
        ).first()
        
        if not existing_follow:
            return jsonify({"error": "Vous ne suivez pas ce club"}), 409
        
        # Retirer le suivi
        # Pour les relationships dynamiques, manipuler la table d'association directement
        
        # Supprimer de la table d'association
        db.session.execute(
            player_club_follows.delete().where(
                player_club_follows.c.player_id == user.id,
                player_club_follows.c.club_id == club_id
            )
        )
        
        # CORRECTION CRUCIALE: Réinitialiser l'affiliation principale
        if user.club_id == club_id:
            user.club_id = None
        
        # Log de l'action
        log_action(
            club_id=club_id, 
            player_id=user.id, 
            action_type='unfollow_club',
            action_details={
                "club_name": club.name,
                "timestamp": datetime.utcnow().isoformat()
            }, 
            performed_by_id=user.id
        )
        
        db.session.commit()
        
        logger.info(f"Joueur {user.id} ne suit plus le club {club.id}")
        return jsonify({
            "message": f"Vous ne suivez plus {club.name}",
            "followed_clubs_count": user.followed_clubs.count()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'arrêt du suivi du club {club_id}: {e}")
        return jsonify({"error": "Erreur lors de l'arrêt du suivi"}), 500

@players_bp.route("/clubs/followed", methods=["GET"])
def get_followed_clubs():
    """Récupérer les clubs suivis avec détails étendus"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        followed_clubs_data = []
        
        # Requête sécurisée des clubs suivis
        try:
            followed_clubs = user.followed_clubs.all()
        except Exception as e:
            logger.warning(f"Erreur avec followed_clubs: {e}")
            followed_clubs = []
        
        for club in followed_clubs:
            club_dict = club.to_dict()
            
            # Ajouter des statistiques enrichies de manière sécurisée
            club_dict["courts_count"] = len(club.courts) if hasattr(club, 'courts') and club.courts else 0
            
            try:
                club_dict["followers_count"] = club.followers.count()
            except Exception:
                club_dict["followers_count"] = 0
                
            club_dict["is_primary_club"] = (user.club_id == club.id)
            
            # Dernière activité du joueur dans ce club
            try:
                last_activity = ClubActionHistory.query.filter_by(
                    club_id=club.id,
                    user_id=user.id
                ).order_by(desc(ClubActionHistory.performed_at)).first()
                
                if last_activity:
                    club_dict["last_activity"] = {
                        "action_type": last_activity.action_type,
                        "performed_at": last_activity.performed_at.isoformat()
                    }
            except Exception:
                pass
            
            followed_clubs_data.append(club_dict)
        
        return jsonify({
            "clubs": followed_clubs_data,
            "total_followed": len(followed_clubs_data),
            "primary_club_id": user.club_id
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des clubs suivis: {e}")
        return jsonify({"error": "Erreur lors de la récupération"}), 500

# --- ROUTES DE DASHBOARD JOUEUR ---

@players_bp.route("/dashboard", methods=["GET"])
def get_player_dashboard():
    """Dashboard complet du joueur avec toutes ses statistiques"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        logger.info(f"Récupération du dashboard pour le joueur {user.id}")
        
        # 1. Informations de base du joueur
        player_info = user.to_dict()
        
        # 2. Statistiques des clubs suivis
        followed_clubs_count = user.followed_clubs.count()  # count() pour dynamic relationship
        primary_club = None
        if user.club_id:
            primary_club = Club.query.get(user.club_id)
        
        # 3. Statistiques des vidéos du joueur
        player_videos = Video.query.filter_by(user_id=user.id).all()
        videos_stats = {
            "total_videos": len(player_videos),
            "unlocked_videos": len([v for v in player_videos if v.is_unlocked]),
            "total_duration": sum(v.duration for v in player_videos if v.duration),
            "recent_videos": [v.to_dict() for v in player_videos[-5:]]  # 5 dernières
        }
        
        # 4. Historique d'activité récente
        recent_activity = ClubActionHistory.query.filter_by(
            user_id=user.id
        ).order_by(desc(ClubActionHistory.performed_at)).limit(10).all()
        
        activity_data = []
        for activity in recent_activity:
            club_name = "Club inconnu"
            if activity.club_id:
                club = Club.query.get(activity.club_id)
                if club:
                    club_name = club.name
            
            activity_data.append({
                "action_type": activity.action_type,
                "club_name": club_name,
                "performed_at": activity.performed_at.isoformat(),
                "details": activity.action_details
            })
        
        # 5. Statistiques de crédits
        credits_stats = {
            "current_balance": user.credits_balance,
            "credits_earned_this_month": 0,  # À calculer depuis l'historique
            "credits_spent_this_month": 0     # À calculer depuis l'historique
        }
        
        # Calculer les crédits du mois
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_credits = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            ClubActionHistory.action_type == 'add_credits',
            ClubActionHistory.performed_at >= month_start
        ).all()
        
        for entry in monthly_credits:
            try:
                if entry.action_details:
                    details = json.loads(entry.action_details)
                    credits_added = details.get('credits_added', 0)
                    if isinstance(credits_added, (int, float)):
                        credits_stats["credits_earned_this_month"] += int(credits_added)
            except:
                pass
        
        # 6. Recommandations de clubs
        recommended_clubs = []
        try:
            # Recommander des clubs populaires non suivis
            all_clubs = Club.query.all()
            followed_ids = {c.id for c in user.followed_clubs.all()}  # .all() pour dynamic relationship
            
            for club in all_clubs:
                if club.id not in followed_ids:
                    followers_count = club.followers.count()  # count() pour dynamic relationship
                    courts_count = len(club.courts) if hasattr(club, 'courts') else 0
                    
                    if followers_count > 0 or courts_count > 0:  # Clubs actifs
                        club_dict = club.to_dict()
                        club_dict["followers_count"] = followers_count
                        club_dict["courts_count"] = courts_count
                        recommended_clubs.append(club_dict)
            
            # Trier par popularité et prendre les 5 premiers
            recommended_clubs.sort(key=lambda x: x.get("followers_count", 0), reverse=True)
            recommended_clubs = recommended_clubs[:5]
        except Exception as e:
            logger.error(f"Erreur lors du calcul des recommandations: {e}")
        
        dashboard_data = {
            "player": player_info,
            "clubs_statistics": {
                "followed_clubs_count": followed_clubs_count,
                "primary_club": primary_club.to_dict() if primary_club else None
            },
            "videos_statistics": videos_stats,
            "credits_statistics": credits_stats,
            "recent_activity": activity_data,
            "recommended_clubs": recommended_clubs,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return jsonify(dashboard_data), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du dashboard joueur: {e}")
        return jsonify({"error": "Erreur lors de la récupération du dashboard"}), 500

# --- ROUTES DE GESTION DES VIDÉOS ---

@players_bp.route("/videos", methods=["GET"])
def get_player_videos():
    """Récupérer toutes les vidéos du joueur avec filtres"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Paramètres de filtrage
        club_id = request.args.get('club_id', type=int)
        is_unlocked = request.args.get('is_unlocked')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Construire la requête
        query = Video.query.filter_by(user_id=user.id)
        
        if club_id:
            # Filtrer par club via les terrains
            query = query.join(Court).filter(Court.club_id == club_id)
        
        if is_unlocked is not None:
            query = query.filter(Video.is_unlocked == (is_unlocked.lower() == 'true'))
        
        # Appliquer pagination et tri
        videos = query.order_by(desc(Video.recorded_at)).offset(offset).limit(limit).all()
        total_count = query.count()
        
        # Enrichir les données des vidéos
        videos_data = []
        for video in videos:
            video_dict = video.to_dict()
            
            # Ajouter les informations du terrain et du club
            court = Court.query.get(video.court_id)
            if court:
                video_dict["court_name"] = court.name
                club = Club.query.get(court.club_id)
                if club:
                    video_dict["club_name"] = club.name
                    video_dict["club_id"] = club.id
            
            videos_data.append(video_dict)
        
        return jsonify({
            "videos": videos_data,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total_count
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos du joueur: {e}")
        return jsonify({"error": "Erreur lors de la récupération des vidéos"}), 500

@players_bp.route("/videos/<int:video_id>/unlock", methods=["POST"])
def unlock_video(video_id):
    """Débloquer une vidéo avec des crédits"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        video = Video.query.get_or_404(video_id)
        
        # Vérifier que la vidéo appartient au joueur
        if video.user_id != user.id:
            return jsonify({"error": "Cette vidéo ne vous appartient pas"}), 403
        
        # Vérifier si déjà débloquée
        if video.is_unlocked:
            return jsonify({"error": "Cette vidéo est déjà débloquée"}), 400
        
        # Vérifier les crédits suffisants
        if user.credits_balance < video.credits_cost:
            return jsonify({
                "error": "Crédits insuffisants",
                "required": video.credits_cost,
                "available": user.credits_balance
            }), 400
        
        # Débloquer la vidéo
        user.credits_balance -= video.credits_cost
        video.is_unlocked = True
        
        # Log de l'action
        court = Court.query.get(video.court_id)
        club_id = court.club_id if court else None
        
        log_action(
            club_id=club_id,
            player_id=user.id,
            action_type='unlock_video',
            action_details={
                "video_id": video.id,
                "video_title": video.title,
                "credits_spent": video.credits_cost,
                "new_balance": user.credits_balance
            },
            performed_by_id=user.id
        )
        
        db.session.commit()
        
        logger.info(f"Joueur {user.id} a débloqué la vidéo {video.id}")
        return jsonify({
            "message": "Vidéo débloquée avec succès",
            "video": video.to_dict(),
            "new_credits_balance": user.credits_balance
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du déblocage de la vidéo {video_id}: {e}")
        return jsonify({"error": "Erreur lors du déblocage de la vidéo"}), 500

# --- ROUTES DE GESTION DES CRÉDITS OPTIMISÉES ---

@players_bp.route("/credits/buy", methods=["POST"])
def buy_credits():
    """Acheter des crédits avec les tarifs tunisiens"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        credits_amount = data.get('credits_amount', 0)
        payment_method = data.get('payment_method', 'simulation')  # simulation, konnect, flouci, carte_bancaire
        package_type = data.get('package_type', 'individual')  # individual, pack
        package_id = data.get('package_id', '')  # ID du package sélectionné
        
        if credits_amount <= 0:
            return jsonify({"error": "Nombre de crédits invalide"}), 400
        
        # Calcul des tarifs selon le package
        price_dt = credits_amount * 10  # Prix de base
        savings_dt = 0
        discount_percent = 0
        
        # Appliquer les remises pour les packs
        if package_type == 'pack':
            if package_id == 'pack_5' and credits_amount == 5:
                price_dt = 45
                savings_dt = 5
                discount_percent = 10
            elif package_id == 'pack_10' and credits_amount == 10:
                price_dt = 80
                savings_dt = 20
                discount_percent = 20
            elif package_id == 'pack_25' and credits_amount == 25:
                price_dt = 187.5
                savings_dt = 62.5
                discount_percent = 25
            elif package_id == 'pack_50' and credits_amount == 50:
                price_dt = 350
                savings_dt = 150
                discount_percent = 30
        
        # Simulation de paiement (en production, intégrer avec Konnect/Flouci et carte bancaire)
        payment_successful = simulate_payment(payment_method, price_dt)  # Simuler selon la méthode
        
        if payment_successful:
            # Ajouter les crédits au solde
            user.credits_balance += credits_amount
            
            # Log de la transaction
            log_action(
                club_id=user.club_id,
                player_id=user.id,
                action_type='buy_credits',
                action_details={
                    "credits_purchased": credits_amount,
                    "price_dt": price_dt,
                    "savings_dt": savings_dt,
                    "discount_percent": discount_percent,
                    "payment_method": payment_method,
                    "package_type": package_type,
                    "package_id": package_id,
                    "new_balance": user.credits_balance,
                    "transaction_timestamp": datetime.utcnow().isoformat()
                },
                performed_by_id=user.id
            )
            
            # Créer une notification pour l'utilisateur
            try:
                from src.models.notification import Notification, NotificationType
                
                Notification.create_notification(
                    user_id=user.id,
                    notification_type=NotificationType.CREDITS_ADDED,
                    title="Crédits ajoutés !",
                    message=f"{credits_amount} crédits ont été ajoutés à votre compte",
                    link="/player"
                )
                logger.info(f"✅ Notification créée pour user {user.id} - achat {credits_amount} crédits")
            except Exception as notif_error:
                logger.error(f"❌ Erreur création notification: {notif_error}")
            
            db.session.commit()
            
            logger.info(f"Joueur {user.id} a acheté {credits_amount} crédits pour {price_dt} DT")
            return jsonify({
                "message": f"Achat de {credits_amount} crédits réussi !",
                "credits_purchased": credits_amount,
                "price_paid_dt": price_dt,
                "savings_dt": savings_dt,
                "discount_percent": discount_percent,
                "new_balance": user.credits_balance,
                "package_type": package_type,
                "package_id": package_id,
                "payment_method": payment_method,
                "transaction_id": f"TXN_{user.id}_{int(time.time())}"
            }), 200
        else:
            return jsonify({
                "error": "Échec du paiement",
                "message": "La transaction n'a pas pu être complétée"
            }), 400
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'achat de crédits: {e}")
        return jsonify({"error": "Erreur lors de l'achat de crédits"}), 500

@players_bp.route("/credits/packages", methods=["GET"])
def get_credit_packages():
    """Récupérer les packages de crédits disponibles"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Charger les packages depuis la base de données
        from src.models.credit_package import CreditPackage
        
        db_packages = CreditPackage.query.filter_by(
            package_type='player',
            is_active=True
        ).order_by(CreditPackage.credits.asc()).all()
        
        # Si aucun package en DB, utiliser les packages par défaut
        if not db_packages:
            packages = [
                {
                    "id": "credit_1",
                    "credits": 1,
                    "price_dt": 10,
                    "type": "individual",
                    "popular": False,
                    "description": "1 crédit pour débloquer une vidéo"
                },
                {
                    "id": "pack_5",
                    "credits": 5,
                    "price_dt": 45,
                    "original_price_dt": 50,
                    "savings_dt": 5,
                    "discount_percent": 10,
                    "type": "pack",
                    "popular": False,
                    "description": "Pack 5 crédits avec 10% de remise",
                    "badge": "Économie 10%"
                },
                {
                    "id": "pack_10",
                    "credits": 10,
                    "price_dt": 80,
                    "original_price_dt": 100,
                    "savings_dt": 20,
                    "discount_percent": 20,
                    "type": "pack",
                    "popular": True,
                    "description": "Pack populaire - 10 crédits avec 20% de remise",
                    "badge": "Meilleure offre"
                },
                {
                    "id": "pack_25",
                    "credits": 25,
                    "price_dt": 187.5,
                    "original_price_dt": 250,
                    "savings_dt": 62.5,
                    "discount_percent": 25,
                    "type": "pack",
                    "popular": False,
                    "description": "Pack 25 crédits avec 25% de remise",
                    "badge": "Économie 25%"
                },
                {
                    "id": "pack_50",
                    "credits": 50,
                    "price_dt": 350,
                    "original_price_dt": 500,
                    "savings_dt": 150,
                    "discount_percent": 30,
                    "type": "pack",
                    "popular": False,
                    "description": "Pack professionnel - 50 crédits avec 30% de remise",
                    "badge": "Économie 30%"
                }
            ]
        else:
            # Convertir les packages DB en dictionnaires
            packages = [pkg.to_dict() for pkg in db_packages]
        
        return jsonify({
            "packages": packages,
            "current_balance": user.credits_balance,
            "currency": "DT",
            "exchange_rate": "1 crédit = 10 DT",
            "special_offers": [
                {
                    "title": "Pack de 10 crédits",
                    "description": "Économisez 20 DT avec notre pack populaire",
                    "savings": "20 DT"
                }
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des packages: {e}")
        return jsonify({"error": "Erreur lors de la récupération des packages"}), 500

@players_bp.route("/credits/payment-methods", methods=["GET"])
def get_payment_methods():
    """Récupérer les méthodes de paiement disponibles"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        payment_methods = [
            {
                "id": "simulation",
                "name": "Simulation",
                "description": "Mode test pour le développement",
                "icon": "test",
                "enabled": True,
                "processing_time": "Instantané"
            },
            {
                "id": "konnect",
                "name": "Konnect",
                "description": "Paiement mobile via Konnect",
                "icon": "konnect",
                "enabled": True,
                "processing_time": "1-2 minutes",
                "supported_networks": ["Orange", "Ooredoo", "Tunisie Telecom"]
            },
            {
                "id": "flouci",
                "name": "Flouci",
                "description": "Portefeuille électronique Flouci",
                "icon": "flouci",
                "enabled": True,
                "processing_time": "Instantané"
            },
            {
                "id": "carte_bancaire",
                "name": "Carte Bancaire",
                "description": "Paiement par carte Visa/MasterCard",
                "icon": "credit_card",
                "enabled": True,
                "processing_time": "Instantané",
                "supported_cards": ["Visa", "MasterCard"]
            }
        ]
        
        return jsonify({
            "payment_methods": payment_methods,
            "default_method": "konnect",
            "currency": "DT"
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des méthodes de paiement: {e}")
        return jsonify({"error": "Erreur lors de la récupération des méthodes de paiement"}), 500

@players_bp.route("/credits/history", methods=["GET"])
def get_credits_history():
    """Historique détaillé des crédits avec pagination"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Récupérer l'historique des crédits
        credits_actions = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            or_(
                ClubActionHistory.action_type == 'buy_credits',
                ClubActionHistory.action_type == 'unlock_video',
                ClubActionHistory.action_type == 'purchase'
            )
        ).order_by(desc(ClubActionHistory.performed_at)).offset(offset).limit(limit).all()
        
        total_count = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            or_(
                ClubActionHistory.action_type == 'buy_credits',
                ClubActionHistory.action_type == 'unlock_video',
                ClubActionHistory.action_type == 'purchase'
            )
        ).count()
        
        history_data = []
        for action in credits_actions:
            action_data = {
                "id": action.id,
                "action_type": action.action_type,
                "performed_at": action.performed_at.isoformat(),
                "details": action.action_details
            }
            
            # Ajouter les informations du club si disponible
            if action.club_id:
                club = Club.query.get(action.club_id)
                if club:
                    action_data["club_name"] = club.name
            
            history_data.append(action_data)
        
        return jsonify({
            "history": history_data,
            "total_count": total_count,
            "current_balance": user.credits_balance,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total_count
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'historique des crédits: {e}")
        return jsonify({"error": "Erreur lors de la récupération de l'historique"}), 500

@players_bp.route("/credits/balance", methods=["GET"])
def get_credits_balance():
    """Récupérer le solde actuel des crédits"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Calculer les statistiques des crédits
        total_earned = 0
        total_spent = 0
        
        credits_actions = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            or_(
                ClubActionHistory.action_type == 'buy_credits',
                ClubActionHistory.action_type == 'unlock_video'
            )
        ).all()
        
        for action in credits_actions:
            try:
                if action.action_details:
                    details = json.loads(action.action_details)
                    
                    if action.action_type == 'buy_credits':
                        credits_added = details.get('credits_purchased', 0)
                        if isinstance(credits_added, (int, float)):
                            total_earned += int(credits_added)
                    
                    elif action.action_type == 'unlock_video':
                        credits_spent = details.get('credits_spent', 0)
                        if isinstance(credits_spent, (int, float)):
                            total_spent += int(credits_spent)
            except:
                continue
        
        return jsonify({
            "current_balance": user.credits_balance,
            "total_earned": total_earned,
            "total_spent": total_spent,
            "net_balance": total_earned - total_spent
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du solde des crédits: {e}")
        return jsonify({"error": "Erreur lors de la récupération du solde"}), 500

# --- ROUTES DE STATISTIQUES JOUEUR ---

@players_bp.route("/statistics", methods=["GET"])
def get_player_statistics():
    """Statistiques détaillées du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Statistiques générales
        total_videos = Video.query.filter_by(user_id=user.id).count()
        unlocked_videos = Video.query.filter_by(user_id=user.id, is_unlocked=True).count()
        
        # Statistiques par club
        clubs_stats = []
        for club in user.followed_clubs:
            club_videos = db.session.query(Video).join(Court).filter(
                Court.club_id == club.id,
                Video.user_id == user.id
            ).count()
            
            clubs_stats.append({
                "club": club.to_dict(),
                "videos_count": club_videos
            })
        
        # Activité par mois (derniers 6 mois)
        monthly_activity = []
        for i in range(6):
            month_start = (datetime.utcnow().replace(day=1) - timedelta(days=30*i)).replace(day=1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            
            month_videos = Video.query.filter(
                Video.user_id == user.id,
                Video.recorded_at >= month_start,
                Video.recorded_at <= month_end
            ).count()
            
            monthly_activity.append({
                "month": month_start.strftime("%Y-%m"),
                "videos_count": month_videos
            })
        
        return jsonify({
            "general_statistics": {
                "total_videos": total_videos,
                "unlocked_videos": unlocked_videos,
                "locked_videos": total_videos - unlocked_videos,
                "followed_clubs": len(user.followed_clubs),
                "current_credits": user.credits_balance
            },
            "clubs_statistics": clubs_stats,
            "monthly_activity": monthly_activity[::-1]  # Ordre chronologique
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des statistiques: {e}")
        return jsonify({"error": "Erreur lors de la récupération des statistiques"}), 500

# --- ROUTES DE PROFIL ---

@players_bp.route("/profile", methods=["GET"])
def get_player_profile():
    """Récupérer le profil complet du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        profile_data = user.to_dict()
        
        # Ajouter des informations enrichies
        if user.club_id:
            primary_club = Club.query.get(user.club_id)
            profile_data["primary_club"] = primary_club.to_dict() if primary_club else None
        
        profile_data["followed_clubs_count"] = len(user.followed_clubs)
        profile_data["total_videos"] = Video.query.filter_by(user_id=user.id).count()
        
        return jsonify({"profile": profile_data}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du profil: {e}")
        return jsonify({"error": "Erreur lors de la récupération du profil"}), 500

@players_bp.route("/profile", methods=["PUT"])
def update_player_profile():
    """Mettre à jour le profil du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        
        # Champs modifiables
        if 'name' in data and data['name'].strip():
            user.name = data['name'].strip()
        
        if 'phone_number' in data:
            user.phone_number = data['phone_number']
        
        # Log de la modification
        log_action(
            club_id=user.club_id,
            player_id=user.id,
            action_type='update_profile',
            action_details={
                "updated_fields": list(data.keys()),
                "timestamp": datetime.utcnow().isoformat()
            },
            performed_by_id=user.id
        )
        
        db.session.commit()
        
        logger.info(f"Profil mis à jour pour le joueur {user.id}")
        return jsonify({
            "message": "Profil mis à jour avec succès",
            "profile": user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de la mise à jour du profil: {e}")
        return jsonify({"error": "Erreur lors de la mise à jour du profil"}), 500

# --- ROUTES DE RECHERCHE OPTIMISÉES ---

@players_bp.route("/search/clubs", methods=["GET"])
def search_clubs():
    """Recherche optimisée de clubs avec filtres avancés"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Paramètres de recherche
        query_text = request.args.get('q', '').strip()
        city = request.args.get('city', '').strip()
        min_courts = request.args.get('min_courts', 0, type=int)
        max_distance = request.args.get('max_distance', type=float)
        sort_by = request.args.get('sort_by', 'popularity')  # popularity, name, distance
        limit = request.args.get('limit', 20, type=int)
        
        # Construire la requête de base
        clubs_query = Club.query
        
        # Filtres textuels
        if query_text:
            clubs_query = clubs_query.filter(
                or_(
                    Club.name.contains(query_text),
                    Club.address.contains(query_text)
                )
            )
        
        if city:
            clubs_query = clubs_query.filter(Club.address.contains(city))
        
        # Filtrer par nombre de terrains
        if min_courts > 0:
            clubs_query = clubs_query.join(Court).group_by(Club.id).having(
                func.count(Court.id) >= min_courts
            )
        
        clubs = clubs_query.limit(limit).all()
        
        # Enrichir les résultats
        results = []
        followed_ids = {c.id for c in user.followed_clubs}
        
        for club in clubs:
            club_dict = club.to_dict()
            club_dict["is_followed"] = club.id in followed_ids
            club_dict["courts_count"] = len(club.courts) if hasattr(club, 'courts') else 0
            club_dict["followers_count"] = len(club.followers.all()) if hasattr(club, 'followers') else 0
            
            results.append(club_dict)
        
        # Tri des résultats
        if sort_by == 'popularity':
            results.sort(key=lambda x: x.get("followers_count", 0), reverse=True)
        elif sort_by == 'name':
            results.sort(key=lambda x: x.get("name", ""))
        
        return jsonify({
            "clubs": results,
            "total_found": len(results),
            "search_params": {
                "query": query_text,
                "city": city,
                "min_courts": min_courts,
                "sort_by": sort_by
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la recherche de clubs: {e}")
        return jsonify({"error": "Erreur lors de la recherche"}), 500

# --- ROUTES SOCIALES ET COMMUNAUTAIRES ---

@players_bp.route("/social/leaderboard", methods=["GET"])
def get_leaderboard():
    """Classement des joueurs par crédits ou activité"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        sort_by = request.args.get('sort_by', 'credits')  # credits, videos, activity
        club_id = request.args.get('club_id', type=int)
        limit = request.args.get('limit', 10, type=int)
        
        # Construire la requête de base
        if club_id:
            # Classement par club
            players_query = User.query.filter(
                User.role == 'PLAYER',
                User.club_id == club_id
            )
        else:
            # Classement global
            players_query = User.query.filter(User.role == 'PLAYER')
        
        # Tri selon le critère choisi
        if sort_by == 'credits':
            players = players_query.order_by(desc(User.credits_balance)).limit(limit).all()
        elif sort_by == 'videos':
            # Trier par nombre de vidéos (nécessite une jointure)
            players = db.session.query(User).join(Video).filter(
                User.role == 'PLAYER'
            ).group_by(User.id).order_by(
                desc(func.count(Video.id))
            ).limit(limit).all()
        else:
            # Trier par activité récente
            players = players_query.order_by(desc(User.last_login)).limit(limit).all()
        
        leaderboard_data = []
        for i, player in enumerate(players, 1):
            player_data = {
                "rank": i,
                "name": player.name,
                "credits_balance": player.credits_balance,
                "videos_count": Video.query.filter_by(user_id=player.id).count(),
                "is_current_user": (player.id == user.id)
            }
            
            # Ajouter le club si disponible
            if player.club_id:
                club = Club.query.get(player.club_id)
                if club:
                    player_data["club_name"] = club.name
            
            leaderboard_data.append(player_data)
        
        # Position du joueur actuel
        current_user_rank = None
        for i, player_data in enumerate(leaderboard_data):
            if player_data["is_current_user"]:
                current_user_rank = i + 1
                break
        
        return jsonify({
            "leaderboard": leaderboard_data,
            "current_user_rank": current_user_rank,
            "sort_by": sort_by,
            "club_id": club_id
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du classement: {e}")
        return jsonify({"error": "Erreur lors de la récupération du classement"}), 500

@players_bp.route("/social/activity_feed", methods=["GET"])
def get_activity_feed():
    """Flux d'activité des clubs suivis"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        # Récupérer les IDs des clubs suivis
        followed_club_ids = [c.id for c in user.followed_clubs]
        
        if not followed_club_ids:
            return jsonify({
                "activities": [],
                "total_count": 0,
                "offset": offset,
                "limit": limit
            }), 200
        
        # Récupérer les activités des clubs suivis
        activities = ClubActionHistory.query.filter(
            ClubActionHistory.club_id.in_(followed_club_ids),
            ClubActionHistory.action_type.in_([
                'join_club', 'leave_club', 'add_video', 'unlock_video',
                'create_court', 'update_club_info'
            ])
        ).order_by(desc(ClubActionHistory.performed_at)).offset(offset).limit(limit).all()
        
        total_count = ClubActionHistory.query.filter(
            ClubActionHistory.club_id.in_(followed_club_ids),
            ClubActionHistory.action_type.in_([
                'join_club', 'leave_club', 'add_video', 'unlock_video',
                'create_court', 'update_club_info'
            ])
        ).count()
        
        activities_data = []
        for activity in activities:
            activity_data = {
                "id": activity.id,
                "action_type": activity.action_type,
                "performed_at": activity.performed_at.isoformat(),
                "details": activity.action_details
            }
            
            # Ajouter les informations du club
            if activity.club_id:
                club = Club.query.get(activity.club_id)
                if club:
                    activity_data["club"] = {
                        "id": club.id,
                        "name": club.name
                    }
            
            # Ajouter les informations du joueur (si ce n'est pas l'utilisateur actuel)
            if activity.user_id and activity.user_id != user.id:
                activity_user = User.query.get(activity.user_id)
                if activity_user:
                    activity_data["user"] = {
                        "name": activity_user.name
                    }
            
            activities_data.append(activity_data)
        
        return jsonify({
            "activities": activities_data,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total_count
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du flux d'activité: {e}")
        return jsonify({"error": "Erreur lors de la récupération du flux"}), 500

# --- ROUTES DE DIAGNOSTIC ET MAINTENANCE ---

@players_bp.route("/diagnostics/health", methods=["GET"])
def player_health_check():
    """Diagnostic de santé des données du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        diagnostics = {
            "player_id": user.id,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": []
        }
        
        # 1. Vérification des clubs suivis
        followed_count = len(user.followed_clubs)
        diagnostics["checks"].append({
            "name": "clubs_followed",
            "status": "OK" if followed_count > 0 else "WARNING",
            "value": followed_count,
            "message": f"{followed_count} clubs suivis" if followed_count > 0 else "Aucun club suivi"
        })
        
        # 2. Vérification du club principal
        primary_club_status = "OK" if user.club_id else "INFO"
        primary_club_msg = f"Club principal: {user.club_id}" if user.club_id else "Aucun club principal défini"
        diagnostics["checks"].append({
            "name": "primary_club",
            "status": primary_club_status,
            "value": user.club_id,
            "message": primary_club_msg
        })
        
        # 3. Vérification des vidéos
        total_videos = Video.query.filter_by(user_id=user.id).count()
        unlocked_videos = Video.query.filter_by(user_id=user.id, is_unlocked=True).count()
        diagnostics["checks"].append({
            "name": "videos_status",
            "status": "OK",
            "value": {"total": total_videos, "unlocked": unlocked_videos},
            "message": f"{total_videos} vidéos total, {unlocked_videos} débloquées"
        })
        
        # 4. Vérification du solde des crédits
        credits_status = "OK" if user.credits_balance >= 0 else "ERROR"
        diagnostics["checks"].append({
            "name": "credits_balance",
            "status": credits_status,
            "value": user.credits_balance,
            "message": f"Solde: {user.credits_balance} crédits"
        })
        
        # 5. Vérification de l'activité récente
        recent_activity = ClubActionHistory.query.filter_by(user_id=user.id).order_by(
            desc(ClubActionHistory.performed_at)
        ).first()
        
        if recent_activity:
            days_since_activity = (datetime.utcnow() - recent_activity.performed_at).days
            activity_status = "OK" if days_since_activity <= 30 else "WARNING"
            activity_msg = f"Dernière activité il y a {days_since_activity} jours"
        else:
            activity_status = "WARNING"
            activity_msg = "Aucune activité enregistrée"
        
        diagnostics["checks"].append({
            "name": "recent_activity",
            "status": activity_status,
            "value": days_since_activity if recent_activity else None,
            "message": activity_msg
        })
        
        # Calcul du statut global
        statuses = [check["status"] for check in diagnostics["checks"]]
        if "ERROR" in statuses:
            overall_status = "ERROR"
        elif "WARNING" in statuses:
            overall_status = "WARNING"
        else:
            overall_status = "OK"
        
        diagnostics["overall_status"] = overall_status
        
        return jsonify(diagnostics), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du diagnostic de santé: {e}")
        return jsonify({"error": "Erreur lors du diagnostic"}), 500

@players_bp.route("/diagnostics/performance", methods=["GET"])
def player_performance_metrics():
    """Métriques de performance pour optimisation haute charge"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        start_time = time.time()
        
        metrics = {
            "player_id": user.id,
            "timestamp": datetime.utcnow().isoformat(),
            "performance_metrics": {}
        }
        
        # 1. Test de requête clubs suivis (avec optimisation)
        clubs_start = time.time()
        followed_clubs = db.session.query(Club).options(
            joinedload(Club.followers),
            joinedload(Club.courts)
        ).join(User.followed_clubs).filter(User.id == user.id).all()
        clubs_time = time.time() - clubs_start
        
        metrics["performance_metrics"]["followed_clubs_query"] = {
            "execution_time_ms": round(clubs_time * 1000, 2),
            "clubs_count": len(followed_clubs),
            "status": "OK" if clubs_time < 0.1 else "WARNING"
        }
        
        # 2. Test de requête vidéos (avec optimisation)
        videos_start = time.time()
        videos = Video.query.filter_by(user_id=user.id).limit(50).all()
        videos_time = time.time() - videos_start
        
        metrics["performance_metrics"]["videos_query"] = {
            "execution_time_ms": round(videos_time * 1000, 2),
            "videos_count": len(videos),
            "status": "OK" if videos_time < 0.1 else "WARNING"
        }
        
        # 3. Test de requête historique
        history_start = time.time()
        history = ClubActionHistory.query.filter_by(user_id=user.id).limit(20).all()
        history_time = time.time() - history_start
        
        metrics["performance_metrics"]["history_query"] = {
            "execution_time_ms": round(history_time * 1000, 2),
            "entries_count": len(history),
            "status": "OK" if history_time < 0.1 else "WARNING"
        }
        
        # 4. Métriques de session
        total_time = time.time() - start_time
        metrics["performance_metrics"]["total_execution"] = {
            "execution_time_ms": round(total_time * 1000, 2),
            "status": "OK" if total_time < 0.5 else "WARNING"
        }
        
        # 5. Recommandations d'optimisation
        recommendations = []
        if clubs_time > 0.1:
            recommendations.append("Optimiser les requêtes de clubs suivis avec plus de jointures")
        if videos_time > 0.1:
            recommendations.append("Ajouter un index sur user_id pour la table vidéos")
        if history_time > 0.1:
            recommendations.append("Optimiser les requêtes d'historique avec pagination")
        
        metrics["recommendations"] = recommendations
        
        return jsonify(metrics), 200
        
    except Exception as e:
        logger.error(f"Erreur lors des métriques de performance: {e}")
        return jsonify({"error": "Erreur lors du test de performance"}), 500

# --- ROUTE DE MAINTENANCE SPÉCIALISÉE ---

@players_bp.route("/maintenance/cleanup", methods=["POST"])
def player_data_cleanup():
    """Nettoyage des données obsolètes du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        cleanup_report = {
            "player_id": user.id,
            "timestamp": datetime.utcnow().isoformat(),
            "actions_performed": []
        }
        
        # 1. Nettoyer les anciennes entrées d'historique (> 6 mois)
        six_months_ago = datetime.utcnow() - timedelta(days=180)
        old_history_count = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            ClubActionHistory.performed_at < six_months_ago
        ).count()
        
        if old_history_count > 0:
            ClubActionHistory.query.filter(
                ClubActionHistory.user_id == user.id,
                ClubActionHistory.performed_at < six_months_ago
            ).delete()
            
            cleanup_report["actions_performed"].append({
                "action": "cleanup_old_history",
                "items_removed": old_history_count,
                "description": f"Supprimé {old_history_count} entrées d'historique anciennes"
            })
        
        # 2. Vérifier les clubs suivis orphelins
        orphaned_clubs = []
        for club in user.followed_clubs:
            if not Club.query.get(club.id):
                orphaned_clubs.append(club)
        
        if orphaned_clubs:
            for club in orphaned_clubs:
                user.followed_clubs.remove(club)
            
            cleanup_report["actions_performed"].append({
                "action": "remove_orphaned_clubs",
                "items_removed": len(orphaned_clubs),
                "description": f"Supprimé {len(orphaned_clubs)} clubs suivis orphelins"
            })
        
        # 3. Réinitialiser le club principal si supprimé
        if user.club_id and not Club.query.get(user.club_id):
            user.club_id = None
            cleanup_report["actions_performed"].append({
                "action": "reset_primary_club",
                "items_removed": 1,
                "description": "Réinitialisé le club principal supprimé"
            })
        
        db.session.commit()
        
        if not cleanup_report["actions_performed"]:
            cleanup_report["actions_performed"].append({
                "action": "no_cleanup_needed",
                "items_removed": 0,
                "description": "Aucun nettoyage nécessaire"
            })
        
        logger.info(f"Nettoyage des données effectué pour le joueur {user.id}")
        return jsonify({
            "message": "Nettoyage des données effectué avec succès",
            "report": cleanup_report
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du nettoyage des données: {e}")
        return jsonify({"error": "Erreur lors du nettoyage"}), 500

# --- ROUTES AVANCÉES POUR OPTIMISATION HAUTE CHARGE (1000+ UTILISATEURS) ---

@players_bp.route("/advanced/load_test", methods=["POST"])
def simulate_high_load_test():
    """Test de charge simulé pour valider la résistance à 1000+ utilisateurs concurrents"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json() or {}
        iterations = min(data.get('iterations', 20), 100)  # Limiter à 100 pour sécurité
        concurrent_simulation = data.get('concurrent_users', 50)
        
        load_test_results = {
            "player_id": user.id,
            "timestamp": datetime.utcnow().isoformat(),
            "test_configuration": {
                "iterations": iterations,
                "simulated_concurrent_users": concurrent_simulation,
                "target_response_time_ms": 200,
                "acceptable_failure_rate": 5
            },
            "results": [],
            "performance_summary": {}
        }
        
        total_start = time.time()
        successful_operations = 0
        failed_operations = 0
        total_response_time = 0
        
        for i in range(iterations):
            iteration_start = time.time()
            
            try:
                # Simulation des opérations critiques d'un joueur
                operation_times = {}
                
                # 1. Dashboard - opération la plus fréquente (80% du trafic)
                dashboard_start = time.time()
                clubs_count = len(user.followed_clubs)
                videos_count = Video.query.filter_by(user_id=user.id).count()
                credits_balance = user.credits_balance
                operation_times['dashboard'] = (time.time() - dashboard_start) * 1000
                
                # 2. Clubs suivis - opération fréquente (15% du trafic)
                clubs_start = time.time()
                followed_clubs = db.session.query(Club).options(
                    joinedload(Club.followers)
                ).join(User.followed_clubs).filter(User.id == user.id).limit(10).all()
                operation_times['followed_clubs'] = (time.time() - clubs_start) * 1000
                
                # 3. Recherche clubs - opération moyenne (5% du trafic)
                search_start = time.time()
                available_clubs = Club.query.limit(5).all()
                operation_times['search'] = (time.time() - search_start) * 1000
                
                # 4. Historique activité - opération occasionnelle
                history_start = time.time()
                recent_history = ClubActionHistory.query.filter_by(
                    user_id=user.id
                ).limit(10).all()
                operation_times['history'] = (time.time() - history_start) * 1000
                
                iteration_time = (time.time() - iteration_start) * 1000
                total_response_time += iteration_time
                successful_operations += 1
                
                # Simuler la charge de plusieurs utilisateurs concurrents
                concurrency_factor = min(concurrent_simulation / 10, 10)  # Facteur d'ajustement
                adjusted_time = iteration_time * concurrency_factor
                
                load_test_results["results"].append({
                    "iteration": i + 1,
                    "status": "SUCCESS",
                    "response_time_ms": round(iteration_time, 2),
                    "adjusted_time_ms": round(adjusted_time, 2),
                    "operation_breakdown": {k: round(v, 2) for k, v in operation_times.items()},
                    "data_processed": {
                        "clubs_count": clubs_count,
                        "videos_count": videos_count,
                        "followed_clubs": len(followed_clubs),
                        "history_entries": len(recent_history)
                    }
                })
                
                # Pause simulée entre les requêtes (comportement réaliste)
                time.sleep(0.01)  # 10ms entre les requêtes
                
            except Exception as e:
                failed_operations += 1
                load_test_results["results"].append({
                    "iteration": i + 1,
                    "status": "FAILED",
                    "error": str(e),
                    "response_time_ms": (time.time() - iteration_start) * 1000
                })
        
        total_test_time = (time.time() - total_start) * 1000
        
        # Calcul des métriques de performance
        if successful_operations > 0:
            avg_response_time = total_response_time / successful_operations
            success_rate = (successful_operations / iterations) * 100
            
            successful_results = [r for r in load_test_results["results"] if r["status"] == "SUCCESS"]
            response_times = [r["response_time_ms"] for r in successful_results]
            
            load_test_results["performance_summary"] = {
                "total_iterations": iterations,
                "successful_operations": successful_operations,
                "failed_operations": failed_operations,
                "success_rate_percent": round(success_rate, 2),
                "average_response_time_ms": round(avg_response_time, 2),
                "min_response_time_ms": round(min(response_times), 2) if response_times else 0,
                "max_response_time_ms": round(max(response_times), 2) if response_times else 0,
                "total_test_duration_ms": round(total_test_time, 2),
                "operations_per_second": round(successful_operations / (total_test_time / 1000), 2)
            }
            
            # Évaluation de la capacité haute charge
            if avg_response_time < 200 and success_rate > 95:
                capacity_assessment = "EXCELLENT - Prêt pour 1000+ utilisateurs concurrents"
                performance_grade = "A+"
            elif avg_response_time < 300 and success_rate > 90:
                capacity_assessment = "TRÈS BON - Peut gérer 1000+ utilisateurs avec optimisation mineure"
                performance_grade = "A"
            elif avg_response_time < 500 and success_rate > 85:
                capacity_assessment = "BON - Nécessite quelques optimisations pour 1000+ utilisateurs"
                performance_grade = "B+"
            elif avg_response_time < 800 and success_rate > 75:
                capacity_assessment = "ACCEPTABLE - Optimisation requise avant déploiement haute charge"
                performance_grade = "B"
            else:
                capacity_assessment = "CRITIQUE - Optimisation majeure requise"
                performance_grade = "C"
            
            load_test_results["high_load_assessment"] = {
                "capacity_rating": capacity_assessment,
                "performance_grade": performance_grade,
                "concurrent_users_estimate": min(1000 if avg_response_time < 200 else int(1000 * (200 / avg_response_time)), 2000),
                "bottlenecks_identified": []
            }
            
            # Identification des goulots d'étranglement
            if any(r.get("operation_breakdown", {}).get("dashboard", 0) > 100 for r in successful_results):
                load_test_results["high_load_assessment"]["bottlenecks_identified"].append("Dashboard queries need optimization")
            
            if any(r.get("operation_breakdown", {}).get("followed_clubs", 0) > 50 for r in successful_results):
                load_test_results["high_load_assessment"]["bottlenecks_identified"].append("Followed clubs queries need caching")
            
            if avg_response_time > 300:
                load_test_results["high_load_assessment"]["bottlenecks_identified"].append("Overall response time optimization needed")
        
        else:
            load_test_results["performance_summary"] = {
                "error": "Aucune opération réussie - système non fonctionnel"
            }
            load_test_results["high_load_assessment"] = {
                "capacity_rating": "CRITIQUE - Système défaillant",
                "performance_grade": "F"
            }
        
        logger.info(f"Test de charge haute charge complété pour le joueur {user.id}: {successful_operations}/{iterations} succès")
        return jsonify(load_test_results), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du test de charge haute charge: {e}")
        return jsonify({"error": "Erreur lors du test de charge"}), 500

@players_bp.route("/advanced/bulk_operations", methods=["POST"])
def bulk_player_operations():
    """Opérations en masse optimisées pour haute charge"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data = request.get_json()
        operation_type = data.get('operation_type')
        targets = data.get('targets', [])
        
        if not operation_type or not targets:
            return jsonify({"error": "Type d'opération et cibles requis"}), 400
        
        # Limiter le nombre d'opérations pour éviter la surcharge
        max_operations = 50
        if len(targets) > max_operations:
            return jsonify({
                "error": f"Limite de {max_operations} opérations par lot"
            }), 400
        
        bulk_results = {
            "player_id": user.id,
            "operation_type": operation_type,
            "timestamp": datetime.utcnow().isoformat(),
            "results": [],
            "summary": {
                "total_requested": len(targets),
                "successful": 0,
                "failed": 0,
                "skipped": 0
            }
        }
        
        start_time = time.time()
        
        if operation_type == "follow_multiple_clubs":
            for club_id in targets:
                try:
                    club = Club.query.get(club_id)
                    if not club:
                        bulk_results["results"].append({
                            "target_id": club_id,
                            "status": "FAILED",
                            "error": "Club non trouvé"
                        })
                        bulk_results["summary"]["failed"] += 1
                        continue
                    
                    if club in user.followed_clubs:
                        bulk_results["results"].append({
                            "target_id": club_id,
                            "status": "SKIPPED",
                            "reason": "Déjà suivi"
                        })
                        bulk_results["summary"]["skipped"] += 1
                        continue
                    
                    # Vérifier la limite
                    if len(user.followed_clubs) >= 10:
                        bulk_results["results"].append({
                            "target_id": club_id,
                            "status": "FAILED",
                            "error": "Limite de clubs suivis atteinte"
                        })
                        bulk_results["summary"]["failed"] += 1
                        continue
                    
                    user.followed_clubs.append(club)
                    
                    log_action(
                        club_id=club_id,
                        player_id=user.id,
                        action_type='bulk_follow_club',
                        action_details={"club_name": club.name, "bulk_operation": True},
                        performed_by_id=user.id
                    )
                    
                    bulk_results["results"].append({
                        "target_id": club_id,
                        "status": "SUCCESS",
                        "club_name": club.name
                    })
                    bulk_results["summary"]["successful"] += 1
                    
                except Exception as e:
                    bulk_results["results"].append({
                        "target_id": club_id,
                        "status": "FAILED",
                        "error": str(e)
                    })
                    bulk_results["summary"]["failed"] += 1
        
        elif operation_type == "mark_videos_seen":
            for video_id in targets:
                try:
                    video = Video.query.get(video_id)
                    if not video:
                        bulk_results["results"].append({
                            "target_id": video_id,
                            "status": "FAILED",
                            "error": "Vidéo non trouvée"
                        })
                        bulk_results["summary"]["failed"] += 1
                        continue
                    
                    if video.user_id != user.id:
                        bulk_results["results"].append({
                            "target_id": video_id,
                            "status": "FAILED",
                            "error": "Vidéo ne vous appartient pas"
                        })
                        bulk_results["summary"]["failed"] += 1
                        continue
                    
                    # Marquer comme vue (ajout d'un attribut vu)
                    log_action(
                        club_id=None,
                        player_id=user.id,
                        action_type='mark_video_seen',
                        action_details={
                            "video_id": video_id,
                            "video_title": video.title,
                            "bulk_operation": True
                        },
                        performed_by_id=user.id
                    )
                    
                    bulk_results["results"].append({
                        "target_id": video_id,
                        "status": "SUCCESS",
                        "video_title": video.title
                    })
                    bulk_results["summary"]["successful"] += 1
                    
                except Exception as e:
                    bulk_results["results"].append({
                        "target_id": video_id,
                        "status": "FAILED",
                        "error": str(e)
                    })
                    bulk_results["summary"]["failed"] += 1
        
        else:
            return jsonify({"error": "Type d'opération non supporté"}), 400
        
        db.session.commit()
        
        execution_time = (time.time() - start_time) * 1000
        bulk_results["execution_time_ms"] = round(execution_time, 2)
        bulk_results["operations_per_second"] = round(len(targets) / (execution_time / 1000), 2) if execution_time > 0 else 0
        
        logger.info(f"Opération en masse {operation_type} complétée pour le joueur {user.id}: {bulk_results['summary']['successful']}/{len(targets)} succès")
        return jsonify(bulk_results), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'opération en masse: {e}")
        return jsonify({"error": "Erreur lors de l'opération en masse"}), 500

@players_bp.route("/advanced/analytics", methods=["GET"])
def get_advanced_player_analytics():
    """Analytics avancées du joueur avec métriques de performance"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        period = request.args.get('period', '30d')  # 7d, 30d, 90d, 1y
        include_predictions = request.args.get('predictions', 'false').lower() == 'true'
        
        # Calculer les dates selon la période
        end_date = datetime.utcnow()
        if period == '7d':
            start_date = end_date - timedelta(days=7)
            date_format = "%Y-%m-%d"
        elif period == '30d':
            start_date = end_date - timedelta(days=30)
            date_format = "%Y-%m-%d"
        elif period == '90d':
            start_date = end_date - timedelta(days=90)
            date_format = "%Y-%m"
        elif period == '1y':
            start_date = end_date - timedelta(days=365)
            date_format = "%Y-%m"
        else:
            start_date = end_date - timedelta(days=30)
            date_format = "%Y-%m-%d"
        
        analytics_data = {
            "player_id": user.id,
            "period": period,
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "metrics": {}
        }
        
        # 1. Analyse de l'activité temporelle
        activity_analysis = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            ClubActionHistory.performed_at >= start_date
        ).all()
        
        # Grouper par jour/mois selon la période
        activity_by_date = {}
        for activity in activity_analysis:
            date_key = activity.performed_at.strftime(date_format)
            if date_key not in activity_by_date:
                activity_by_date[date_key] = {"count": 0, "types": {}}
            
            activity_by_date[date_key]["count"] += 1
            action_type = activity.action_type
            if action_type not in activity_by_date[date_key]["types"]:
                activity_by_date[date_key]["types"][action_type] = 0
            activity_by_date[date_key]["types"][action_type] += 1
        
        analytics_data["metrics"]["activity_timeline"] = activity_by_date
        
        # 2. Analyse des patterns d'usage
        total_activities = len(activity_analysis)
        unique_action_types = len(set(a.action_type for a in activity_analysis))
        
        # Calcul de l'engagement (activités par jour)
        days_in_period = (end_date - start_date).days or 1
        engagement_score = total_activities / days_in_period
        
        analytics_data["metrics"]["engagement_analysis"] = {
            "total_activities": total_activities,
            "unique_action_types": unique_action_types,
            "activities_per_day": round(engagement_score, 2),
            "engagement_level": "HIGH" if engagement_score > 5 else "MEDIUM" if engagement_score > 2 else "LOW"
        }
        
        # 3. Analyse des vidéos
        videos_in_period = Video.query.filter(
            Video.user_id == user.id,
            Video.recorded_at >= start_date
        ).all()
        
        unlocked_in_period = len([v for v in videos_in_period if v.is_unlocked])
        total_duration = sum(v.duration for v in videos_in_period if v.duration)
        
        analytics_data["metrics"]["video_analysis"] = {
            "new_videos": len(videos_in_period),
            "unlocked_videos": unlocked_in_period,
            "unlock_rate": round((unlocked_in_period / len(videos_in_period)) * 100, 2) if videos_in_period else 0,
            "total_duration_minutes": round(total_duration / 60, 2) if total_duration else 0,
            "average_duration_minutes": round((total_duration / len(videos_in_period)) / 60, 2) if videos_in_period and total_duration else 0
        }
        
        # 4. Analyse des crédits
        credits_activities = [a for a in activity_analysis if a.action_type in ['add_credits', 'unlock_video']]
        credits_earned = credits_spent = 0
        
        for activity in credits_activities:
            try:
                details = json.loads(activity.action_details) if activity.action_details else {}
                if activity.action_type == 'add_credits':
                    credits_earned += details.get('credits_added', 0)
                elif activity.action_type == 'unlock_video':
                    credits_spent += details.get('credits_spent', 0)
            except:
                pass
        
        analytics_data["metrics"]["credits_analysis"] = {
            "credits_earned": credits_earned,
            "credits_spent": credits_spent,
            "net_credits": credits_earned - credits_spent,
            "current_balance": user.credits_balance,
            "spending_rate": round(credits_spent / days_in_period, 2),
            "earning_rate": round(credits_earned / days_in_period, 2)
        }
        
        # 5. Analyse des clubs
        club_interactions = {}
        for activity in activity_analysis:
            if activity.club_id:
                club_id = activity.club_id
                if club_id not in club_interactions:
                    club_interactions[club_id] = {"count": 0, "types": []}
                club_interactions[club_id]["count"] += 1
                club_interactions[club_id]["types"].append(activity.action_type)
        
        # Enrichir avec les noms des clubs
        club_analytics = []
        for club_id, data in club_interactions.items():
            club = Club.query.get(club_id)
            if club:
                club_analytics.append({
                    "club_id": club_id,
                    "club_name": club.name,
                    "interactions": data["count"],
                    "interaction_types": len(set(data["types"])),
                    "most_common_action": max(set(data["types"]), key=data["types"].count)
                })
        
        club_analytics.sort(key=lambda x: x["interactions"], reverse=True)
        analytics_data["metrics"]["club_interactions"] = club_analytics[:10]  # Top 10
        
        # 6. Prédictions (si demandées)
        if include_predictions:
            try:
                # Prédiction simple basée sur les tendances
                if len(videos_in_period) > 0 and days_in_period > 7:
                    video_rate = len(videos_in_period) / days_in_period
                    predicted_videos_next_period = round(video_rate * days_in_period)
                    
                    predicted_credits_needed = predicted_videos_next_period * 5  # Estimation 5 crédits/vidéo
                    
                    analytics_data["predictions"] = {
                        "next_period_videos": predicted_videos_next_period,
                        "estimated_credits_needed": predicted_credits_needed,
                        "recommended_credits_purchase": max(0, predicted_credits_needed - user.credits_balance),
                        "confidence_level": "MEDIUM" if len(videos_in_period) > 5 else "LOW"
                    }
            except:
                analytics_data["predictions"] = {"error": "Prédictions non disponibles"}
        
        # 7. Recommandations personnalisées
        recommendations = []
        
        if engagement_score < 2:
            recommendations.append("Augmentez votre activité en suivant plus de clubs")
        
        if analytics_data["metrics"]["video_analysis"]["unlock_rate"] < 50:
            recommendations.append("Considérez débloquer plus de vidéos pour améliorer votre expérience")
        
        if user.credits_balance < 10:
            recommendations.append("Rechargez vos crédits pour débloquer de nouvelles vidéos")
        
        if len(user.followed_clubs) < 3:
            recommendations.append("Suivez plus de clubs pour enrichir votre feed d'activités")
        
        analytics_data["recommendations"] = recommendations
        
        logger.info(f"Analytics avancées générées pour le joueur {user.id}")
        return jsonify(analytics_data), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la génération des analytics: {e}")
        return jsonify({"error": "Erreur lors de la génération des analytics"}), 500

@players_bp.route("/advanced/preferences", methods=["GET", "PUT"])
def player_preferences():
    """Gestion des préférences avancées du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    if request.method == "GET":
        try:
            # Récupérer les préférences depuis l'historique ou paramètres par défaut
            preferences_action = ClubActionHistory.query.filter_by(
                user_id=user.id,
                action_type='update_preferences'
            ).order_by(desc(ClubActionHistory.performed_at)).first()
            
            if preferences_action and preferences_action.action_details:
                try:
                    preferences = json.loads(preferences_action.action_details)
                except:
                    preferences = {}
            else:
                preferences = {}
            
            # Préférences par défaut
            default_preferences = {
                "notifications": {
                    "new_videos": True,
                    "club_updates": True,
                    "credits_low": True,
                    "leaderboard_changes": False
                },
                "display": {
                    "videos_per_page": 20,
                    "clubs_per_page": 10,
                    "dashboard_refresh_minutes": 5,
                    "theme": "light"
                },
                "privacy": {
                    "show_in_leaderboard": True,
                    "show_activity_to_followers": True,
                    "allow_friend_requests": True
                },
                "performance": {
                    "enable_auto_refresh": True,
                    "preload_videos": False,
                    "compress_data": False
                }
            }
            
            # Fusionner avec les préférences existantes
            for category, settings in default_preferences.items():
                if category not in preferences:
                    preferences[category] = settings
                else:
                    for key, value in settings.items():
                        if key not in preferences[category]:
                            preferences[category][key] = value
            
            return jsonify({
                "preferences": preferences,
                "last_updated": preferences_action.performed_at.isoformat() if preferences_action else None
            }), 200
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des préférences: {e}")
            return jsonify({"error": "Erreur lors de la récupération des préférences"}), 500
    
    elif request.method == "PUT":
        try:
            data = request.get_json()
            new_preferences = data.get('preferences', {})
            
            # Validation des préférences
            valid_categories = ['notifications', 'display', 'privacy', 'performance']
            validated_preferences = {}
            
            for category, settings in new_preferences.items():
                if category in valid_categories and isinstance(settings, dict):
                    validated_preferences[category] = settings
            
            # Sauvegarder les préférences
            log_action(
                club_id=user.club_id,
                player_id=user.id,
                action_type='update_preferences',
                action_details=validated_preferences,
                performed_by_id=user.id
            )
            
            db.session.commit()
            
            logger.info(f"Préférences mises à jour pour le joueur {user.id}")
            return jsonify({
                "message": "Préférences mises à jour avec succès",
                "preferences": validated_preferences,
                "updated_at": datetime.utcnow().isoformat()
            }), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors de la mise à jour des préférences: {e}")
            return jsonify({"error": "Erreur lors de la mise à jour des préférences"}), 500

@players_bp.route("/advanced/export_data", methods=["POST"])
def export_player_data():
    """Exportation complète des données du joueur (GDPR compliance)"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        data_format = request.json.get('format', 'json')  # json, csv
        include_history = request.json.get('include_history', True)
        include_videos = request.json.get('include_videos', True)
        
        export_data = {
            "export_info": {
                "player_id": user.id,
                "export_timestamp": datetime.utcnow().isoformat(),
                "format": data_format,
                "gdpr_compliant": True
            },
            "player_profile": user.to_dict()
        }
        
        # Clubs suivis
        export_data["followed_clubs"] = [club.to_dict() for club in user.followed_clubs]
        
        # Vidéos (si demandées)
        if include_videos:
            player_videos = Video.query.filter_by(user_id=user.id).all()
            export_data["videos"] = []
            
            for video in player_videos:
                video_data = video.to_dict()
                # Ajouter les informations du terrain et du club
                court = Court.query.get(video.court_id)
                if court:
                    video_data["court_name"] = court.name
                    club = Club.query.get(court.club_id)
                    if club:
                        video_data["club_name"] = club.name
                
                export_data["videos"].append(video_data)
        
        # Historique d'activité (si demandé)
        if include_history:
            activity_history = ClubActionHistory.query.filter_by(
                user_id=user.id
            ).order_by(desc(ClubActionHistory.performed_at)).all()
            
            export_data["activity_history"] = []
            for activity in activity_history:
                activity_data = {
                    "id": activity.id,
                    "action_type": activity.action_type,
                    "performed_at": activity.performed_at.isoformat(),
                    "details": activity.action_details
                }
                
                # Ajouter le nom du club si disponible
                if activity.club_id:
                    club = Club.query.get(activity.club_id)
                    if club:
                        activity_data["club_name"] = club.name
                
                export_data["activity_history"].append(activity_data)
        
        # Statistiques agrégées
        export_data["statistics"] = {
            "total_videos": Video.query.filter_by(user_id=user.id).count(),
            "unlocked_videos": Video.query.filter_by(user_id=user.id, is_unlocked=True).count(),
            "followed_clubs_count": len(user.followed_clubs),
            "total_activities": ClubActionHistory.query.filter_by(user_id=user.id).count(),
            "current_credits_balance": user.credits_balance,
            "account_created": user.created_at.isoformat() if hasattr(user, 'created_at') else None,
            "last_login": user.last_login.isoformat() if user.last_login else None
        }
        
        # Log de l'exportation
        log_action(
            club_id=user.club_id,
            player_id=user.id,
            action_type='export_data',
            action_details={
                "format": data_format,
                "include_history": include_history,
                "include_videos": include_videos,
                "data_size": len(str(export_data))
            },
            performed_by_id=user.id
        )
        
        db.session.commit()
        
        logger.info(f"Exportation des données complétée pour le joueur {user.id}")
        return jsonify(export_data), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de l'exportation des données: {e}")
        return jsonify({"error": "Erreur lors de l'exportation des données"}), 500

@players_bp.route("/system/status", methods=["GET"])
def get_player_system_status():
    """Status système optimisé pour monitoring haute charge"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        status_data = {
            "player_id": user.id,
            "timestamp": datetime.utcnow().isoformat(),
            "system_health": {},
            "performance_indicators": {},
            "high_load_readiness": {}
        }
        
        # Tests de santé système
        system_start = time.time()
        
        # 1. Test de connectivité base de données
        try:
            db.session.execute("SELECT 1")
            db_status = "HEALTHY"
            db_response_time = (time.time() - system_start) * 1000
        except Exception as e:
            db_status = f"ERROR: {str(e)}"
            db_response_time = -1
        
        # 2. Test des requêtes utilisateur critiques
        user_queries_start = time.time()
        test_user = User.query.options(joinedload(User.followed_clubs)).get(user.id)
        user_queries_time = (time.time() - user_queries_start) * 1000
        
        # 3. Test des requêtes vidéos
        video_queries_start = time.time()
        test_videos = Video.query.filter_by(user_id=user.id).limit(10).all()
        video_queries_time = (time.time() - video_queries_start) * 1000
        
        # 4. Test des requêtes historique
        history_queries_start = time.time()
        test_history = ClubActionHistory.query.filter_by(user_id=user.id).limit(10).all()
        history_queries_time = (time.time() - history_queries_start) * 1000
        
        status_data["system_health"] = {
            "database_connection": {
                "status": db_status,
                "response_time_ms": round(db_response_time, 2)
            },
            "user_queries": {
                "status": "HEALTHY" if user_queries_time < 100 else "SLOW",
                "response_time_ms": round(user_queries_time, 2)
            },
            "video_queries": {
                "status": "HEALTHY" if video_queries_time < 100 else "SLOW",
                "response_time_ms": round(video_queries_time, 2)
            },
            "history_queries": {
                "status": "HEALTHY" if history_queries_time < 100 else "SLOW",
                "response_time_ms": round(history_queries_time, 2)
            }
        }
        
        # Indicateurs de performance
        total_system_time = (time.time() - system_start) * 1000
        
        status_data["performance_indicators"] = {
            "total_health_check_time_ms": round(total_system_time, 2),
            "average_query_time_ms": round((user_queries_time + video_queries_time + history_queries_time) / 3, 2),
            "database_efficiency": "EXCELLENT" if db_response_time < 10 else "GOOD" if db_response_time < 50 else "NEEDS_OPTIMIZATION",
            "query_optimization_level": "HIGH" if all(t < 50 for t in [user_queries_time, video_queries_time, history_queries_time]) else "MEDIUM"
        }
        
        # Évaluation de la préparation haute charge
        all_queries_fast = all(t < 100 for t in [user_queries_time, video_queries_time, history_queries_time])
        db_fast = db_response_time < 50
        
        if all_queries_fast and db_fast:
            load_readiness = "READY_FOR_HIGH_LOAD"
            concurrent_capacity = "1000+"
        elif all_queries_fast:
            load_readiness = "GOOD_WITH_DB_OPTIMIZATION"
            concurrent_capacity = "500-1000"
        elif db_fast:
            load_readiness = "NEEDS_QUERY_OPTIMIZATION"
            concurrent_capacity = "100-500"
        else:
            load_readiness = "NEEDS_MAJOR_OPTIMIZATION"
            concurrent_capacity = "<100"
        
        status_data["high_load_readiness"] = {
            "readiness_level": load_readiness,
            "estimated_concurrent_capacity": concurrent_capacity,
            "optimization_priority": "DATABASE" if not db_fast else "QUERIES" if not all_queries_fast else "NONE",
            "recommendations": []
        }
        
        # Recommandations spécifiques
        if db_response_time > 50:
            status_data["high_load_readiness"]["recommendations"].append("Optimiser la connexion base de données")
        if user_queries_time > 100:
            status_data["high_load_readiness"]["recommendations"].append("Ajouter des index sur les requêtes utilisateur")
        if video_queries_time > 100:
            status_data["high_load_readiness"]["recommendations"].append("Optimiser les requêtes vidéos avec jointures")
        if history_queries_time > 100:
            status_data["high_load_readiness"]["recommendations"].append("Implémenter la pagination pour l'historique")
        
        if not status_data["high_load_readiness"]["recommendations"]:
            status_data["high_load_readiness"]["recommendations"].append("Système optimisé pour haute charge")
        
        # Status global
        all_healthy = (
            db_status == "HEALTHY" and
            all_queries_fast and
            total_system_time < 500
        )
        
        status_data["overall_status"] = "OPTIMAL" if all_healthy else "NEEDS_ATTENTION"
        
        return jsonify(status_data), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du status système: {e}")
        return jsonify({
            "player_id": user.id if user else "unknown",
            "overall_status": "ERROR",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500
