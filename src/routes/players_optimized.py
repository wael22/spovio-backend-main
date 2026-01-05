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
from ..models.user import User, Club, Court, Video, ClubActionHistory

logger = logging.getLogger(__name__)

players_bp = Blueprint('players', __name__, url_prefix='/api/players')

# --- FONCTIONS UTILITAIRES OPTIMISÉES ---

def require_player_access():
    """Vérification d'accès avec optimisations pour haute charge"""
    try:
        if 'user_id' not in session:
            logger.warning("Tentative d'accès sans session")
            return None
        
        # Optimisation: utiliser joinedload pour éviter N+1 queries
        user = db.session.query(User).options(
            joinedload(User.followed_clubs),
            joinedload(User.videos)
        ).filter_by(id=session['user_id']).first()
        
        if not user or user.role != 'PLAYER':
            logger.warning(f"Accès refusé pour l'utilisateur {session.get('user_id')}")
            return None
        
        # Mettre à jour la dernière connexion pour les statistiques
        user.last_login = datetime.utcnow()
        db.session.commit()
        
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

@players_bp.route("/clubs/available", methods=["GET"])
def get_available_clubs():
    """Récupérer les clubs disponibles avec optimisations pour haute charge"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        # Optimisation: requête unique avec jointure pour éviter N+1
        clubs_query = db.session.query(Club).options(
            joinedload(Club.followers),
            joinedload(Club.courts)
        ).all()
        
        followed_ids = {c.id for c in user.followed_clubs}
        
        clubs_data = []
        for club in clubs_query:
            club_dict = club.to_dict()
            club_dict["is_followed"] = club.id in followed_ids
            club_dict["followers_count"] = len(club.followers.all()) if hasattr(club, 'followers') else 0
            club_dict["courts_count"] = len(club.courts) if hasattr(club, 'courts') else 0
            clubs_data.append(club_dict)
        
        # Trier par popularité (nombre de followers)
        clubs_data.sort(key=lambda x: x.get("followers_count", 0), reverse=True)
        
        logger.info(f"Clubs disponibles récupérés pour le joueur {user.id}")
        return jsonify({
            "clubs": clubs_data,
            "total_clubs": len(clubs_data),
            "followed_count": len(followed_ids)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des clubs disponibles: {e}")
        return jsonify({"error": "Erreur lors de la récupération des clubs"}), 500

@players_bp.route("/clubs/<int:club_id>/follow", methods=["POST"])
def follow_club(club_id):
    """Suivre un club avec optimisations et validations robustes"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        club = Club.query.get_or_404(club_id)
        
        # Vérification optimisée
        if club in user.followed_clubs:
            return jsonify({"error": "Vous suivez déjà ce club"}), 409
        
        # Limite de clubs suivis pour éviter la surcharge
        max_followed_clubs = 10  # Configurable
        if len(user.followed_clubs) >= max_followed_clubs:
            return jsonify({
                "error": f"Limite de {max_followed_clubs} clubs suivis atteinte"
            }), 400
        
        # Ajouter le suivi
        user.followed_clubs.append(club)
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
            "followed_clubs_count": len(user.followed_clubs)
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
        
        if club not in user.followed_clubs:
            return jsonify({"error": "Vous ne suivez pas ce club"}), 409
        
        # Retirer le suivi
        user.followed_clubs.remove(club)
        
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
            "followed_clubs_count": len(user.followed_clubs)
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
        
        for club in user.followed_clubs:
            club_dict = club.to_dict()
            
            # Ajouter des statistiques enrichies
            club_dict["courts_count"] = len(club.courts) if hasattr(club, 'courts') else 0
            club_dict["followers_count"] = len(club.followers.all()) if hasattr(club, 'followers') else 0
            club_dict["is_primary_club"] = (user.club_id == club.id)
            
            # Dernière activité du joueur dans ce club
            last_activity = ClubActionHistory.query.filter_by(
                club_id=club.id,
                user_id=user.id
            ).order_by(desc(ClubActionHistory.performed_at)).first()
            
            if last_activity:
                club_dict["last_activity"] = {
                    "action_type": last_activity.action_type,
                    "performed_at": last_activity.performed_at.isoformat()
                }
            
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
        followed_clubs_count = len(user.followed_clubs)
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
            followed_ids = {c.id for c in user.followed_clubs}
            
            for club in all_clubs:
                if club.id not in followed_ids:
                    followers_count = len(club.followers.all()) if hasattr(club, 'followers') else 0
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
                ClubActionHistory.action_type == 'add_credits',
                ClubActionHistory.action_type == 'unlock_video',
                ClubActionHistory.action_type == 'purchase'
            )
        ).order_by(desc(ClubActionHistory.performed_at)).offset(offset).limit(limit).all()
        
        total_count = ClubActionHistory.query.filter(
            ClubActionHistory.user_id == user.id,
            or_(
                ClubActionHistory.action_type == 'add_credits',
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
                ClubActionHistory.action_type == 'add_credits',
                ClubActionHistory.action_type == 'unlock_video'
            )
        ).all()
        
        for action in credits_actions:
            try:
                if action.action_details:
                    details = json.loads(action.action_details)
                    
                    if action.action_type == 'add_credits':
                        credits_added = details.get('credits_added', 0)
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
