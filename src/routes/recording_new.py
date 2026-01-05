"""
Routes Flask pour l'API d'enregistrement vidéo
"""
from flask import Blueprint, request, jsonify, session
from functools import wraps
import logging
from typing import Optional

from ..services.recording_service import RecordingService
from ..models.recording import Recording
from ..models.user import Club, Court, RecordingSession

logger = logging.getLogger(__name__)

# Blueprint pour les routes d'enregistrement
recording_api = Blueprint('recording_api', __name__)

# Instance globale du service (à initialiser dans l'app factory)
recording_service: Optional[RecordingService] = None


def init_recording_service(app):
    """Initialise le service d'enregistrement"""
    global recording_service
    
    uploader_config = {
        'type': app.config.get('UPLOAD_TYPE', 'local'),
        'api_key': app.config.get('BUNNY_API_KEY'),
        'library_id': app.config.get('BUNNY_LIBRARY_ID'),
        'base_url': app.config.get('BUNNY_BASE_URL', 'https://video.bunnycdn.com')
    }
    
    recording_service = RecordingService(
        output_dir=app.config.get('RECORDINGS_DIR', 'static/recordings'),
        thumbnails_dir=app.config.get('THUMBNAILS_DIR', 'static/thumbnails'),
        uploader_config=uploader_config
    )
    
    logger.info("Service d'enregistrement initialisé")


def require_auth(f):
    """Décorateur pour l'authentification par session Flask"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentification requise'}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_club_admin(f):
    """Décorateur pour vérifier les permissions club"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentification requise'}), 401
        
        # Import local pour éviter les imports circulaires
        from ..models.user import User
        
        user = User.query.get(session['user_id'])
        if not user or user.role.value not in ['club', 'super_admin']:
            return jsonify({'error': 'Permissions insuffisantes'}), 403
        return f(*args, **kwargs)
    return decorated_function


