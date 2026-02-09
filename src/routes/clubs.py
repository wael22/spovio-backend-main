from flask import Blueprint, request, jsonify, session
from src.models.user import db, User, Club, Court, UserRole, ClubActionHistory, Video, RecordingSession
from src.models.system_settings import SystemSettings
from src.models.notification import Notification, NotificationType
from src.routes.admin import log_club_action
from datetime import datetime, timedelta
import json
import os
import random
import logging
from werkzeug.security import generate_password_hash
from sqlalchemy.orm import joinedload

# Logger pour tracer les actions
logger = logging.getLogger(__name__)

# Définition du blueprint pour les routes des clubs
clubs_bp = Blueprint('clubs', __name__)

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

# Route pour récupérer la liste des clubs
@clubs_bp.route('/', methods=['GET'])
def get_clubs():
    clubs = Club.query.all()
    return jsonify({'clubs': [club.to_dict() for club in clubs]}), 200

# Route pour récupérer un club spécifique
@clubs_bp.route('/<int:club_id>', methods=['GET'])
def get_club(club_id):
    club = Club.query.get_or_404(club_id)
    return jsonify({'club': club.to_dict()}), 200

# Route pour suivre un club
@clubs_bp.route('/<int:club_id>/follow', methods=['POST'])
def follow_club(club_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.PLAYER:
        return jsonify({'error': 'Seuls les joueurs peuvent suivre un club'}), 403
    
    club = Club.query.get_or_404(club_id)
    if club in user.followed_clubs:
        return jsonify({'message': 'Vous suivez déjà ce club'}), 200
    
    user.followed_clubs.append(club)
    db.session.commit()
    return jsonify({'message': 'Club suivi avec succès'}), 200

# Route pour récupérer l'historique des actions du club
# Route de diagnostic pour vérifier les données d'un club spécifique
@clubs_bp.route('/diagnostic/<int:club_id>', methods=['GET'])
def diagnostic_club_data(club_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    # Permettre aux super admins et aux clubs de diagnostiquer
    if user.role not in [UserRole.CLUB, UserRole.SUPER_ADMIN]:
        return jsonify({'error': 'Accès réservé aux clubs et administrateurs'}), 403
        
    try:
        # Récupérer le club
        club = Club.query.get(club_id)
        if not club:
            return jsonify({'error': f'Club avec ID {club_id} non trouvé'}), 404
        
        print(f"\n=== DIAGNOSTIC CLUB {club.name} (ID: {club.id}) ===")
        
        # 1. Vérifier les joueurs
        players = User.query.filter_by(club_id=club.id, role=UserRole.PLAYER).all()
        players_count = len(players)
        print(f"Joueurs trouvés: {players_count}")
        players_data = []
        for player in players:
            players_data.append({
                'id': player.id,
                'name': player.name,
                'email': player.email,
                'club_id': player.club_id
            })
            print(f"  - {player.name} (ID: {player.id}, club_id: {player.club_id})")
        
        # 2. Vérifier les terrains
        courts = Court.query.filter_by(club_id=club.id).all()
        courts_count = len(courts)
        print(f"Terrains trouvés: {courts_count}")
        courts_data = []
        for court in courts:
            courts_data.append({
                'id': court.id,
                'name': court.name,
                'club_id': court.club_id,
                'qr_code': court.qr_code
            })
            print(f"  - {court.name} (ID: {court.id}, club_id: {court.club_id})")
        
        # 3. Vérifier les vidéos
        court_ids = [court.id for court in courts]
        videos = []
        videos_count = 0
        if court_ids:
            videos = Video.query.filter(Video.court_id.in_(court_ids)).all()
            videos_count = len(videos)
        
        print(f"Vidéos trouvées: {videos_count}")
        videos_data = []
        for video in videos:
            videos_data.append({
                'id': video.id,
                'title': video.title,
                'user_id': video.user_id,
                'court_id': video.court_id
            })
            print(f"  - {video.title} (ID: {video.id}, user_id: {video.user_id}, court_id: {video.court_id})")
        
        # 4. Vérifier les followers
        try:
            followers = club.followers.all()
            followers_count = len(followers)
            print(f"Followers trouvés: {followers_count}")
            followers_data = []
            for follower in followers:
                followers_data.append({
                    'id': follower.id,
                    'name': follower.name,
                    'email': follower.email,
                    'club_id': follower.club_id
                })
                print(f"  - {follower.name} (ID: {follower.id}, club_id: {follower.club_id})")
        except Exception as e:
            print(f"Erreur lors de la vérification des followers: {e}")
            followers_count = 0
            followers_data = []
        
        # 5. Vérifier les crédits dans l'historique
        credit_entries = ClubActionHistory.query.filter_by(
            club_id=club.id,
            action_type='add_credits'
        ).all()
        
        print(f"Entrées de crédits trouvées: {len(credit_entries)}")
        credits_data = []
        total_credits = 0
        for entry in credit_entries:
            try:
                details = json.loads(entry.action_details)
                credits_added = details.get('credits_added', 0)
                total_credits += int(credits_added)
                credits_data.append({
                    'id': entry.id,
                    'user_id': entry.user_id,
                    'credits_added': credits_added,
                    'performed_at': entry.performed_at.isoformat()
                })
                print(f"  - Entrée {entry.id}: {credits_added} crédits pour user {entry.user_id}")
            except Exception as e:
                print(f"  - Erreur parsing entrée {entry.id}: {e}")
        
        print(f"Total crédits calculés: {total_credits}")
        
        # 6. Vérifier l'historique global
        all_history = ClubActionHistory.query.filter_by(club_id=club.id).all()
        print(f"Entrées d'historique total: {len(all_history)}")
        
        history_types = {}
        for entry in all_history:
            action_type = entry.action_type
            history_types[action_type] = history_types.get(action_type, 0) + 1
        
        for action_type, count in history_types.items():
            print(f"  - {action_type}: {count} entrées")
        
        return jsonify({
            'club': {
                'id': club.id,
                'name': club.name,
                'address': club.address,
                'email': club.email
            },
            'diagnostics': {
                'players': {
                    'count': players_count,
                    'data': players_data
                },
                'courts': {
                    'count': courts_count,
                    'data': courts_data
                },
                'videos': {
                    'count': videos_count,
                    'data': videos_data
                },
                'followers': {
                    'count': followers_count,
                    'data': followers_data
                },
                'credits': {
                    'total': total_credits,
                    'entries_count': len(credit_entries),
                    'data': credits_data
                },
                'history_summary': history_types
            }
        }), 200
        
    except Exception as e:
        print(f"Erreur lors du diagnostic: {e}")
        return jsonify({'error': f'Erreur lors du diagnostic: {str(e)}'}), 500

# Route pour récupérer les informations du tableau de bord du club
@clubs_bp.route('/dashboard', methods=['GET'])
def get_club_dashboard():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        # Récupérer le club associé à l'utilisateur
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        print(f"Récupération du tableau de bord pour le club ID: {club.id}, nom: {club.name}")
        
        # 1. Compter les joueurs associés au club - Méthode similaire à admin.py
        players = User.query.filter_by(club_id=club.id, role=UserRole.PLAYER).all()
        players_count = len(players)
        print(f"Nombre de joueurs: {players_count}")
        
        # Debug: afficher les joueurs trouvés
        for player in players[:3]:
            print(f"  Joueur: {player.name} (ID: {player.id}, club_id: {player.club_id})")
        
        # 2. Compter les terrains du club et vérifier leur statut d'occupation
        courts = Court.query.filter_by(club_id=club.id).all()
        courts_count = len(courts)
        print(f"Nombre de terrains: {courts_count}")
        
        # ACTIVATION: Nettoyer automatiquement les sessions expirées
        # pour libérer les terrains qui ne sont plus réellement occupés
        try:
            # Nettoyer les sessions expirées
            expired_sessions = RecordingSession.query.filter_by(status='active').all()
            cleaned_count = 0
            
            for session in expired_sessions:
                if session.is_expired():
                    session.status = 'completed'
                    
                    # 🔧 LIBÉRER LE TERRAIN (FIX CRITIQUE)
                    court = Court.query.get(session.court_id)
                    if court:
                        court.is_recording = False
                        print(f"🔓 Terrain {court.name} (ID:{court.id}) libéré")
                    
                    cleaned_count += 1
                    print(f"Nettoyage session expirée {session.id} (Court {session.court_id})")
            
            if cleaned_count > 0:
                db.session.commit()
                print(f"✅ {cleaned_count} session(s) expirée(s) nettoyée(s)")
                
        except Exception as e:
            print(f"Erreur lors du nettoyage des sessions expirées: {e}")
        
        # Enrichir les informations des terrains avec le statut d'occupation
        courts_with_status = []
        for court in courts:
            court_dict = court.to_dict()
            
            # Vérifier s'il y a un enregistrement actif sur ce terrain
            active_recording = RecordingSession.query.filter_by(
                court_id=court.id,
                status='active'
            ).first()
            
            if active_recording and not active_recording.is_expired():
                court_dict.update({
                    'is_occupied': True,
                    'occupation_status': 'Occupé - Enregistrement en cours',
                    'recording_player': active_recording.user.name if active_recording.user else 'Joueur inconnu',
                    'recording_remaining': active_recording.get_remaining_minutes(),
                    'recording_total': active_recording.planned_duration
                })
            else:
                court_dict.update({
                    'is_occupied': False,
                    'occupation_status': 'Disponible',
                    'recording_player': None,
                    'recording_remaining': None,
                    'recording_total': None
                })
            
            courts_with_status.append(court_dict)
            print(f"  Terrain: {court.name} (ID: {court.id}) - {court_dict['occupation_status']}")
        
        courts = courts_with_status
        
        # 3. Compter les vidéos - Requête similaire à admin.py avec jointures explicites
        court_ids = [court_data['id'] if isinstance(court_data, dict) else court_data.id for court_data in courts]
        videos_count = 0
        
        if court_ids:
            # Utiliser une requête avec joinedload pour éviter le problème N+1
            videos = db.session.query(Video).options(joinedload(Video.owner)).join(Court, Video.court_id == Court.id).filter(
                Court.club_id == club.id
            ).all()
            videos_count = len(videos)
            
            # Debug: afficher les vidéos trouvées
            print(f"Nombre de vidéos: {videos_count}")
            for video in videos[:3]:
                player_name = video.owner.name if video.owner else 'Joueur inconnu'
                print(f"  Vidéo: {video.title} (ID: {video.id}, joueur: {player_name})")
        else:
            videos = []
            print("Aucun terrain trouvé, donc aucune vidéo")
        
        # 4. Compter les followers - Correction de la méthode
        followers_count = 0
        try:
            # Utiliser une requête directe comme dans admin.py
            followers = db.session.query(User).join(
                club.followers.property.secondary
            ).filter(
                club.followers.property.secondary.c.club_id == club.id
            ).all()
            followers_count = len(followers)
            
            print(f"Nombre de followers: {followers_count}")
            # Debug: afficher les followers trouvés
            for follower in followers[:3]:
                print(f"  Follower: {follower.name} (ID: {follower.id})")
                
        except Exception as e:
            # Fallback: utiliser la relation directe
            try:
                followers_list = club.followers.all()
                followers_count = len(followers_list)
                print(f"Nombre de followers (fallback): {followers_count}")
            except Exception as e2:
                print(f"Erreur lors du comptage des followers: {e}, fallback: {e2}")
                followers_count = 0
        
        # 5. Compter les crédits offerts - Amélioration de la méthode
        credits_given = 0
        try:
            # Récupérer toutes les entrées d'historique de type 'add_credits', 'club_add_credits' et 'admin_add_credits' pour ce club
            credit_entries = db.session.query(ClubActionHistory).filter(
                ClubActionHistory.club_id == club.id,
                ClubActionHistory.action_type.in_(['add_credits', 'club_add_credits', 'admin_add_credits'])
            ).all()
            
            print(f"Entrées de crédits trouvées: {len(credit_entries)}")
            
            # Parcourir chaque entrée pour extraire les crédits
            for entry in credit_entries:
                try:
                    if entry.action_details:
                        details = json.loads(entry.action_details)
                        credits_added = details.get('credits_added', 0)
                        if isinstance(credits_added, (int, float)):
                            credits_given += int(credits_added)
                            print(f"  Entrée {entry.id}: +{credits_added} crédits")
                        else:
                            print(f"  Entrée {entry.id}: valeur de crédits invalide: {credits_added}")
                    else:
                        print(f"  Entrée {entry.id}: pas de détails")
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                    print(f"  Erreur parsing entrée {entry.id}: {e}")
            
            print(f"Total des crédits offerts: {credits_given}")
            
        except Exception as e:
            print(f"Erreur lors du calcul des crédits: {e}")
            credits_given = 0
        
        # Statistiques finales - CORRIGER LES NOMS POUR CORRESPONDRE AU FRONTEND
        stats = {
            'total_players': players_count,      # Frontend attend 'total_players'
            'total_courts': courts_count,        # Frontend attend 'total_courts'
            'total_videos': videos_count,        # Frontend attend 'total_videos'
            'total_credits_offered': credits_given,  # Frontend attend 'total_credits_offered'
            'followers_count': followers_count,  # Pas utilisé dans le frontend actuellement
            # Garder aussi les anciens noms pour compatibilité
            'players_count': players_count,
            'courts_count': courts_count,
            'videos_count': videos_count,
            'credits_given': credits_given
        }
        
        print(f"Statistiques finales: {stats}")
        
        # Enrichir les vidéos avec le nom du joueur
        videos_enriched = []
        if videos:
            for video in videos:
                video_dict = video.to_dict()
                # Ajouter le nom du joueur
                if video.owner:
                    video_dict['player_name'] = video.owner.name
                else:
                    video_dict['player_name'] = 'Joueur inconnu'
                videos_enriched.append(video_dict)
        
        return jsonify({
            'club': club.to_dict(),
            'stats': stats,
            'players': [player.to_dict() for player in players],  # Ajouter les joueurs pour le frontend
            'courts': courts,      # Ajouter les terrains avec statut d'occupation pour le frontend
            'videos': videos_enriched,  # Vidéos enrichies avec nom du joueur
            'debug_info': {
                'user_id': user.id,
                'club_id': user.club_id,
                'role': user.role.value,
                'court_ids': court_ids
            }
        }), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération du tableau de bord: {e}")
        return jsonify({'error': 'Erreur lors de la récupération du tableau de bord'}), 500

# Route pour récupérer les informations du club
@clubs_bp.route('/info', methods=['GET'])
def get_club_info():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        return jsonify({'club': club.to_dict()}), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des informations du club: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des informations du club'}), 500

# Route pour récupérer les terrains du club
@clubs_bp.route('/courts', methods=['GET'])
def get_club_courts():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        courts = Court.query.filter_by(club_id=club.id).all()
        return jsonify({'courts': [court.to_dict() for court in courts]}), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des terrains: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des terrains'}), 500

# Route pour récupérer les joueurs du club
@clubs_bp.route('/players', methods=['GET'])
def get_club_players():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        players = User.query.filter_by(club_id=club.id).all()
        return jsonify({'players': [player.to_dict() for player in players]}), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des joueurs: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des joueurs'}), 500

# Route pour récupérer les abonnés du club
@clubs_bp.route('/followers', methods=['GET'])
def get_club_followers():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        # Récupérer les joueurs qui suivent ce club
        followers = club.followers.all()
        return jsonify({'followers': [follower.to_dict() for follower in followers]}), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des abonnés: {e}")
        return jsonify({"error": "Erreur lors de la récupération des abonnés"}), 500

@clubs_bp.route('/history', methods=['GET'])
def get_club_history():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
    
    try:
        # On définit des alias pour les tables User afin de différencier les utilisateurs dans la requête
        Player = db.aliased(User)
        Performer = db.aliased(User)
        
        # Récupération de l'historique des actions pour ce club
        history_query = (
            db.session.query(
                ClubActionHistory,
                Player.name.label('player_name'),
                Performer.name.label('performed_by_name')
            )
            .outerjoin(Player, ClubActionHistory.user_id == Player.id)
            .outerjoin(Performer, ClubActionHistory.performed_by_id == Performer.id)
            .filter(ClubActionHistory.club_id == user.club_id)
            .order_by(ClubActionHistory.performed_at.desc())
            .all()
        )
        
        # Formatage des données pour la réponse
        history_data = []
        for entry, player_name, performed_by_name in history_query:
            history_data.append({
                'id': entry.id,
                'action_type': entry.action_type,
                'action_details': entry.action_details,
                'performed_at': entry.performed_at.isoformat(),
                'player_id': entry.user_id,
                'player_name': player_name,
                'performed_by_id': entry.performed_by_id,
                'performed_by_name': performed_by_name
            })
        
        return jsonify({"history": history_data}), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération de l'historique: {e}")
        return jsonify({"error": "Erreur lors de la récupération de l'historique"}), 500

# Route pour récupérer les packages de crédits pour clubs
@clubs_bp.route('/credits/packages', methods=['GET'])
def get_club_credit_packages():
    """Récupérer les packages de crédits disponibles pour les clubs"""
    try:
        # Charger les packages depuis la base de données
        from src.models.credit_package import CreditPackage
        
        db_packages = CreditPackage.query.filter_by(
            package_type='club',
            is_active=True
        ).order_by(CreditPackage.credits.asc()).all()
        
        # Si aucun package en DB, utiliser les packages par défaut
        if not db_packages:
            packages = [
                {
                    "id": "pack_100",
                    "credits": 100,
                    "price_dt": 700,
                    "type": "basic",
                    "description": "Pour débuter",
                    "popular": False
                },
                {
                    "id": "pack_500",
                    "credits": 500,
                    "price_dt": 3000,
                    "type": "standard",
                    "description": "Le plus populaire",
                    "popular": True,
                    "original_price_dt": 3500,
                    "savings_dt": 500
                },
                {
                    "id": "pack_1000",
                    "credits": 1000,
                    "price_dt": 5500,
                    "type": "premium",
                    "description": "Meilleure offre",
                    "popular": False,
                    "original_price_dt": 7000,
                    "savings_dt": 1500,
                    "badge": "Économie 21%"
                },
                {
                    "id": "pack_5000",
                    "credits": 5000,
                    "price_dt": 25000,
                    "type": "enterprise",
                    "description": "Pour grands clubs",
                    "popular": False,
                    "original_price_dt": 35000,
                    "savings_dt": 10000,
                    "badge": "Économie 29%"
                }
            ]
        else:
            # Convertir les packages DB en dictionnaires
            packages = [pkg.to_dict() for pkg in db_packages]
        
        return jsonify({"packages": packages}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des packages clubs: {e}")
        return jsonify({"error": "Erreur serveur"}), 500

# Route pour qu'un club achète des crédits
@clubs_bp.route('/credits/buy', methods=['POST'])
def buy_club_credits():
    """Acheter des crédits en tant que club"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        data = request.get_json()
        credits_amount = data.get('credits_amount', 0)
        payment_method = data.get('payment_method', 'simulation')
        
        if credits_amount <= 0:
            return jsonify({'error': 'Le montant de crédits doit être positif'}), 400
        
        # Charger les packages depuis la base de données
        from src.models.credit_package import CreditPackage
        
        # Récupérer les packages clubs actifs
        db_packages = CreditPackage.query.filter_by(
            package_type='club',
            is_active=True
        ).all()
        
        # Construire le dictionnaire de packages (credits -> price_dt)
        packages = {}
        for pkg in db_packages:
            packages[pkg.credits] = pkg.price_dt
        
        # Si aucun package en DB, utiliser les packages par défaut
        if not packages:
            packages = {
                100: 700,
                500: 3000,
                1000: 5500,
                5000: 25000
            }
        
        if credits_amount not in packages:
            return jsonify({'error': f'Package invalide. Packages disponibles : {list(packages.keys())}'}), 400
        
        price = packages[credits_amount]
        
        # Récupérer le club
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        # Ajouter les crédits au club
        old_balance = club.credits_balance
        club.credits_balance += credits_amount
        
        # Logger dans l'historique
        log_club_action(
            user_id=user.id,
            club_id=user.club_id,
            action_type='buy_credits',
            details={
                'credits_bought': credits_amount,
                'price_paid': price,
                'payment_method': payment_method,
                'old_balance': old_balance,
                'new_balance': club.credits_balance
            },
            performed_by_id=user.id
        )
        
        # Créer une notification
        try:
            notification = Notification(
                user_id=user.id,
                notification_type=NotificationType.CREDIT,
                title="💳 Achat de crédits réussi !",
                message=f"Vous avez acheté {credits_amount} crédits pour {price} DT. Nouveau solde : {club.credits_balance} crédits",
                link="/club"
            )
            db.session.add(notification)
            logger.info(f"✅ Notification créée pour le club {user.club_id} - achat {credits_amount} crédits")
        except Exception as notif_error:
            logger.error(f"❌ Erreur création notification achat crédits club: {notif_error}")
        
        db.session.commit()
        
        logger.info(f"Club {user.club_id} a acheté {credits_amount} crédits pour {price} DT")
        
        return jsonify({
            'message': f'{credits_amount} crédits achetés avec succès',
            'club': {
                'id': club.id,
                'name': club.name,
                'old_balance': old_balance,
                'new_balance': club.credits_balance,
                'credits_bought': credits_amount,
                'price_paid': price
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors de l'achat de crédits du club: {e}")
        return jsonify({'error': 'Erreur lors de l\'achat de crédits'}), 500

# Route pour ajouter des crédits à un joueur
@clubs_bp.route('/<int:player_id>/add-credits', methods=['POST'])
def add_credits_to_player(player_id):
    logger.info(f"🎯 [ADD CREDITS] Début - player_id={player_id}")
    user = get_current_user()
    if not user:
        logger.error("❌ [ADD CREDITS] Utilisateur non authentifié")
        return jsonify({'error': 'Non authentifié'}), 401
    
    logger.info(f"✅ [ADD CREDITS] User authentifié - ID={user.id}, role={user.role}, club_id={user.club_id}")
    
    if user.role != UserRole.CLUB:
        logger.error(f"❌ [ADD CREDITS] Accès refusé - role={user.role}")
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        logger.info(f"🔍 [ADD CREDITS] Récupération joueur ID={player_id}")
        # Récupérer le joueur
        player = User.query.get_or_404(player_id)
        logger.info(f"✅ [ADD CREDITS] Joueur trouvé - name={player.name}, club_id={player.club_id}")
        
        # Vérifier que le joueur est associé au club
        if player.club_id != user.club_id:
            logger.error(f"❌ [ADD CREDITS] Joueur pas dans le club - player.club_id={player.club_id}, user.club_id={user.club_id}")
            return jsonify({'error': 'Ce joueur n\'est pas associé à votre club'}), 403
        
        logger.info(f"📦 [ADD CREDITS] R écupération données request")
        data = request.get_json()
        credits = data.get('credits')
        logger.info(f"💰 [ADD CREDITS] Crédits demandés: {credits}")
        
        if not credits or credits <= 0:
            logger.error(f"❌ [ADD CREDITS] Montant invalide: {credits}")
            return jsonify({'error': 'Le nombre de crédits doit être un entier positif'}), 400
        
        # Récupérer le club et vérifier son solde
        logger.info(f"🏢 [ADD CREDITS] Récupération club ID={user.club_id}")
        club = Club.query.get(user.club_id)
        if not club:
            logger.error(f"❌ [ADD CREDITS] Club non trouvé - club_id={user.club_id}")
            return jsonify({'error': 'Club non trouvé'}), 404
        
        logger.info(f"✅ [ADD CREDITS] Club trouvé - name={club.name}, solde={club.credits_balance}")
        
        # Validation : vérifier que le club a assez de crédits
        if club.credits_balance < credits:
            logger.error(f"❌ [ADD CREDITS] Solde insuffisant - solde={club.credits_balance}, demandé={credits}")
            return jsonify({
                'error': f'Solde insuffisant. Vous avez {club.credits_balance} crédits, vous essayez d\'en offrir {credits}.',
                'club_balance': club.credits_balance,
                'credits_requested': credits
            }), 400
        
        # Déduire les crédits du club
        logger.info(f"💸 [ADD CREDITS] Déduction crédits club - ancien={club.credits_balance}, nouveau={club.credits_balance - credits}")
        old_club_balance = club.credits_balance
        club.credits_balance -= credits
        
        # Ajouter les crédits au joueur
        logger.info(f"✨ [ADD CREDITS] Ajout crédits joueur - ancien={player.credits_balance}, nouveau={player.credits_balance + credits}")
        old_balance = player.credits_balance
        player.credits_balance += credits
        
        # Enregistrer l'action dans l'historique
        logger.info(f"📝 [ADD CREDITS] Création entrée historique")
        history_entry = ClubActionHistory(
            user_id=player.id,
            club_id=user.club_id,
            performed_by_id=user.id,
            action_type='club_add_credits',
            action_details=json.dumps({
                'credits_added': credits,
                'old_balance': old_balance,
                'new_balance': player.credits_balance
            })
        )
        
        logger.info(f"💾 [ADD CREDITS] Ajout à la session DB")
        db.session.add(history_entry)
        
        # Créer une notification pour le joueur
        try:
            # Récupérer le nom du club
            club = Club.query.get(user.club_id)
            club_name = club.name if club else "votre club"
            
            notification = Notification(
                user_id=player.id,
                notification_type='CREDITS_ADDED',  # Matches PostgreSQL enum
                title="🎁 Crédits offerts !",
                message=f"{club_name} vous a offert {credits} crédits. Nouveau solde : {player.credits_balance} crédits",
                link="/player"
            )
            db.session.add(notification)
            logger.info(f"✅ Notification créée pour le joueur {player.id} - {credits} crédits offerts par le club {user.club_id}")
        except Exception as notif_error:
            logger.error(f"❌ Erreur création notification pour crédits offerts: {notif_error}")
        
        logger.info(f"💾 [ADD CREDITS] Commit transaction")
        db.session.commit()
        logger.info(f"🎉 [ADD CREDITS] Succès! {credits} crédits transférés à {player.name}")
        
        return jsonify({
            'message': f'{credits} crédits transférés avec succès à {player.name}',
            'player': {
                'id': player.id,
                'name': player.name,
                'new_balance': player.credits_balance
            },
            'club': {
                'old_balance': old_club_balance,
                'new_balance': club.credits_balance,
                'credits_transferred': credits
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"❌❌❌ [ADD CREDITS] ERREUR CRITIQUE ❌❌❌")
        logger.error(f"Exception: {type(e).__name__}: {str(e)}")
        logger.error(f"Stack trace:\n{error_trace}")
        traceback.print_exc()
        return jsonify({'error': f'Erreur lors de l\'ajout de crédits: {str(e)}'}), 500

# Route pour mettre à jour les informations d'un joueur
@clubs_bp.route('/<int:player_id>', methods=['PUT'])
def update_player(player_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        # Récupérer le joueur
        player = User.query.get_or_404(player_id)
        
        # Vérifier que le joueur est associé au club
        if player.club_id != user.club_id:
            return jsonify({'error': 'Ce joueur n\'est pas associé à votre club'}), 403
        
        data = request.get_json()
        changes = {}
        
        if 'name' in data and data['name'] != player.name:
            changes['name'] = {'old': player.name, 'new': data['name']}
            player.name = data['name']
            
        if 'phone_number' in data and data['phone_number'] != player.phone_number:
            changes['phone_number'] = {'old': player.phone_number, 'new': data['phone_number']}
            player.phone_number = data['phone_number']
        
        if changes:
            # Enregistrer l'action dans l'historique
            history_entry = ClubActionHistory(
                user_id=player.id,
                club_id=user.club_id,
                performed_by_id=user.id,
                action_type='update_player',
                action_details=json.dumps({
                    'changes': changes
                })
            )
            
            db.session.add(history_entry)
            db.session.commit()
            
            return jsonify({
                'message': 'Informations du joueur mises à jour avec succès',
                'player': player.to_dict()
            }), 200
        else:
            return jsonify({
                'message': 'Aucune modification effectuée',
                'player': player.to_dict()
            }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la mise à jour du joueur: {e}")
        return jsonify({'error': 'Erreur lors de la mise à jour du joueur'}), 500

# Route pour récupérer les vidéos enregistrées sur les terrains du club
@clubs_bp.route('/videos', methods=['GET'])
def get_club_videos():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        # Récupérer les terrains du club
        courts = Court.query.filter_by(club_id=club.id).all()
        court_ids = [court.id for court in courts]
        
        # Récupérer les vidéos enregistrées sur ces terrains avec joinedload pour optimiser
        from src.models.user import Video
        from sqlalchemy.orm import joinedload
        
        videos = Video.query.options(joinedload(Video.owner)).filter(Video.court_id.in_(court_ids)).order_by(Video.recorded_at.desc()).all() if court_ids else []
        
        # Enrichir les vidéos avec le nom du joueur
        videos_enriched = []
        for video in videos:
            video_dict = video.to_dict()
            # Ajouter le nom du joueur
            if video.owner:
                video_dict['player_name'] = video.owner.name
            else:
                video_dict['player_name'] = 'Joueur inconnu'
            videos_enriched.append(video_dict)
        
        return jsonify({'videos': videos_enriched}), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des vidéos: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des vidéos'}), 500

# Route de diagnostic pour voir pourquoi les données ne s'affichent pas
@clubs_bp.route('/debug', methods=['GET'])
def debug_club_data():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
        
    try:
        # Récupérer les informations de l'utilisateur connecté
        user_info = {
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'role': user.role.value if user.role else None,
            'club_id': user.club_id
        }
        
        # Récupérer les informations du club si c'est un club
        club_info = None
        if user.role == UserRole.CLUB and user.club_id:
            club = Club.query.get(user.club_id)
            if club:
                club_info = {
                    'id': club.id,
                    'name': club.name,
                    'address': club.address,
                    'created_at': club.created_at.isoformat() if club.created_at else None
                }
                
                # Compter les entités associées
                players = User.query.filter_by(club_id=club.id, role=UserRole.PLAYER).all()
                courts = Court.query.filter_by(club_id=club.id).all()
                
                club_info['players'] = [{
                    'id': p.id,
                    'name': p.name,
                    'email': p.email
                } for p in players]
                
                club_info['courts'] = [{
                    'id': c.id,
                    'name': c.name,
                    'qr_code': c.qr_code
                } for c in courts]
                
                # Vérifier les followers
                followers_count = 0
                try:
                    followers_count = club.followers.count()
                except Exception as e:
                    print(f"Erreur dans le comptage des followers: {e}")
                
                club_info['followers_count'] = followers_count
                
        # Vérifier si les tables sont bien créées
        database_info = {
            'tables_exist': {
                'User': db.engine.has_table('user'),
                'Club': db.engine.has_table('club'),
                'Court': db.engine.has_table('court'),
                'Video': db.engine.has_table('video'),
                'ClubActionHistory': db.engine.has_table('club_action_history'),
                'player_club_follows': db.engine.has_table('player_club_follows')
            }
        }
        
        return jsonify({
            'user': user_info,
            'club': club_info,
            'database': database_info,
            'session': {
                'user_id': session.get('user_id'),
                'user_role': session.get('user_role')
            }
        }), 200
        
    except Exception as e:
        print(f"Erreur lors du diagnostic: {e}")
        return jsonify({'error': f'Erreur lors du diagnostic: {str(e)}'}), 500

# Route pour tester la réponse JSON du dashboard (sans les logs de debug)
@clubs_bp.route('/dashboard-json-test', methods=['GET'])
def test_dashboard_json():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        # Récupérer le club associé à l'utilisateur
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        # Calculer les statistiques SANS les logs pour voir la réponse JSON pure
        # 1. Compter les joueurs
        players = User.query.filter_by(club_id=club.id, role=UserRole.PLAYER).all()
        players_count = len(players)
        
        # 2. Compter les terrains
        courts = Court.query.filter_by(club_id=club.id).all()
        courts_count = len(courts)
        
        # 3. Compter les vidéos
        videos_count = 0
        if courts:
            videos = db.session.query(Video).join(Court, Video.court_id == Court.id).filter(
                Court.club_id == club.id
            ).all()
            videos_count = len(videos)
        
        # 4. Compter les followers
        followers_count = 0
        try:
            followers_list = club.followers.all()
            followers_count = len(followers_list)
        except:
            followers_count = 0
        
        # 5. Compter les crédits
        credits_given = 0
        try:
            credit_entries = db.session.query(ClubActionHistory).filter_by(
                club_id=club.id,
                action_type='add_credits'
            ).all()
            
            for entry in credit_entries:
                try:
                    if entry.action_details:
                        details = json.loads(entry.action_details)
                        credits_added = details.get('credits_added', 0)
                        if isinstance(credits_added, (int, float)):
                            credits_given += int(credits_added)
                except:
                    pass
        except:
            credits_given = 0
        
        # Réponse JSON claire - NOMS COMPATIBLES AVEC LE FRONTEND
        response_data = {
            'success': True,
            'club': {
                'id': club.id,
                'name': club.name,
                'address': club.address,
                'email': club.email,
                'created_at': club.created_at.isoformat() if club.created_at else None
            },
            'stats': {
                'total_players': players_count,      # Frontend attend 'total_players'
                'total_courts': courts_count,        # Frontend attend 'total_courts'  
                'total_videos': videos_count,        # Frontend attend 'total_videos'
                'total_credits_offered': credits_given,  # Frontend attend 'total_credits_offered'
                'followers_count': followers_count,
                # Garder aussi les anciens noms pour compatibilité
                'players_count': players_count,
                'courts_count': courts_count,
                'videos_count': videos_count,
                'credits_given': credits_given
            },
            'players': [player.to_dict() for player in players],
            'courts': [court.to_dict() for court in courts],
            'videos': [video.to_dict() for video in videos] if courts else [],
            'debug_info': {
                'user_id': user.id,
                'club_id': user.club_id,
                'role': user.role.value,
                'timestamp': datetime.utcnow().isoformat()
            }
        }
        
        return jsonify(response_data), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Erreur lors de la récupération du tableau de bord: {str(e)}'
        }), 500

# Route pour forcer la création de données de test complètes (inspirée d'admin.py)
@clubs_bp.route('/force-create-test-data', methods=['POST'])
def force_create_test_data():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role not in [UserRole.CLUB, UserRole.SUPER_ADMIN]:
        return jsonify({'error': 'Accès réservé aux clubs et administrateurs'}), 403
        
    try:
        # Récupérer le club
        club_id = user.club_id
        if not club_id:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        club = Club.query.get(club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        print(f"Force création de données pour le club ID: {club.id}, nom: {club.name}")
        
        # 1. Créer/vérifier les terrains
        courts_created = 0
        courts = []
        for i in range(1, 4):  # 3 terrains
            court_name = f"Terrain {i}"
            court = Court.query.filter_by(club_id=club_id, name=court_name).first()
            if not court:
                court = Court(
                    club_id=club_id,
                    name=court_name,
                    qr_code=f"QR_{club_id}_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    camera_url=f"http://example.com/camera/{club_id}/{i}"
                )
                db.session.add(court)
                courts_created += 1
                print(f"Terrain créé: {court_name}")
            courts.append(court)
        
        db.session.flush()  # Pour obtenir les IDs
        
        # 2. Créer/vérifier les joueurs (similar to admin.py user creation)
        players_created = 0
        players = []
        for i in range(1, 6):  # 5 joueurs
            player_email = f"testplayer{i}_club{club_id}@example.com"
            player = User.query.filter_by(email=player_email).first()
            if not player:
                player = User(
                    email=player_email,
                    name=f"Test Player {i} - Club {club.name}",
                    password_hash=generate_password_hash('password123'),
                    role=UserRole.PLAYER,
                    club_id=club_id,
                    credits_balance=10
                )
                db.session.add(player)
                players_created += 1
                print(f"Joueur créé: {player.name}")
            else:
                # S'assurer que le joueur est bien associé au club
                if player.club_id != club_id:
                    player.club_id = club_id
                    print(f"Joueur associé au club: {player.name}")
            players.append(player)
        
        db.session.flush()  # Pour obtenir les IDs des joueurs
        
        # 3. Créer des followers externes (similar to admin.py approach)
        followers_created = 0
        external_followers = []
        for i in range(1, 4):  # 3 followers externes
            follower_email = f"follower{i}_for_club{club_id}@example.com"
            follower = User.query.filter_by(email=follower_email).first()
            if not follower:
                follower = User(
                    email=follower_email,
                    name=f"External Follower {i}",
                    password_hash=generate_password_hash('password123'),
                    role=UserRole.PLAYER,
                    credits_balance=SystemSettings.get_welcome_credits()
                    # Pas de club_id pour les externes
                )
                db.session.add(follower)
                followers_created += 1
                print(f"Follower externe créé: {follower.name}")
            external_followers.append(follower)
        
        db.session.flush()
        
        # Associer tous les followers au club (similaire à admin.py)
        all_followers = players + external_followers
        for follower in all_followers:
            if club not in follower.followed_clubs.all():
                follower.followed_clubs.append(club)
                print(f"{follower.name} suit maintenant le club")
        
        # 4. Créer des vidéos (similar to admin.py video creation logic)
        videos_created = 0
        for court in courts:
            for player in players:
                # 2 vidéos par joueur par terrain
                for v in range(1, 3):
                    video_title = f"Match {player.name} - {court.name} - Video {v}"
                    existing_video = Video.query.filter_by(
                        title=video_title,
                        user_id=player.id,
                        court_id=court.id
                    ).first()
                    
                    if not existing_video:
                        video = Video(
                            title=video_title,
                            description=f"Match enregistré le {datetime.now().strftime('%Y-%m-%d')}",
                            file_url=f"http://example.com/videos/{club_id}/{court.id}/{player.id}/{v}.mp4",
                            thumbnail_url=f"http://example.com/thumbs/{club_id}/{court.id}/{player.id}/{v}.jpg",
                            duration=random.randint(600, 7200),  # 10min à 2h
                            is_unlocked=True,
                            credits_cost=random.randint(1, 3),
                            user_id=player.id,
                            court_id=court.id,
                            recorded_at=datetime.utcnow(),
                            created_at=datetime.utcnow()
                        )
                        db.session.add(video)
                        videos_created += 1
                        print(f"Vidéo créée: {video_title}")
        
        # 5. Créer des entrées d'historique pour les crédits (similar to admin.py log_club_action)
        credits_entries_created = 0
        for player in players:
            # Plusieurs distributions de crédits par joueur
            for _ in range(random.randint(2, 4)):
                credits_amount = random.randint(5, 20)
                history_entry = ClubActionHistory(
                    user_id=player.id,
                    club_id=club_id,
                    performed_by_id=user.id,
                    action_type='add_credits',
                    action_details=json.dumps({
                        'credits_added': credits_amount,
                        'player_name': player.name,
                        'reason': 'Test data generation'
                    }),
                    performed_at=datetime.utcnow() - timedelta(days=random.randint(1, 30))
                )
                db.session.add(history_entry)
                credits_entries_created += 1
                print(f"Ajout de {credits_amount} crédits à {player.name}")
        
        # 6. Créer d'autres types d'historique
        for player in players:
            # Historique d'ajout de joueur
            history_entry = ClubActionHistory(
                user_id=player.id,
                club_id=club_id,
                performed_by_id=user.id,
                action_type='add_player',
                action_details=json.dumps({
                    'player_name': player.name,
                    'player_email': player.email
                }),
                performed_at=datetime.utcnow() - timedelta(days=random.randint(1, 60))
            )
            db.session.add(history_entry)
        
        # Commit final
        db.session.commit()
        
        # Vérification post-création
        verification = {
            'players_count': User.query.filter_by(club_id=club_id, role=UserRole.PLAYER).count(),
            'courts_count': Court.query.filter_by(club_id=club_id).count(),
            'videos_count': len(db.session.query(Video).join(Court).filter(Court.club_id == club_id).all()),
            'followers_count': len(club.followers.all()),
            'credits_entries': ClubActionHistory.query.filter_by(club_id=club_id, action_type='add_credits').count()
        }
        
        return jsonify({
            'message': 'Données de test créées avec succès',
            'created': {
                'courts': courts_created,
                'players': players_created,
                'followers': followers_created,
                'videos': videos_created,
                'credit_entries': credits_entries_created
            },
            'verification': verification,
            'club': {
                'id': club.id,
                'name': club.name
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la création forcée des données: {e}")
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

# Route pour créer des données de test pour le club connecté
@clubs_bp.route('/create-test-data', methods=['POST'])
def create_test_data():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB and user.role != UserRole.SUPER_ADMIN:
        return jsonify({'error': 'Accès réservé aux clubs et administrateurs'}), 403
        
    try:
        # Récupérer le club
        club_id = user.club_id
        if not club_id:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        club = Club.query.get(club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        print(f"Création de données de test pour le club ID: {club.id}, nom: {club.name}")
        
        # Créer des terrains pour le club
        courts_data = []
        courts = []
        for i in range(1, 4):  # Créer 3 terrains
            court = Court.query.filter_by(club_id=club_id, name=f"Terrain {i}").first()
            if not court:
                court = Court(
                    club_id=club_id,
                    name=f"Terrain {i}",
                    qr_code=f"QR_TERRAIN_{club_id}_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    camera_url=f"http://exemple.com/camera/{club_id}/{i}"
                )
                db.session.add(court)
                courts_data.append({'name': court.name, 'created': True})
                courts.append(court)
            else:
                courts_data.append({'name': court.name, 'created': False})
                courts.append(court)
        
        # Flush pour obtenir les IDs des terrains
        db.session.flush()
        
        # Créer des joueurs pour le club
        players_data = []
        players = []
        test_players = [
            {'name': 'Joueur Test 1', 'email': f'joueur1_{club_id}@test.com'},
            {'name': 'Joueur Test 2', 'email': f'joueur2_{club_id}@test.com'},
            {'name': 'Joueur Test 3', 'email': f'joueur3_{club_id}@test.com'}
        ]
        
        for player_info in test_players:
            player = User.query.filter_by(email=player_info['email']).first()
            if not player:
                player = User(
                    email=player_info['email'],
                    name=player_info['name'],
                    password_hash=generate_password_hash('password123'),
                    role=UserRole.PLAYER,
                    club_id=club_id,
                    credits_balance=SystemSettings.get_welcome_credits()
                )
                db.session.add(player)
                players_data.append({'name': player.name, 'created': True})
                players.append(player)
                
                # Créer une entrée d'historique pour ce joueur
                history_entry = ClubActionHistory(
                    user_id=player.id,
                    club_id=club_id,
                    performed_by_id=user.id,
                    action_type='add_player',
                    action_details=json.dumps({
                        'player_name': player.name,
                        'player_email': player.email
                    }),
                    performed_at=datetime.utcnow()
                )
                db.session.add(history_entry)
            else:
                players_data.append({'name': player.name, 'created': False})
                players.append(player)
        
        # Flush pour obtenir les IDs des joueurs
        db.session.flush()
        
        # Créer des followers pour le club
        followers_data = []
        
        # Créer 2 joueurs externes qui vont suivre le club
        external_players = [
            {'name': 'Follower Externe 1', 'email': f'follower1_{club_id}@test.com'},
            {'name': 'Follower Externe 2', 'email': f'follower2_{club_id}@test.com'}
        ]
        
        for player_info in external_players:
            player = User.query.filter_by(email=player_info['email']).first()
            if not player:
                player = User(
                    email=player_info['email'],
                    name=player_info['name'],
                    password_hash=generate_password_hash('password123'),
                    role=UserRole.PLAYER,
                    credits_balance=3
                    # Pas de club_id pour les followers externes
                )
                db.session.add(player)
                db.session.flush()
                followers_data.append({'name': player.name, 'created': True})
                
                # Faire suivre le club par ce joueur
                player.followed_clubs.append(club)
            else:
                followers_data.append({'name': player.name, 'created': False})
                
                # S'assurer que le joueur suit le club
                if club not in player.followed_clubs.all():
                    player.followed_clubs.append(club)
        
        # Faire suivre le club par les joueurs du club aussi
        for player in players:
            if club not in player.followed_clubs.all():
                player.followed_clubs.append(club)
        
        # Créer des vidéos pour les terrains et joueurs
        videos_data = []
        
        # Pour chaque terrain, créer quelques vidéos
        for court in courts:
            for player in players:
                # Créer 2 vidéos par joueur et par terrain
                for i in range(2):
                    video_title = f"Match de {player.name} sur {court.name} #{i+1}"
                    
                    # Vérifier si la vidéo existe déjà
                    existing_video = Video.query.filter_by(
                        title=video_title,
                        user_id=player.id,
                        court_id=court.id
                    ).first()
                    
                    if not existing_video:
                        video = Video(
                            title=video_title,
                            description=f"Description de la vidéo {i+1} pour {player.name}",
                            file_url=f"http://exemple.com/videos/{club_id}/{court.id}/{player.id}/{i+1}.mp4",
                            thumbnail_url=f"http://exemple.com/thumbnails/{club_id}/{court.id}/{player.id}/{i+1}.jpg",
                            duration=random.randint(300, 3600),  # 5 minutes à 1 heure
                            is_unlocked=True,
                            credits_cost=1,
                            recorded_at=datetime.utcnow(),
                            user_id=player.id,
                            court_id=court.id
                        )
                        db.session.add(video)
                        videos_data.append({'title': video.title, 'created': True})
                    else:
                        videos_data.append({'title': existing_video.title, 'created': False})
        
        # Créer des entrées pour les crédits
        credits_data = []
        
        for player in players:
            # Ajouter des crédits pour chaque joueur
            credits_to_add = 10
            
            history_entry = ClubActionHistory(
                user_id=player.id,
                club_id=club_id,
                performed_by_id=user.id,
                action_type='add_credits',
                action_details=json.dumps({
                    'credits_added': credits_to_add,
                    'player_name': player.name
                }),
                performed_at=datetime.utcnow()
            )
            db.session.add(history_entry)
            credits_data.append({
                'player_name': player.name,
                'credits_added': credits_to_add
            })
        
        # Commit des changements en base de données
        db.session.commit()
        
        return jsonify({
            'message': 'Données de test créées avec succès',
            'courts': courts_data,
            'players': players_data,
            'followers': followers_data,
            'videos': videos_data,
            'credits': credits_data
        }), 201
        
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la création des données de test: {e}")
        return jsonify({'error': f'Erreur lors de la création des données de test: {str(e)}'}), 500

# Route pour mettre à jour les informations du profil du club
@clubs_bp.route('/profile', methods=['PUT'])
def update_club_profile():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    if user.role != UserRole.CLUB:
        return jsonify({'error': 'Accès réservé aux clubs'}), 403
        
    try:
        club = Club.query.get(user.club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
            
        data = request.get_json()
        
        # Logging des modifications
        changes = []
        
        # Mettre à jour les informations du club
        if 'name' in data:
            old_name = club.name
            club.name = data['name']
            changes.append(f"Nom: '{old_name}' → '{club.name}'")
            
        if 'address' in data:
            old_address = club.address or "Non défini"
            club.address = data['address']
            changes.append(f"Adresse: '{old_address}' → '{club.address}'")
            
        if 'phone_number' in data:
            old_phone = club.phone_number or "Non défini"
            club.phone_number = data['phone_number']
            changes.append(f"Téléphone: '{old_phone}' → '{club.phone_number}'")
            
        if 'email' in data:
            old_email = club.email
            club.email = data['email']
            changes.append(f"Email: '{old_email}' → '{club.email}'")
            
        # SYNCHRONISATION BIDIRECTIONNELLE: Mettre à jour l'utilisateur associé
        if 'name' in data:
            user.name = data['name']
            
        if 'phone_number' in data:
            user.phone_number = data['phone_number']
            
        if 'email' in data:
            user.email = data['email']
        
        # Log des modifications pour traçabilité
        if changes:
            print(f"✅ Profil club {club.id} mis à jour:")
            for change in changes:
                print(f"   - {change}")
            print(f"👤 Synchronisation user {user.id} effectuée")
            
        db.session.commit()
        
        return jsonify({
            'message': 'Profil mis à jour avec succès',
            'club': club.to_dict(),
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la mise à jour du profil: {e}")
        return jsonify({'error': 'Erreur lors de la mise à jour du profil'}), 500

# Route pour arrêter un enregistrement depuis le dashboard club
@clubs_bp.route('/courts/<int:court_id>/stop-recording', methods=['POST'])
def stop_court_recording(court_id):
    """
    Permet à un club d'arrêter l'enregistrement en cours sur un terrain spécifique
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Non authentifié'}), 401
        
        if user.role not in [UserRole.CLUB, UserRole.SUPER_ADMIN]:
            return jsonify({'error': 'Seuls les clubs et super admins peuvent arrêter les enregistrements'}), 403
        
        # Vérifier que le terrain appartient au club (sauf pour super admin)
        court = Court.query.get_or_404(court_id)
        if user.role == UserRole.CLUB and court.club_id != user.club.id:
            return jsonify({'error': 'Ce terrain ne vous appartient pas'}), 403
        
        # Importer les classes nécessaires
        from src.models.user import RecordingSession, Video
        
        # Trouver l'enregistrement actif sur ce terrain
        active_recording = RecordingSession.query.filter_by(
            court_id=court_id,
            status='active'
        ).first()
        
        if not active_recording:
            return jsonify({'error': 'Aucun enregistrement actif sur ce terrain'}), 404
        
        # Arrêter l'enregistrement
        active_recording.status = 'stopped'
        active_recording.end_time = datetime.utcnow()
        active_recording.stopped_by = 'club'
        
        # IMPORTANT: Libérer le terrain pour que le joueur le voit comme disponible
        court.is_recording = False
        court.current_recording_id = None
        
        # Calculer la durée de l'enregistrement avec debug
        start_time = active_recording.start_time
        end_time = active_recording.end_time
        
        print(f"DEBUG - Calcul durée:")
        print(f"  Start time: {start_time}")
        print(f"  End time: {end_time}")
        
        if start_time and end_time:
            duration_delta = end_time - start_time
            duration_seconds = duration_delta.total_seconds()
            duration_minutes = max(1, int(duration_seconds / 60))  # Minimum 1 minute
            
            print(f"  Durée en secondes: {duration_seconds}")
            print(f"  Durée en minutes: {duration_minutes}")
        else:
            # Fallback si les dates sont nulles
            duration_minutes = 1
            print(f"  Fallback: durée fixée à 1 minute")
        
        
        # 🆕 Arrêter l'enregistrement vidéo via NOUVEAU système
        from src.video_system.session_manager import session_manager
        from src.video_system.recording import video_recorder
        
        try:
            # Arrêter enregistrement FFmpeg
            video_file_path = video_recorder.stop_recording(active_recording.recording_id)
            logger.info(f"Arrêt enregistrement via nouveau système: {video_file_path}")
            
            # Fermer session proxy
            # CRITIQUE: Marquer comme inactif AVANT de fermer
            session = session_manager.get_session(active_recording.recording_id)
            if session:
                session.recording_active = False
            session_manager.close_session(active_recording.recording_id)
            
            # Le fichier est dans static/videos/{club_id}/{session_id}.mp4
            if video_file_path:
                video_file_url = f"videos/{court.club_id}/{active_recording.recording_id}.mp4"
            else:
                video_file_url = None
                
        except Exception as e:
            logger.warning(f"Erreur lors de l'arrêt du service vidéo: {e}")
            video_file_url = None
                
        # Créer automatiquement une vidéo pour le joueur
        # Format: "Match [jour/mois], Terrain [n°], [nom club]"
        recorded_date = active_recording.start_time.strftime('%d/%m') if active_recording.start_time else datetime.now().strftime('%d/%m')
        club = Club.query.get(court.club_id) if court.club_id else None
        club_name = club.name if club else "Club"
        video_title = active_recording.title or f"Match {recorded_date}, {court.name}, {club_name}"
        
        # Déterminer l'URL du fichier vidéo
        video_file_url = None
        # video_file_url déjà défini plus haut (ligne ~1449)
        # Vérifier que le fichier existe
        if not video_file_url or not os.path.exists(video_file_url):
            possible_paths = [
                f"static/videos/{court.club_id}/{active_recording.recording_id}.mp4",
                f"static/videos/{active_recording.recording_id}.mp4"
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    video_file_url = path
                    logger.info(f"Fichier vidéo trouvé: {path}")
                    break
            else:
                logger.warning(f"Fichier vidéo introuvable pour {active_recording.recording_id}")
        
        new_video = Video(
            title=video_title,
            description=active_recording.description or f"Enregistrement automatique sur {court.name}",
            duration=duration_minutes,  # ⚠️ TEMPORAIRE - sera corrigé ci-dessous
            user_id=active_recording.user_id,
            court_id=court_id,
            recorded_at=active_recording.start_time,
            file_url=video_file_url,  # ✅ Ajouter l'URL du fichier
            is_unlocked=True,  # Vidéo débloquée automatiquement
            credits_cost=0     # Pas de coût puisque l'enregistrement a été arrêté par le club
        )
        
        # 🔍 CORRECTION CRITIQUE - Vérifier durée réelle du fichier (comme dans recording.py)
        if video_file_url and os.path.exists(video_file_url):
            try:
                logger.info(f"🔍 Vérification durée réelle fichier: {video_file_url}")
                
                # Attendre que le fichier soit complètement finalisé
                import time
                time.sleep(2)
                
                # Utiliser ffprobe pour obtenir la durée réelle
                # Utiliser FFmpegRunner
                from src.services.ffmpeg_runner import FFmpegRunner
                runner = FFmpegRunner()
                ffprobe_result = runner.probe_video_info(video_file_url)
                
                if ffprobe_result:
                    real_duration_seconds = ffprobe_result['duration']
                    real_duration_minutes = real_duration_seconds / 60
                    difference_seconds = abs(real_duration_seconds - (duration_minutes * 60))
                    
                    logger.info(f"📊 COMPARAISON DURÉES (route clubs):")
                    logger.info(f"   🗄️ DB (calcul): {duration_minutes:.2f} min = {duration_minutes * 60:.0f}s")
                    logger.info(f"   🎥 Fichier réel: {real_duration_minutes:.2f} min = {real_duration_seconds:.0f}s")
                    logger.info(f"   📈 Différence: {difference_seconds:.0f}s")
                    
                    if difference_seconds > 10:  # Différence significative
                        logger.warning(f"⚠️ ÉCART IMPORTANT: {difference_seconds:.0f}s - utilisation durée réelle")
                        new_video.duration = real_duration_seconds  # ✅ Correction durée
                    else:
                        logger.info("✅ Durées cohérentes")
                        new_video.duration = real_duration_seconds  # ✅ Utiliser durée précise même si cohérente
                        
                    logger.info(f"🎯 DURÉE FINALE clubs.py: {new_video.duration:.0f}s")
                else:
                    logger.warning("⚠️ Impossible de lire durée réelle - utilisation durée DB")
                    new_video.duration = duration_minutes * 60  # Conversion en secondes
            except Exception as e:
                logger.error(f"❌ Erreur lecture durée réelle: {e}")
                new_video.duration = duration_minutes * 60
        else:
            logger.warning("⚠️ Pas de fichier pour vérification - utilisation durée DB")
            new_video.duration = duration_minutes * 60
        
        db.session.add(new_video)
        
        # Upload automatique vers Bunny CDN si le fichier existe
        if video_file_url and os.path.exists(video_file_url):
            try:
                from src.services.bunny_storage_service import bunny_storage_service
                
                logger.info(f"🚀 Début upload vers Bunny CDN: {video_file_url}")
                
                # Déclencher l'upload en arrière-plan
                upload_id = bunny_storage_service.queue_upload(
                    local_path=video_file_url,
                    title=new_video.title,
                    metadata={
                        'video_id': new_video.id,
                        'user_id': active_recording.user_id,
                        'court_id': court_id,
                        'recording_id': active_recording.recording_id,
                        'duration': duration_minutes
                    }
                )
                
                if upload_id:
                    logger.info(f"✅ Upload Bunny programmé avec ID: {upload_id}")
                    
                    # ✨ CORRECTION: Wait for upload and update bunny_video_id + file_url
                    import time
                    time.sleep(3)  # Give queue time to process
                    
                    upload_status = bunny_storage_service.get_upload_status(upload_id)
                    if upload_status and upload_status.get('bunny_video_id'):
                        bunny_id = upload_status['bunny_video_id']
                        new_video.bunny_video_id = bunny_id
                        from src.config.bunny_config import BUNNY_CONFIG
                        cdn_hostname = BUNNY_CONFIG.get('cdn_hostname', 'vz-9b857324-07d.b-cdn.net')
                        new_video.file_url = f"https://{cdn_hostname}/{bunny_id}/playlist.m3u8"
                        db.session.commit()
                        logger.info(f"✅ Bunny video ID saved: {new_video.bunny_video_id}")
                        logger.info(f"✅ Bunny URL updated: {new_video.file_url}")
                    else:
                        logger.warning(f"⚠️ Upload status: {upload_status}")
                else:
                    logger.warning(f"⚠️ Échec programmation upload Bunny")
                    
            except Exception as bunny_error:
                logger.warning(f"⚠️ Erreur upload Bunny CDN: {bunny_error}")
        
        # Log de l'action d'arrêt par le club
        try:
            action_history = ClubActionHistory(
                club_id=user.club.id,
                user_id=active_recording.user_id,
                action_type='stop_recording',
                action_details=json.dumps({
                    'stopped_by': 'club',
                    'duration_minutes': duration_minutes,
                    'court_name': court.name,
                    'video_title': new_video.title,
                    'recording_id': active_recording.recording_id
                }),
                performed_by_id=user.id,
                performed_at=datetime.utcnow()
            )
            db.session.add(action_history)
            logger.info(f"Club {user.club.name} a arrêté l'enregistrement {active_recording.recording_id}")
        except Exception as log_error:
            logger.warning(f"Erreur lors du log d'action: {log_error}")
        
        db.session.commit()
        
        return jsonify({
            'message': 'Enregistrement arrêté avec succès et vidéo créée',
            'recording_id': active_recording.id,
            'video_id': new_video.id,
            'video_title': new_video.title,
            'duration_minutes': duration_minutes,
            'court_id': court_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de l'arrêt de l'enregistrement: {e}")
        return jsonify({'error': 'Erreur lors de l\'arrêt de l\'enregistrement'}), 500


@clubs_bp.route('/cleanup-expired-sessions', methods=['POST'])
def cleanup_expired_sessions():
    """Nettoie les sessions d'enregistrement expirées pour libérer les terrains"""
    try:
        # Vérifier l'authentification (club ou admin)
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Non authentifié'}), 401
        
        if user.role not in [UserRole.CLUB, UserRole.SUPER_ADMIN]:
            return jsonify({'error': 'Permissions insuffisantes'}), 403
        
        # Trouver toutes les sessions actives
        active_sessions = RecordingSession.query.filter_by(status='active').all()
        
        cleaned_count = 0
        sessions_info = []
        
        for session in active_sessions:
            if session.is_expired():
                # Marquer la session comme terminée
                session.status = 'completed'
                cleaned_count += 1
                
                # Collecter les informations pour le rapport
                court = Court.query.get(session.court_id)
                sessions_info.append({
                    'session_id': session.id,
                    'court_id': session.court_id,
                    'court_name': court.name if court else f'Court {session.court_id}',
                    'user_id': session.user_id,
                    'expired_since': session.get_expired_duration_minutes()
                })
        
        if cleaned_count > 0:
            db.session.commit()
            logger.info(f"Nettoyage automatique: {cleaned_count} sessions expirées supprimées")
        
        return jsonify({
            'success': True,
            'message': f'{cleaned_count} session(s) expirée(s) nettoyée(s)',
            'cleaned_sessions': sessions_info,
            'total_cleaned': cleaned_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Erreur lors du nettoyage des sessions: {e}")
        return jsonify({'error': 'Erreur lors du nettoyage'}), 500
