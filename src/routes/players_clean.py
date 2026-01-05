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
        db.session.flush()
        
        logger.info(f"Action loggée: {action_type} pour le joueur {player_id}")
        
    except Exception as e:
        logger.error(f"Erreur lors du logging de l'action {action_type}: {e}")

# --- ROUTES DE GESTION DES CLUBS ---

@players_bp.route("/clubs/available", methods=["GET"])
def get_available_clubs():
    """Récupérer les clubs disponibles avec optimisations pour haute charge"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
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
        
        if club in user.followed_clubs:
            return jsonify({"error": "Vous suivez déjà ce club"}), 409
        
        max_followed_clubs = 10
        if len(user.followed_clubs) >= max_followed_clubs:
            return jsonify({
                "error": f"Limite de {max_followed_clubs} clubs suivis atteinte"
            }), 400
        
        user.followed_clubs.append(club)
        user.club_id = club.id
        
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
        
        user.followed_clubs.remove(club)
        
        # CORRECTION CRUCIALE: Réinitialiser l'affiliation principale
        if user.club_id == club_id:
            user.club_id = None
        
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
            club_dict["courts_count"] = len(club.courts) if hasattr(club, 'courts') else 0
            club_dict["followers_count"] = len(club.followers.all()) if hasattr(club, 'followers') else 0
            club_dict["is_primary_club"] = (user.club_id == club.id)
            
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
        
        player_info = user.to_dict()
        
        followed_clubs_count = len(user.followed_clubs)
        primary_club = None
        if user.club_id:
            primary_club = Club.query.get(user.club_id)
        
        player_videos = Video.query.filter_by(user_id=user.id).all()
        videos_stats = {
            "total_videos": len(player_videos),
            "unlocked_videos": len([v for v in player_videos if v.is_unlocked]),
            "total_duration": sum(v.duration for v in player_videos if v.duration),
            "recent_videos": [v.to_dict() for v in player_videos[-5:]]
        }
        
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
        
        credits_stats = {
            "current_balance": user.credits_balance,
            "credits_earned_this_month": 0,
            "credits_spent_this_month": 0
        }
        
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
        
        recommended_clubs = []
        try:
            all_clubs = Club.query.all()
            followed_ids = {c.id for c in user.followed_clubs}
            
            for club in all_clubs:
                if club.id not in followed_ids:
                    followers_count = len(club.followers.all()) if hasattr(club, 'followers') else 0
                    courts_count = len(club.courts) if hasattr(club, 'courts') else 0
                    
                    if followers_count > 0 or courts_count > 0:
                        club_dict = club.to_dict()
                        club_dict["followers_count"] = followers_count
                        club_dict["courts_count"] = courts_count
                        recommended_clubs.append(club_dict)
            
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

# --- AUTRES ROUTES OPTIMISÉES ---

@players_bp.route("/videos", methods=["GET"])
def get_player_videos():
    """Récupérer toutes les vidéos du joueur avec filtres optimisés"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        club_id = request.args.get('club_id', type=int)
        is_unlocked = request.args.get('is_unlocked')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        query = Video.query.filter_by(user_id=user.id)
        
        if club_id:
            query = query.join(Court).filter(Court.club_id == club_id)
        
        if is_unlocked is not None:
            query = query.filter(Video.is_unlocked == (is_unlocked.lower() == 'true'))
        
        videos = query.order_by(desc(Video.recorded_at)).offset(offset).limit(limit).all()
        total_count = query.count()
        
        videos_data = []
        for video in videos:
            video_dict = video.to_dict()
            
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
        logger.error(f"Erreur lors de la récupération des vidéos: {e}")
        return jsonify({"error": "Erreur lors de la récupération des vidéos"}), 500

@players_bp.route("/videos/<int:video_id>/unlock", methods=["POST"])
def unlock_video(video_id):
    """Débloquer une vidéo avec des crédits"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        video = Video.query.get_or_404(video_id)
        
        if video.user_id != user.id:
            return jsonify({"error": "Cette vidéo ne vous appartient pas"}), 403
        
        if video.is_unlocked:
            return jsonify({"error": "Cette vidéo est déjà débloquée"}), 400
        
        if user.credits_balance < video.credits_cost:
            return jsonify({
                "error": "Crédits insuffisants",
                "required": video.credits_cost,
                "available": user.credits_balance
            }), 400
        
        user.credits_balance -= video.credits_cost
        video.is_unlocked = True
        
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

@players_bp.route("/profile", methods=["GET"])
def get_player_profile():
    """Récupérer le profil complet du joueur"""
    user = require_player_access()
    if not user: 
        return jsonify({"error": "Accès non autorisé"}), 403
    
    try:
        profile_data = user.to_dict()
        
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
        
        if 'name' in data and data['name'].strip():
            user.name = data['name'].strip()
        
        if 'phone_number' in data:
            user.phone_number = data['phone_number']
        
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

# --- ROUTES POUR HAUTE CHARGE ---

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
        
        # Test clubs suivis
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
        
        # Test vidéos
        videos_start = time.time()
        videos = Video.query.filter_by(user_id=user.id).limit(50).all()
        videos_time = time.time() - videos_start
        
        metrics["performance_metrics"]["videos_query"] = {
            "execution_time_ms": round(videos_time * 1000, 2),
            "videos_count": len(videos),
            "status": "OK" if videos_time < 0.1 else "WARNING"
        }
        
        # Test historique
        history_start = time.time()
        history = ClubActionHistory.query.filter_by(user_id=user.id).limit(20).all()
        history_time = time.time() - history_start
        
        metrics["performance_metrics"]["history_query"] = {
            "execution_time_ms": round(history_time * 1000, 2),
            "entries_count": len(history),
            "status": "OK" if history_time < 0.1 else "WARNING"
        }
        
        total_time = time.time() - start_time
        metrics["performance_metrics"]["total_execution"] = {
            "execution_time_ms": round(total_time * 1000, 2),
            "status": "OK" if total_time < 0.5 else "WARNING"
        }
        
        recommendations = []
        if clubs_time > 0.1:
            recommendations.append("Optimiser les requêtes de clubs suivis")
        if videos_time > 0.1:
            recommendations.append("Ajouter un index sur user_id pour les vidéos")
        if history_time > 0.1:
            recommendations.append("Optimiser les requêtes d'historique")
        
        metrics["recommendations"] = recommendations
        
        return jsonify(metrics), 200
        
    except Exception as e:
        logger.error(f"Erreur lors des métriques de performance: {e}")
        return jsonify({"error": "Erreur lors du test de performance"}), 500