@recording_api.route('/start', methods=['POST'])
@require_auth
def start_recording():
    """Démarre un nouvel enregistrement"""
    try:
        data = request.get_json()
        
        # Validation des paramètres requis
        required_fields = ['court_id']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'Paramètre manquant: {field}'
                }), 400
        
        court_id = data['court_id']
        user_id = session['user_id']  # Définir user_id ici
        
        # Récupérer les informations du terrain
        court = Court.query.get(court_id)
        if not court:
            return jsonify({
                'success': False,
                'error': 'Terrain non trouvé'
            }), 404
        
        # Vérifier que le terrain a une caméra
        if not hasattr(court, 'camera_url') or not court.camera_url:
            return jsonify({
                'success': False,
                'error': 'Ce terrain n\'a pas de caméra configurée'
            }), 400
        
        # Paramètres avec valeurs par défaut
        camera_url = court.camera_url
        max_duration = data.get('duration', 3600)  # 1h par défaut
        quality = data.get('quality', 'medium')
        match_id = data.get('match_id')
        club_id = court.club_id
        title = data.get('title', f'Enregistrement {court.name}')
        description = data.get('description', '')
        
        # Validation des valeurs
        if max_duration > 7200:  # Max 2h
            return jsonify({
                'success': False,
                'error': 'Durée maximale: 2 heures'
            }), 400
        
        if quality not in ['low', 'medium', 'high']:
            return jsonify({
                'success': False,
                'error': 'Qualité invalide (low, medium, high)'
            }), 400
        
        # Démarrer l'enregistrement
        if recording_service is None:
            logger.error("Recording service n'est pas initialisé")
            return jsonify({
                'success': False,
                'error': 'Service d\'enregistrement non disponible'
            }), 503
        
        logger.info(f"Tentative de démarrage d'enregistrement - Court: {court_id}, User: {user_id}, Camera: {camera_url}")
        
        result = recording_service.start_recording(
            user_id=session['user_id'],
            court_id=court_id,
            camera_url=camera_url,
            max_duration=max_duration,
            quality=quality,
            match_id=match_id,
            club_id=club_id
        )
        
        logger.info(f"Résultat start_recording: {result}")
        
        if result['success']:
            return jsonify(result), 201
        else:
            return jsonify(result), 400
            
    except Exception as e:
        logger.error(f"Erreur start_recording: {e}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/start-simple', methods=['POST'])
@require_auth
def start_simple_recording():
    """Version simplifiée du démarrage d'enregistrement sans le recording_service"""
    try:
        from datetime import datetime
        import uuid
        
        data = request.get_json()
        
        # Validation des paramètres requis
        if 'court_id' not in data:
            return jsonify({
                'success': False,
                'error': 'Paramètre manquant: court_id'
            }), 400
        
        court_id = data['court_id']
        user_id = session['user_id']
        
        # Récupérer les informations du terrain
        court = Court.query.get(court_id)
        if not court:
            return jsonify({
                'success': False,
                'error': 'Terrain non trouvé'
            }), 404
        
        # Vérifier qu'il n'y a pas d'enregistrement actif sur ce terrain
        existing_session = RecordingSession.query.filter_by(
            court_id=court_id,
            status='active'
        ).first()
        
        if existing_session:
            return jsonify({
                'success': False,
                'error': 'Un enregistrement est déjà en cours sur ce terrain'
            }), 400
        
        # Vérifier qu'il n'y a pas d'enregistrement actif pour cet utilisateur
        user_active_session = RecordingSession.query.filter_by(
            user_id=user_id,
            status='active'
        ).first()
        
        if user_active_session:
            return jsonify({
                'success': False,
                'error': 'Vous avez déjà un enregistrement en cours'
            }), 400
        
        # Créer une nouvelle session d'enregistrement
        recording_id = str(uuid.uuid4())
        duration = data.get('duration', 60)  # 60 minutes par défaut
        title = data.get('title', f'Enregistrement {court.name}')
        description = data.get('description', '')
        
        recording_session = RecordingSession(
            recording_id=recording_id,
            user_id=user_id,
            court_id=court_id,
            club_id=court.club_id,
            planned_duration=duration,
            title=title,
            description=description,
            status='active',
            start_time=datetime.utcnow()
        )
        
        from ..models.database import db
        db.session.add(recording_session)
        db.session.commit()
        
        response_data = {
            'success': True,
            'recording_session': {
                'id': recording_session.id,
                'recording_id': recording_id,
                'court_id': court_id,
                'club_id': court.club_id,
                'user_id': user_id,
                'planned_duration': duration,
                'title': title,
                'description': description,
                'status': 'active',
                'start_time': recording_session.start_time.isoformat()
            }
        }
        
        logger.info(f"Enregistrement simple créé: {recording_id} pour utilisateur {user_id} sur terrain {court_id}")
        
        return jsonify(response_data), 201
        
    except Exception as e:
        logger.error(f"Erreur start_simple_recording: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/my-active', methods=['GET'])
@require_auth
def get_my_active_recording():
    """Récupère l'enregistrement actif de l'utilisateur connecté"""
    try:
        user_id = session['user_id']
        
        # Chercher un enregistrement actif pour cet utilisateur dans la base de données
        active_session = RecordingSession.query.filter_by(
            user_id=user_id,
            status='active'
        ).first()
        
        if active_session:
            # Get court and club names
            court = Court.query.get(active_session.court_id)
            club = Club.query.get(active_session.club_id)
            
            recording_data = {
                'recording_id': active_session.recording_id,
                'id': active_session.id,
                'user_id': active_session.user_id,
                'court_id': active_session.court_id,
                'court_name': court.name if court else "Court",
                'club_id': active_session.club_id,
                'club_name': club.name if club else "Club",
                'planned_duration': active_session.planned_duration,
                'start_time': active_session.start_time.isoformat() if active_session.start_time else None,
                'title': active_session.title,
                'description': active_session.description,
                'status': active_session.status
            }
            
            return jsonify({
                'success': True,
                'active_recording': recording_data
            }), 200
        else:
            return jsonify({
                'success': True,
                'active_recording': None
            }), 200
            
    except Exception as e:
        logger.error(f"Erreur get_my_active_recording: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/debug/service', methods=['GET'])
def debug_service():
    """Route de debug pour vérifier l'état du service d'enregistrement"""
    try:
        service_info = {
            'recording_service_initialized': recording_service is not None,
            'recording_service_type': type(recording_service).__name__ if recording_service else None
        }
        
        if recording_service:
            try:
                active_recordings = recording_service.list_active_recordings()
                service_info['active_recordings_count'] = len(active_recordings)
                service_info['can_list_recordings'] = True
            except Exception as e:
                service_info['list_recordings_error'] = str(e)
                service_info['can_list_recordings'] = False
        
        return jsonify({
            'success': True,
            'service_info': service_info
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@recording_api.route('/debug/courts', methods=['GET'])
def debug_courts():
    """Route de debug pour vérifier les terrains et leurs caméras"""
    try:
        courts = Court.query.all()
        courts_info = []
        
        for court in courts:
            court_info = {
                'id': court.id,
                'name': court.name,
                'club_id': court.club_id,
                'has_camera_attr': hasattr(court, 'camera_url'),
                'camera_url': getattr(court, 'camera_url', None),
                'camera_url_type': type(getattr(court, 'camera_url', None)).__name__
            }
            courts_info.append(court_info)
        
        return jsonify({
            'success': True,
            'courts': courts_info,
            'total_courts': len(courts_info)
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@recording_api.route('/stop/<recording_id>', methods=['POST'])
@require_auth
def stop_recording(recording_id: str):
    """Arrête un enregistrement"""
    try:
        # Vérifier les permissions
        # Un utilisateur peut arrêter ses propres enregistrements
        # Un admin de club peut arrêter les enregistrements de son club
        
        status_result = recording_service.get_recording_status(recording_id)
        if not status_result['success']:
            return jsonify(status_result), 404
        
        recording_data = status_result['recording']
        
        # Vérification des permissions
        # Import local pour éviter les imports circulaires
        from ..models.user import User
        
        current_user = User.query.get(session['user_id'])
        can_stop = (
            recording_data['user_id'] == session['user_id'] or  # Propriétaire
            current_user.role.value in ['club', 'super_admin']  # Admin
        )
        
        if not can_stop:
            return jsonify({
                'success': False,
                'error': 'Permissions insuffisantes'
            }), 403
        
        # Arrêter l'enregistrement
        result = recording_service.stop_recording(
            recording_id, 
            stopped_by_user_id=session['user_id']
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erreur stop_recording: {e}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/status/<recording_id>', methods=['GET'])
@require_auth
def get_recording_status(recording_id: str):
    """Récupère le statut d'un enregistrement"""
    try:
        result = recording_service.get_recording_status(recording_id)
        
        if result['success']:
            # Vérifier les permissions de lecture
            # Import local pour éviter les imports circulaires
            from ..models.user import User
            
            recording_data = result['recording']
            current_user = User.query.get(session['user_id'])
            can_view = (
                recording_data['user_id'] == session['user_id'] or
                current_user.role.value in ['club', 'super_admin']
            )
            
            if not can_view:
                return jsonify({
                    'success': False,
                    'error': 'Permissions insuffisantes'
                }), 403
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erreur get_recording_status: {e}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/active', methods=['GET'])
@require_auth
def list_active_recordings():
    """Liste les enregistrements actifs"""
    try:
        # Import local pour éviter les imports circulaires
        from ..models.user import User
        
        # Filtres selon le rôle
        user_id = None
        court_id = request.args.get('court_id', type=int)
        
        # Les utilisateurs normaux ne voient que leurs enregistrements
        current_user = User.query.get(session['user_id'])
        if current_user.role.value == 'player':
            user_id = session['user_id']
        
        recordings = recording_service.list_active_recordings(
            user_id=user_id,
            court_id=court_id
        )
        
        return jsonify({
            'success': True,
            'recordings': recordings,
            'count': len(recordings)
        })
        
    except Exception as e:
        logger.error(f"Erreur list_active_recordings: {e}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/history', methods=['GET'])
@require_auth
def get_recordings_history():
    """Récupère l'historique des enregistrements"""
    try:
        # Paramètres de pagination
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        
        # Filtres
        court_id = request.args.get('court_id', type=int)
        status = request.args.get('status')
        
        # Construction de la requête
        query = Recording.query
        
        # Import local pour éviter les imports circulaires
        from ..models.user import User
        
        # Filtres selon le rôle
        current_user = User.query.get(session['user_id'])
        if current_user.role.value == 'player':
            query = query.filter(Recording.user_id == session['user_id'])
        
        if court_id:
            query = query.filter(Recording.court_id == court_id)
        
        if status:
            query = query.filter(Recording.status == status)
        
        # Tri et pagination
        query = query.order_by(Recording.created_at.desc())
        paginated = query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        return jsonify({
            'success': True,
            'recordings': [r.to_dict() for r in paginated.items],
            'pagination': {
                'page': page,
                'pages': paginated.pages,
                'per_page': per_page,
                'total': paginated.total,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur get_recordings_history: {e}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/club/stop-all', methods=['POST'])
@require_auth
@require_club_admin
def club_stop_all_recordings():
    """Arrête tous les enregistrements actifs (admin club)"""
    try:
        club_id = request.json.get('club_id') if request.json else None
        
        # Récupérer tous les enregistrements actifs
        active_recordings = recording_service.list_active_recordings()
        
        stopped_count = 0
        errors = []
        
        for recording_data in active_recordings:
            # Filtrer par club si spécifié
            if club_id and recording_data.get('club_id') != club_id:
                continue
            
            try:
                result = recording_service.stop_recording(
                    recording_data['recording_id'],
                    stopped_by_user_id=session['user_id']
                )
                if result['success']:
                    stopped_count += 1
                else:
                    errors.append({
                        'recording_id': recording_data['recording_id'],
                        'error': result['error']
                    })
            except Exception as e:
                errors.append({
                    'recording_id': recording_data['recording_id'],
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'stopped_count': stopped_count,
            'errors': errors,
            'message': f'{stopped_count} enregistrement(s) arrêté(s)'
        })
        
    except Exception as e:
        logger.error(f"Erreur club_stop_all_recordings: {e}")
        return jsonify({
            'success': False,
            'error': 'Erreur interne du serveur'
        }), 500


@recording_api.route('/health', methods=['GET'])
def health_check():
    """Point de contrôle de santé du service d'enregistrement"""
    try:
        if recording_service is None:
            return jsonify({
                'status': 'error',
                'message': 'Service non initialisé'
            }), 503
        
        active_count = len(recording_service.list_active_recordings())
        
        return jsonify({
            'status': 'ok',
            'service': 'recording',
            'active_recordings': active_count,
            'max_parallel': recording_service.max_parallel_recordings
        })
        
    except Exception as e:
        logger.error(f"Erreur health_check: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Erreur interne'
        }), 500


@recording_api.route('/test-clubs/<int:club_id>/courts', methods=['GET'])
def test_get_club_courts(club_id):
    """Version de test sans authentification pour diagnostiquer"""
    try:
        # Vérifier que le club existe
        club = Club.query.get(club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        # Récupérer tous les terrains du club
        courts = Court.query.filter_by(club_id=club_id).all()
        
        courts_data = []
        for court in courts:
            court_data = {
                'id': court.id,
                'name': court.name,
                'club_id': court.club_id,
                'qr_code': court.qr_code,
                'camera_url': getattr(court, 'camera_url', None),
                'available': True,  
                'has_camera': hasattr(court, 'camera_url') and bool(court.camera_url)
            }
            courts_data.append(court_data)
        
        return jsonify({
            'courts': courts_data,
            'club_name': club.name,
            'test_mode': True
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors du test des terrains du club {club_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': f'Erreur lors du test: {str(e)}',
            'club_id': club_id
        }), 500


@recording_api.route('/clubs/<int:club_id>/courts', methods=['GET'])
@require_auth
def get_club_courts_for_players(club_id):
    """
    Récupérer les terrains d'un club pour les joueurs
    Accessible à tous les utilisateurs authentifiés
    """
    try:
        # Vérifier que le club existe
        club = Club.query.get(club_id)
        if not club:
            return jsonify({'error': 'Club non trouvé'}), 404
        
        # Récupérer tous les terrains du club
        courts = Court.query.filter_by(club_id=club_id).all()
        
        if not courts:
            return jsonify({'courts': []}), 200
        
        courts_data = []
        for court in courts:
            # Vérifier s'il y a un enregistrement actif sur ce terrain
            active_recording = None
            try:
                active_recording = RecordingSession.query.filter_by(
                    court_id=court.id,
                    status='active'
                ).first()
            except Exception as recording_error:
                logger.warning(f"Erreur lors de la vérification des enregistrements actifs: {recording_error}")
                # Continuer sans la vérification des enregistrements actifs
            
            court_data = {
                'id': court.id,
                'name': court.name,
                'club_id': court.club_id,
                'qr_code': court.qr_code,
                'camera_url': getattr(court, 'camera_url', None),
                'available': True  # Par défaut disponible (changé de is_available à available)
            }
            
            # Vérifier si le terrain a une caméra configurée
            if hasattr(court, 'camera_url') and court.camera_url:
                court_data['has_camera'] = True
            else:
                court_data['has_camera'] = False
                court_data['available'] = False  # Pas disponible sans caméra
            
            # Si il y a un enregistrement actif, le terrain n'est pas disponible
            if active_recording:
                court_data['available'] = False
                court_data['recording_info'] = {
                    'id': active_recording.id,
                    'start_time': active_recording.start_time.isoformat() if active_recording.start_time else None,
                    'status': active_recording.status
                }
            else:
                court_data['recording_info'] = None
            
            courts_data.append(court_data)
        
        return jsonify({
            'courts': courts_data,
            'club_name': club.name
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des terrains du club {club_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': f'Erreur lors de la récupération des terrains: {str(e)}',
            'club_id': club_id
        }), 500


@recording_api.route('/available-courts', methods=['GET'])
@require_auth
def get_all_available_courts():
    """
    Récupérer tous les terrains disponibles pour l'enregistrement
    Accessible à tous les utilisateurs authentifiés
    """
    try:
        # Récupérer tous les clubs avec leurs terrains
        clubs_data = []
        clubs = Club.query.all()
        
        for club in clubs:
            courts = Court.query.filter_by(club_id=club.id).all()
            available_courts = []
            
            for court in courts:
                # Vérifier s'il y a un enregistrement actif sur ce terrain
                active_recording = RecordingSession.query.filter_by(
                    court_id=court.id,
                    status='active'
                ).first()
                
                # Vérifier si le terrain a une caméra configurée ET n'a pas d'enregistrement actif
                if hasattr(court, 'camera_url') and court.camera_url and not active_recording:
                    court_data = {
                        'id': court.id,
                        'name': court.name,
                        'club_id': court.club_id,
                        'qr_code': court.qr_code,
                        'camera_url': court.camera_url,
                        'available': True,  # Changé de is_available à available
                        'has_camera': True,
                        'recording_info': None
                    }
                    available_courts.append(court_data)
            
            if available_courts:  # Seulement inclure les clubs qui ont des terrains disponibles
                clubs_data.append({
                    'id': club.id,
                    'name': club.name,
                    'address': club.address,
                    'courts': available_courts,
                    'courts_count': len(available_courts)
                })
        
        return jsonify({
            'clubs': clubs_data,
            'total_clubs': len(clubs_data),
            'total_courts': sum(club['courts_count'] for club in clubs_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des terrains disponibles: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des terrains'}), 500
