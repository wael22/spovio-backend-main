"""
Module de gestion des vidéos et des enregistrements pour l'application PadelVar.
Ce module contient toutes les routes API liées aux vidéos, aux enregistrements, 
et à la gestion des terrains pour les matchs de padel.

La version refactorisée sépare la logique métier des routes API et améliore
la gestion des erreurs et des ressources.
"""

from flask import Blueprint, request, jsonify, session, send_file, Response
from src.models.user import db, User, Video, Court, Club
from src.services.video_capture_service import video_capture_service
from datetime import datetime, timedelta
import os
import io
import logging
import threading
import time
from typing import Dict, Any, Optional, List, Tuple
import json
from functools import wraps

# Configuration du logger
logger = logging.getLogger(__name__)

# Création du Blueprint
videos_bp = Blueprint('videos', __name__)

# ====================================================================
# GESTIONNAIRE D'ENREGISTREMENTS
# ====================================================================

class RecordingManager:
    """
    Classe centralisée pour gérer les enregistrements actifs et leurs timers.
    Cette classe gère la synchronisation, les accès concurrents et le nettoyage
    des ressources pour tous les enregistrements.
    """
    
    def __init__(self):
        """Initialise les dictionnaires pour suivre les enregistrements et leurs timers."""
        self.active_recordings = {}  # Informations sur les enregistrements actifs
        self.recording_timers = {}   # Informations sur les timers des enregistrements
        self.timer_threads = {}      # Threads des timers
        self.lock = threading.RLock()  # Verrou pour protéger les accès concurrents
        
        # Configuration
        self.cleanup_interval = 300  # 5 minutes entre chaque nettoyage
        self.max_timer_age = 3600    # 1 heure max d'âge pour un timer
        
        # Démarrer le thread de nettoyage automatique
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True
        )
        self.cleanup_thread.start()
        
        logger.info("🔧 Gestionnaire d'enregistrements initialisé")
    
    def start_recording(self, session_id: str, court_id: int, user_id: int, 
                        session_name: str, duration_minutes: int) -> None:
        """
        Enregistre une nouvelle session d'enregistrement et démarre son timer.
        
        Args:
            session_id: Identifiant unique de la session d'enregistrement
            court_id: ID du terrain où se déroule l'enregistrement
            user_id: ID de l'utilisateur qui a lancé l'enregistrement
            session_name: Nom de la session (titre du match)
            duration_minutes: Durée prévue de l'enregistrement en minutes
        """
        with self.lock:
            start_time = datetime.now()
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            # Enregistrer les informations de la session
            self.active_recordings[session_id] = {
                'user_id': user_id,
                'court_id': court_id,
                'start_time': start_time,
                'duration_minutes': duration_minutes,
                'session_name': session_name
            }
            
            # Enregistrer les informations du timer
            self.recording_timers[session_id] = {
                'start_time': start_time,
                'end_time': end_time,
                'duration_minutes': duration_minutes,
                'status': 'running'
            }
            
            # Démarrer le timer automatique en arrière-plan
            timer_thread = threading.Thread(
                target=self._auto_stop_recording,
                args=(session_id, court_id, duration_minutes, user_id),
                daemon=True
            )
            timer_thread.start()
            
            # Stocker la référence au thread
            self.timer_threads[session_id] = timer_thread
            
            logger.info(f"⏱️ Enregistrement {session_id} démarré pour {duration_minutes} minutes")
    
    def stop_recording(self, session_id: str) -> None:
        """
        Arrête un enregistrement en cours et met à jour son statut.
        
        Args:
            session_id: Identifiant de la session d'enregistrement à arrêter
        """
        with self.lock:
            # Mettre à jour le statut du timer
            if session_id in self.recording_timers:
                self.recording_timers[session_id]['status'] = 'stopped_manually'
            
            # Supprimer de la liste des enregistrements actifs
            if session_id in self.active_recordings:
                del self.active_recordings[session_id]
            
            logger.info(f"⏹️ Enregistrement {session_id} arrêté manuellement")
    
    def extend_recording(self, session_id: str, additional_minutes: int) -> Optional[datetime]:
        """
        Prolonge la durée d'un enregistrement en cours.
        
        Args:
            session_id: Identifiant de la session d'enregistrement à prolonger
            additional_minutes: Nombre de minutes à ajouter
            
        Returns:
            La nouvelle date de fin ou None si l'enregistrement n'existe pas
        """
        with self.lock:
            if session_id not in self.active_recordings:
                return None
            
            # Prolonger la durée dans le dictionnaire d'enregistrements
            self.active_recordings[session_id]['duration_minutes'] += additional_minutes
            
            # Mettre à jour le timer
            if session_id in self.recording_timers:
                timer_info = self.recording_timers[session_id]
                timer_info['duration_minutes'] += additional_minutes
                timer_info['end_time'] = timer_info['end_time'] + timedelta(minutes=additional_minutes)
                new_end_time = timer_info['end_time']
            else:
                # Si pas de timer, en créer un nouveau
                start_time = self.active_recordings[session_id]['start_time']
                total_minutes = self.active_recordings[session_id]['duration_minutes']
                new_end_time = start_time + timedelta(minutes=total_minutes)
                
                self.recording_timers[session_id] = {
                    'start_time': start_time,
                    'end_time': new_end_time,
                    'duration_minutes': total_minutes,
                    'status': 'running'
                }
            
            logger.info(f"⏱️ Enregistrement {session_id} prolongé de {additional_minutes} minutes")
            return new_end_time
    
    def get_active_recordings(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Récupère la liste des enregistrements actifs pour un utilisateur.
        
        Args:
            user_id: ID de l'utilisateur
            
        Returns:
            Liste des enregistrements actifs avec leurs informations
        """
        with self.lock:
            current_time = datetime.now()
            user_recordings = []
            
            for session_id, recording_info in self.active_recordings.items():
                if recording_info['user_id'] == user_id:
                    # Obtenir les infos du timer s'il existe
                    timer_info = self.recording_timers.get(session_id, {})
                    start_time = timer_info.get('start_time', recording_info['start_time'])
                    end_time = timer_info.get('end_time')
                    duration_minutes = timer_info.get('duration_minutes', recording_info['duration_minutes'])
                    status = timer_info.get('status', 'running')
                    
                    # Calculer les métriques
                    elapsed_minutes = (current_time - start_time).total_seconds() / 60
                    remaining_minutes = 0
                    if end_time:
                        remaining_minutes = max(0, (end_time - current_time).total_seconds() / 60)
                    
                    progress_percent = min(100, (elapsed_minutes / duration_minutes) * 100) if duration_minutes > 0 else 0
                    
                    user_recordings.append({
                        'session_id': session_id,
                        'court_id': recording_info['court_id'],
                        'session_name': recording_info['session_name'],
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat() if end_time else None,
                        'duration_minutes': duration_minutes,
                        'elapsed_minutes': round(elapsed_minutes, 2),
                        'remaining_minutes': round(remaining_minutes, 2),
                        'progress_percent': round(progress_percent, 2),
                        'status': status
                    })
            
            return user_recordings
    
    def get_timer_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations détaillées sur le timer d'un enregistrement.
        
        Args:
            session_id: Identifiant de la session d'enregistrement
            
        Returns:
            Informations sur le timer ou None si le timer n'existe pas
        """
        with self.lock:
            if session_id not in self.recording_timers:
                return None
            
            timer_info = self.recording_timers[session_id]
            current_time = datetime.now()
            
            # Calculer le temps écoulé et restant
            elapsed_seconds = (current_time - timer_info['start_time']).total_seconds()
            remaining_seconds = max(0, (timer_info['end_time'] - current_time).total_seconds())
            
            # Convertir en minutes pour l'interface utilisateur
            elapsed_minutes = elapsed_seconds / 60
            remaining_minutes = remaining_seconds / 60
            progress_percent = min(100, (elapsed_minutes / timer_info['duration_minutes']) * 100)
            
            return {
                'recording_id': session_id,
                'start_time': timer_info['start_time'].isoformat(),
                'end_time': timer_info['end_time'].isoformat(),
                'duration_minutes': timer_info['duration_minutes'],
                'elapsed_minutes': round(elapsed_minutes, 2),
                'remaining_minutes': round(remaining_minutes, 2),
                'progress_percent': round(progress_percent, 2),
                'status': timer_info['status'],
                'current_server_time': current_time.isoformat()
            }
    
    def update_timer_status(self, session_id: str, status: str) -> bool:
        """
        Met à jour le statut d'un timer.
        
        Args:
            session_id: Identifiant de la session d'enregistrement
            status: Nouveau statut du timer ('running', 'stopped', 'completed', 'error', etc.)
            
        Returns:
            True si le timer a été mis à jour, False sinon
        """
        with self.lock:
            if session_id in self.recording_timers:
                self.recording_timers[session_id]['status'] = status
                return True
            return False
    
    def _auto_stop_recording(self, session_id: str, court_id: int, duration_minutes: int, user_id: int) -> None:
        """
        Fonction qui s'exécute en arrière-plan pour arrêter automatiquement 
        l'enregistrement après la durée spécifiée.
        
        Args:
            session_id: Identifiant de la session d'enregistrement
            court_id: ID du terrain
            duration_minutes: Durée de l'enregistrement en minutes
            user_id: ID de l'utilisateur
        """
        try:
            logger.info(f"⏱️ Timer automatique démarré: {session_id} - {duration_minutes} minutes")
            
            # Attendre la durée spécifiée
            time.sleep(duration_minutes * 60)
            
            # Vérifier si l'enregistrement est toujours actif avec le verrou
            with self.lock:
                if session_id not in self.active_recordings:
                    if session_id in self.recording_timers:
                        self.recording_timers[session_id]['status'] = 'canceled'
                    logger.info(f"ℹ️ Enregistrement {session_id} déjà arrêté manuellement")
                    return
            
            logger.info(f"⏹️ Arrêt automatique de l'enregistrement {session_id} après {duration_minutes} minutes")
            
            # Créer une nouvelle session de base de données pour le thread
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from ..models.database import db
            
            # Arrêter l'enregistrement avec le service de capture
            result = video_capture_service.stop_recording(session_id)
            
            # Utiliser une nouvelle session DB pour les opérations de ce thread
            with db.session.begin():
                # Mettre à jour le terrain
                court = Court.query.get(court_id)
                if court:
                    court.is_recording = False
                    court.recording_session_id = None
            
            # Mettre à jour le statut du timer avec le verrou
            with self.lock:
                if session_id in self.recording_timers:
                    self.recording_timers[session_id]['status'] = 'completed'
                
                # Retirer de la liste des enregistrements actifs
                if session_id in self.active_recordings:
                    del self.active_recordings[session_id]
                
                # Retirer le thread
                if session_id in self.timer_threads:
                    del self.timer_threads[session_id]
            
            logger.info(f"✅ Enregistrement {session_id} arrêté automatiquement - durée exacte: {duration_minutes}min")
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'arrêt automatique de l'enregistrement {session_id}: {e}")
            
            # Nettoyer en cas d'erreur avec le verrou
            with self.lock:
                if session_id in self.active_recordings:
                    del self.active_recordings[session_id]
                if session_id in self.recording_timers:
                    self.recording_timers[session_id]['status'] = 'error'
                if session_id in self.timer_threads:
                    del self.timer_threads[session_id]
            
            # Essayer de libérer le terrain même en cas d'erreur
            try:
                with db.session.begin():
                    court = Court.query.get(court_id)
                    if court and court.recording_session_id == session_id:
                        court.is_recording = False
                        court.recording_session_id = None
            except Exception as cleanup_error:
                logger.error(f"❌ Erreur lors du nettoyage du terrain {court_id}: {cleanup_error}")
    
    def _cleanup_loop(self) -> None:
        """
        Boucle de nettoyage qui s'exécute périodiquement pour supprimer 
        les timers expirés et nettoyer les ressources.
        """
        while True:
            try:
                time.sleep(self.cleanup_interval)
                self._cleanup_expired_timers()
            except Exception as e:
                logger.error(f"❌ Erreur dans la boucle de nettoyage: {e}")
    
    def _cleanup_expired_timers(self) -> None:
        """Nettoie les timers expirés et les ressources associées."""
        with self.lock:
            current_time = datetime.now()
            expired_sessions = []
            
            # Identifier les sessions expirées
            for session_id, timer_info in self.recording_timers.items():
                # Vérifier si le timer est terminé depuis longtemps
                if timer_info['status'] in ['completed', 'stopped_manually', 'error', 'canceled']:
                    end_time = timer_info.get('end_time', timer_info['start_time'])
                    if (current_time - end_time).total_seconds() > self.max_timer_age:
                        expired_sessions.append(session_id)
            
            # Nettoyer les sessions expirées
            for session_id in expired_sessions:
                if session_id in self.recording_timers:
                    del self.recording_timers[session_id]
                if session_id in self.active_recordings:
                    del self.active_recordings[session_id]
                if session_id in self.timer_threads:
                    del self.timer_threads[session_id]
                
                logger.info(f"🧹 Timer expiré nettoyé: {session_id}")

# Créer une instance globale du gestionnaire d'enregistrements
recording_manager = RecordingManager()

# ====================================================================
# DÉCORATEURS ET UTILITAIRES
# ====================================================================

def login_required(f):
    """Décorateur pour vérifier que l'utilisateur est authentifié."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_current_user() -> Optional[User]:
    """
    Récupère l'utilisateur actuellement connecté à partir de la session.
    
    Returns:
        L'objet utilisateur ou None si non authentifié
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

def handle_api_error(f):
    """Décorateur pour gérer uniformément les erreurs d'API."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"❌ Erreur API: {e}")
            db.session.rollback()
            return jsonify({'error': f'Une erreur est survenue: {str(e)}'}), 500
    return decorated_function

def api_response(data=None, message=None, status=200, error=None) -> Tuple[dict, int]:
    """
    Crée une réponse d'API standardisée.
    
    Args:
        data: Données à renvoyer
        message: Message de succès ou d'information
        status: Code de statut HTTP
        error: Message d'erreur éventuel
        
    Returns:
        Tuple contenant la réponse JSON et le code de statut
    """
    response = {}
    if data is not None:
        response.update(data)
    if message:
        response['message'] = message
    if error:
        response['error'] = error
    
    return jsonify(response), status

# ====================================================================
# ROUTES POUR LES VIDÉOS
# ====================================================================

@videos_bp.route('/my-videos', methods=['GET'])
@login_required
@handle_api_error
def get_my_videos():
    """Récupère les vidéos de l'utilisateur connecté."""
    user = get_current_user()
    videos = Video.query.filter_by(user_id=user.id).order_by(Video.recorded_at.desc()).all()
    
    # Créer une version sécurisée du to_dict()
    videos_data = []
    for video in videos:
        video_dict = {
            "id": video.id,
            "title": video.title,
            "description": video.description,
            "file_url": video.file_url,
            "thumbnail_url": video.thumbnail_url,
            "duration": getattr(video, 'duration', None),
            "file_size": getattr(video, 'file_size', None),
            "is_unlocked": getattr(video, 'is_unlocked', True),
            "credits_cost": getattr(video, 'credits_cost', 1),
            "recorded_at": video.recorded_at.isoformat() if video.recorded_at else None,
            "created_at": video.created_at.isoformat() if video.created_at else None,
            "user_id": video.user_id,
            "court_id": video.court_id
        }
        videos_data.append(video_dict)
    
    return api_response(data={'videos': videos_data})

@videos_bp.route('/<int:video_id>', methods=['GET'])
@login_required
@handle_api_error
def get_video(video_id):
    """Récupère les détails d'une vidéo spécifique."""
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier que l'utilisateur a accès à cette vidéo
    if video.user_id != user.id and not video.is_unlocked:
        return api_response(error="Accès non autorisé à cette vidéo", status=403)
    
    return api_response(data={'video': video.to_dict()})

@videos_bp.route('/<int:video_id>', methods=['PUT'])
@login_required
@handle_api_error
def update_video(video_id):
    """Met à jour les informations d'une vidéo."""
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier que l'utilisateur est propriétaire de la vidéo
    if video.user_id != user.id:
        return api_response(error="Accès non autorisé", status=403)
    
    data = request.get_json()
    if 'title' in data:
        video.title = data['title']
    if 'description' in data:
        video.description = data['description']
    
    db.session.commit()
    return api_response(data={'video': video.to_dict()}, message="Vidéo mise à jour")

@videos_bp.route('/<int:video_id>', methods=['DELETE'])
@login_required
@handle_api_error
def delete_video(video_id):
    """Supprime une vidéo."""
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier que l'utilisateur est propriétaire de la vidéo
    if video.user_id != user.id:
        return api_response(error="Accès non autorisé", status=403)
    
    db.session.delete(video)
    db.session.commit()
    return api_response(message="Vidéo supprimée")

@videos_bp.route('/<int:video_id>/share', methods=['POST'])
@login_required
@handle_api_error
def share_video(video_id):
    """Génère des liens de partage pour une vidéo."""
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier que l'utilisateur est propriétaire de la vidéo
    if video.user_id != user.id:
        return api_response(error="Accès non autorisé à cette vidéo", status=403)
    
    # Vérifier que la vidéo est déverrouillée
    if not video.is_unlocked:
        return api_response(error="La vidéo doit être déverrouillée pour être partagée", status=400)
    
    data = request.get_json()
    platform = data.get('platform')  # 'facebook', 'instagram', 'youtube'
    
    # Générer les liens de partage
    base_url = request.host_url
    video_url = f"{base_url}videos/{video_id}/watch"
    
    share_urls = {
        'facebook': f"https://www.facebook.com/sharer/sharer.php?u={video_url}",
        'instagram': video_url,  # Instagram nécessite une approche différente
        'youtube': video_url,    # YouTube nécessite l'API YouTube
        'direct': video_url
    }
    
    return api_response(
        data={'share_urls': share_urls, 'video_url': video_url},
        message="Liens de partage générés"
    )

@videos_bp.route('/<int:video_id>/watch', methods=['GET'])
@handle_api_error
def watch_video(video_id):
    """Route publique pour regarder une vidéo partagée."""
    video = Video.query.get_or_404(video_id)
    
    # Vérifier que la vidéo est déverrouillée
    if not video.is_unlocked:
        return api_response(error="Vidéo non disponible", status=403)
    
    # Retourner les informations de la vidéo pour le lecteur
    return api_response(data={
        'video': {
            'id': video.id,
            'title': video.title,
            'description': video.description,
            'file_url': video.file_url,
            'thumbnail_url': video.thumbnail_url,
            'duration': video.duration,
            'recorded_at': video.recorded_at.isoformat() if video.recorded_at else None
        }
    })

@videos_bp.route('/download/<int:video_id>', methods=['GET'])
@login_required
@handle_api_error
def download_video(video_id):
    """Télécharge une vidéo."""
    user = get_current_user()
    video = Video.query.get_or_404(video_id)
    
    # Vérifier les permissions
    if video.user_id != user.id and not video.is_unlocked:
        return api_response(error="Accès non autorisé", status=403)
    
    # Utiliser le proxy de téléchargement pour streamer depuis Bunny CDN
    from ..services.video_download_proxy import download_video_proxy
    return download_video_proxy(video_id, user, video, api_response)


# ====================================================================
# ROUTES POUR LES TERRAINS ET CLUBS
# ====================================================================

@videos_bp.route('/courts/available', methods=['GET'])
@login_required
@handle_api_error
def get_available_courts():
    """Récupère la liste des terrains disponibles pour l'enregistrement."""
    # Récupérer tous les terrains non occupés
    courts = Court.query.filter_by(is_recording=False).all()
    
    # Grouper par club
    courts_by_club = {}
    for court in courts:
        club = Club.query.get(court.club_id)
        if club:
            if club.id not in courts_by_club:
                courts_by_club[club.id] = {
                    'club': club.to_dict(),
                    'courts': []
                }
            courts_by_club[club.id]['courts'].append(court.to_dict())
    
    return api_response(data={
        'available_courts': list(courts_by_club.values()),
        'total_available': len(courts)
    })

@videos_bp.route("/clubs/<int:club_id>/courts", methods=["GET"])
@login_required
@handle_api_error
def get_courts_for_club(club_id):
    """Récupère les terrains d'un club spécifique."""
    courts = Court.query.filter_by(club_id=club_id).all()
    return api_response(data={"courts": [c.to_dict() for c in courts]})

@videos_bp.route('/courts/<int:court_id>/camera-stream', methods=['GET'])
@login_required
@handle_api_error
def get_camera_stream(court_id):
    """Récupère les informations de flux de la caméra d'un terrain."""
    court = Court.query.get_or_404(court_id)
    
    return api_response(data={
        'court_id': court.id,
        'court_name': court.name,
        'camera_url': court.camera_url,
        'stream_type': 'mjpeg'  # Type de flux pour la caméra par défaut
    })

# ====================================================================
# ROUTES POUR LA GESTION D'ENREGISTREMENT
# ====================================================================

@videos_bp.route('/record', methods=['POST'])
@login_required
@handle_api_error
def start_recording():
    """Démarre un nouvel enregistrement avec le service de capture vidéo."""
    user = get_current_user()
    data = request.get_json()
    
    court_id = data.get('court_id')
    session_name = data.get('session_name', f"Match du {datetime.now().strftime('%d/%m/%Y')}")
    duration_minutes = data.get('duration_minutes', 60)  # Durée par défaut : 60 minutes
    
    if not court_id:
        return api_response(error="Le terrain est requis", status=400)
    
    # Vérifier que le terrain existe
    court = Court.query.get(court_id)
    if not court:
        return api_response(error="Terrain non trouvé", status=400)
    
    # Vérifier que le terrain n'est pas déjà en cours d'enregistrement
    if hasattr(court, 'is_recording') and court.is_recording:
        return api_response(error="Ce terrain est déjà en cours d'enregistrement", status=400)
    
    # Démarrer l'enregistrement avec le service de capture
    result = video_capture_service.start_recording(
        court_id=court_id,
        user_id=user.id,
        session_name=session_name
    )
    
    session_id = result['session_id']
    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_minutes)
    
    # Marquer le terrain comme en cours d'enregistrement
    court.is_recording = True
    court.recording_session_id = session_id
    db.session.commit()
    
    # Enregistrer dans le gestionnaire d'enregistrements
    recording_manager.start_recording(
        session_id=session_id,
        court_id=court_id,
        user_id=user.id,
        session_name=session_name,
        duration_minutes=duration_minutes
    )
    
    logger.info(f"🎬 Enregistrement démarré par utilisateur {user.id} sur terrain {court_id} - Durée: {duration_minutes}min")
    
    return api_response(data={
        'session_id': session_id,
        'court_id': court_id,
        'session_name': session_name,
        'camera_url': result['camera_url'],
        'status': 'recording',
        'duration_minutes': duration_minutes,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
        'auto_stop_time': end_time.isoformat()
    }, message="Enregistrement démarré avec succès")

@videos_bp.route('/stop-recording', methods=['POST'])
@login_required
@handle_api_error
def stop_recording():
    """Arrête un enregistrement en cours."""
    user = get_current_user()
    data = request.get_json()
    
    session_id = data.get('session_id')
    court_id = data.get('court_id')
    manual_stop = data.get('manual_stop', True)  # Indique si c'est un arrêt manuel ou automatique
    
    if not session_id:
        return api_response(error="session_id manquant", status=400)
    
    # Vérifier que l'enregistrement appartient à l'utilisateur (sauf arrêt automatique)
    with recording_manager.lock:
        if manual_stop and session_id in recording_manager.active_recordings:
            recording_info = recording_manager.active_recordings[session_id]
            if recording_info['user_id'] != user.id:
                return api_response(error="Vous ne pouvez pas arrêter cet enregistrement", status=403)
    
    # Arrêter l'enregistrement avec le service de capture
    result = video_capture_service.stop_recording(session_id)
    
    if result.get('status') == 'error':
        return api_response(error=result.get('error', "Erreur lors de l'arrêt"), status=500)
    
    # Mettre à jour le terrain
    if court_id:
        court = Court.query.get(court_id)
        if court:
            court.is_recording = False
            court.recording_session_id = None
            db.session.commit()
    
    # Mettre à jour dans le gestionnaire d'enregistrements
    recording_manager.stop_recording(session_id)
    
    # Calculer la durée réelle
    actual_duration = None
    with recording_manager.lock:
        if session_id in recording_manager.active_recordings:
            recording_info = recording_manager.active_recordings[session_id]
            actual_duration = (datetime.now() - recording_info['start_time']).total_seconds() / 60
    
    stop_reason = "manual" if manual_stop else "auto"
    logger.info(f"⏹️ Enregistrement arrêté ({stop_reason}) par utilisateur {user.id}: {session_id}")
    
    return api_response(data={
        'session_id': session_id,
        'status': result.get('status'),
        'video_id': result.get('video_id'),
        'video_filename': result.get('video_filename'),
        'duration': result.get('duration'),
        'actual_duration_minutes': round(actual_duration, 2) if actual_duration else None,
        'file_size': result.get('file_size'),
        'stopped_by': stop_reason
    }, message="Enregistrement arrêté avec succès")

@videos_bp.route('/active-recordings', methods=['GET'])
@login_required
@handle_api_error
def get_active_recordings():
    """Récupère la liste des enregistrements actifs de l'utilisateur."""
    user = get_current_user()
    
    # Utiliser le gestionnaire d'enregistrements
    user_recordings = recording_manager.get_active_recordings(user.id)
    
    return api_response(data={
        'active_recordings': user_recordings,
        'total_active': len(user_recordings)
    })

@videos_bp.route('/recording-timer/<recording_id>', methods=['GET'])
@login_required
@handle_api_error
def get_recording_timer(recording_id):
    """Récupère l'état du compteur d'un enregistrement."""
    # Utiliser le gestionnaire d'enregistrements
    timer_info = recording_manager.get_timer_info(recording_id)
    
    if not timer_info:
        return api_response(
            error="Compteur non trouvé pour cet enregistrement", 
            status=404, 
            data={'recording_id': recording_id}
        )
    
    return api_response(data=timer_info)

@videos_bp.route('/recording/<recording_id>/extend', methods=['POST'])
@login_required
@handle_api_error
def extend_recording(recording_id):
    """Prolonge un enregistrement en cours."""
    user = get_current_user()
    data = request.get_json()
    additional_minutes = data.get('additional_minutes', 30)
    
    # Vérifier que l'enregistrement existe et appartient à l'utilisateur
    with recording_manager.lock:
        if recording_id not in recording_manager.active_recordings:
            return api_response(error="Enregistrement non trouvé ou déjà terminé", status=404)
        
        recording_info = recording_manager.active_recordings[recording_id]
        
        # Vérifier que l'utilisateur est propriétaire
        if recording_info['user_id'] != user.id:
            return api_response(error="Accès non autorisé", status=403)
    
    # Prolonger l'enregistrement
    new_end_time = recording_manager.extend_recording(recording_id, additional_minutes)
    
    if not new_end_time:
        return api_response(error="Erreur lors de la prolongation", status=500)
    
    logger.info(f"⏱️ Enregistrement {recording_id} prolongé de {additional_minutes} minutes par utilisateur {user.id}")
    
    return api_response(
        data={
            'new_duration_minutes': recording_info['duration_minutes'] + additional_minutes,
            'new_end_time': new_end_time.isoformat()
        },
        message=f"Enregistrement prolongé de {additional_minutes} minutes"
    )

@videos_bp.route('/recording/<recording_id>/status', methods=['GET'])
@login_required
@handle_api_error
def get_recording_status_by_id(recording_id):
    """Récupère le statut d'un enregistrement en cours."""
    # Obtenir le statut depuis le service de capture
    status = video_capture_service.get_recording_status(recording_id)
    
    if 'error' in status:
        return api_response(error=status['error'], status=404)
    
    # Ajouter les informations du timer si disponible
    timer_info = recording_manager.get_timer_info(recording_id)
    if timer_info:
        status.update({
            'timer_status': timer_info['status'],
            'elapsed_minutes': timer_info['elapsed_minutes'],
            'remaining_minutes': timer_info['remaining_minutes'],
            'progress_percent': timer_info['progress_percent'],
            'duration_minutes': timer_info['duration_minutes'],
            'end_time': timer_info['end_time']
        })
    
    return api_response(data=status)

@videos_bp.route('/recording/<recording_id>/stop', methods=['POST'])
@login_required
@handle_api_error
def stop_recording_by_id(recording_id):
    """Arrête un enregistrement spécifique par son ID."""
    user = get_current_user()
    
    # Arrêter l'enregistrement avec le service de capture
    result = video_capture_service.stop_recording(recording_id)
    
    if result.get('status') == 'error':
        return api_response(error=result.get('error', "Erreur lors de l'arrêt"), status=500)
    
    # Mettre à jour le terrain qui était en cours d'enregistrement
    court = Court.query.filter_by(recording_session_id=recording_id).first()
    if court:
        court.is_recording = False
        court.recording_session_id = None
        db.session.commit()
    
    # Mettre à jour dans le gestionnaire d'enregistrements
    recording_manager.stop_recording(recording_id)
    
    logger.info(f"⏹️ Enregistrement arrêté par utilisateur {user.id}: {recording_id}")
    
    return api_response(
        data={
            'recording_id': recording_id,
            'status': result.get('status'),
            'video_id': result.get('video_id'),
            'video_filename': result.get('video_filename'),
            'duration': result.get('duration'),
            'file_size': result.get('file_size')
        },
        message="Enregistrement arrêté avec succès"
    )

# ====================================================================
# ROUTES POUR LE PARTAGE DE VIDÉOS
# ====================================================================

@videos_bp.route('/stream/<filename>', methods=['GET'])
@login_required
@handle_api_error
def stream_video(filename):
    """Sert les fichiers vidéo (simulation pour le MVP)."""
    # Créer une réponse de stream vidéo simulée
    def generate_fake_video():
        # Données de test pour simuler une vidéo MP4
        fake_video_data = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + b'\x00' * 1000
        yield fake_video_data
    
    return Response(
        generate_fake_video(),
        mimetype='video/mp4',
        headers={
            'Content-Disposition': f'inline; filename="{filename}"',
            'Accept-Ranges': 'bytes',
            'Content-Length': '1024'
        }
    )

@videos_bp.route('/thumbnail/<filename>', methods=['GET'])
@handle_api_error
def get_thumbnail(filename):
    """Sert les thumbnails (simulation pour le MVP)."""
    # Créer une image placeholder simple (1x1 pixel transparent PNG)
    placeholder_png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x00\x00\x00\x007n\xf9$\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01U\r\r\x82\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    
    return Response(
        placeholder_png,
        mimetype='image/png',
        headers={
            'Content-Disposition': f'inline; filename="{filename}"',
            'Cache-Control': 'public, max-age=3600'
        }
    )

# ====================================================================
# ROUTES POUR LA GESTION DES CRÉDITS
# ====================================================================

@videos_bp.route('/buy-credits', methods=['POST'])
@login_required
@handle_api_error
def buy_credits():
    """Achète des crédits pour débloquer des vidéos."""
    user = get_current_user()
    data = request.get_json()
    credits_to_buy = data.get('credits', 0)
    payment_method = data.get('payment_method', 'simulation')
    
    if credits_to_buy <= 0:
        return api_response(error="Le nombre de crédits doit être positif", status=400)
    
    # Pour le MVP, on simule le paiement
    # Dans une vraie implémentation, on intégrerait un système de paiement
    
    # Ajouter les crédits au solde de l'utilisateur
    user.credits_balance += credits_to_buy
    db.session.commit()
    
    return api_response(
        data={
            'new_balance': user.credits_balance,
            'transaction_id': f'txn_{user.id}_{int(datetime.now().timestamp())}'
        },
        message=f"{credits_to_buy} crédits achetés avec succès"
    )

# ====================================================================
# ROUTES POUR LA GESTION DES QR CODES
# ====================================================================

@videos_bp.route('/qr-scan', methods=['POST'])
@login_required
@handle_api_error
def scan_qr_code():
    """Gère le scan QR code et ouvre la caméra sur mobile."""
    data = request.get_json()
    qr_code = data.get('qr_code')
    
    if not qr_code:
        return api_response(error="QR code requis", status=400)
    
    processed_code = qr_code
    if '/c/' in qr_code:
        processed_code = qr_code.split('/c/')[-1].split('?')[0].split('#')[0]
    
    from sqlalchemy import func
    court = Court.query.filter(
        (Court.qr_code == processed_code) | 
        (func.upper(Court.short_code) == processed_code.upper())
    ).first()
    if not court:
        return api_response(error="QR code invalide ou terrain non trouvé", status=404)
    
    # Récupérer les informations du club
    club = Club.query.get(court.club_id)
    
    return api_response(
        data={
            'court': court.to_dict(),
            'club': club.to_dict() if club else None,
            'camera_url': court.camera_url,
            'can_record': True  # L'utilisateur peut démarrer un enregistrement
        },
        message="QR code scanné avec succès"
    )
import io
import logging
import threading
import time

# Configuration du logger
logger = logging.getLogger(__name__)
videos_bp = Blueprint('videos', __name__)

# ====================================================================
# GESTION DES ENREGISTREMENTS EN MÉMOIRE
# ====================================================================

class RecordingManager:
    """
    Classe responsable de la gestion des enregistrements actifs et de leurs timers.
    Centralise la logique de gestion pour éviter les duplications et améliorer la maintenance.
    """
    def __init__(self):
        self.active_recordings = {}
        self.recording_timers = {}
        self.lock = threading.Lock()  # Pour éviter les conditions de course
    
    def start_recording(self, session_id, user_id, court_id, duration_minutes, session_name):
        """Démarre un nouvel enregistrement et son timer"""
        with self.lock:
            start_time = datetime.now()
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            # Stocker les informations d'enregistrement
            self.active_recordings[session_id] = {
                'user_id': user_id,
                'court_id': court_id,
                'start_time': start_time,
                'duration_minutes': duration_minutes,
                'session_name': session_name
            }
            
            # Initialiser le timer
            self.recording_timers[session_id] = {
                'start_time': start_time,
                'end_time': end_time,
                'duration_minutes': duration_minutes,
                'status': 'running'
            }
            
            return {
                'session_id': session_id,
                'start_time': start_time,
                'end_time': end_time
            }
    
    def stop_recording(self, session_id, stopped_by='manual'):
        """Arrête un enregistrement actif"""
        with self.lock:
            recording_info = self.active_recordings.get(session_id)
            if not recording_info:
                return None
            
            # Mettre à jour le statut du timer
            if session_id in self.recording_timers:
                if stopped_by == 'manual':
                    self.recording_timers[session_id]['status'] = 'stopped_manually'
                else:
                    self.recording_timers[session_id]['status'] = 'completed'
            
            # Calculer la durée réelle
            actual_duration = None
            if recording_info:
                actual_duration = (datetime.now() - recording_info['start_time']).total_seconds() / 60
                
            # Retirer de la liste des enregistrements actifs
            del self.active_recordings[session_id]
            
            return {
                'recording_info': recording_info,
                'actual_duration': actual_duration
            }
    
    def get_timer_info(self, recording_id):
        """Récupère les informations du timer pour un enregistrement"""
        with self.lock:
            if recording_id not in self.recording_timers:
                return None
            
            timer_info = self.recording_timers[recording_id].copy()
            current_time = datetime.now()
            
            # Calculer le temps écoulé et restant
            elapsed_seconds = (current_time - timer_info['start_time']).total_seconds()
            remaining_seconds = max(0, (timer_info['end_time'] - current_time).total_seconds())
            
            # Convertir en minutes pour l'interface utilisateur
            elapsed_minutes = elapsed_seconds / 60
            remaining_minutes = remaining_seconds / 60
            progress_percent = min(100, (elapsed_minutes / timer_info['duration_minutes']) * 100)
            
            return {
                'recording_id': recording_id,
                'start_time': timer_info['start_time'].isoformat(),
                'end_time': timer_info['end_time'].isoformat(),
                'duration_minutes': timer_info['duration_minutes'],
                'elapsed_minutes': round(elapsed_minutes, 2),
                'remaining_minutes': round(remaining_minutes, 2),
                'progress_percent': round(progress_percent, 2),
                'status': timer_info['status'],
                'current_server_time': current_time.isoformat()
            }
    
    def extend_recording(self, recording_id, additional_minutes):
        """Prolonge la durée d'un enregistrement actif"""
        with self.lock:
            if recording_id not in self.active_recordings:
                return None
            
            recording_info = self.active_recordings[recording_id]
            recording_info['duration_minutes'] += additional_minutes
            
            # Mettre à jour le timer
            if recording_id in self.recording_timers:
                timer_info = self.recording_timers[recording_id]
                timer_info['duration_minutes'] += additional_minutes
                timer_info['end_time'] = timer_info['end_time'] + timedelta(minutes=additional_minutes)
                new_end_time = timer_info['end_time']
            else:
                new_end_time = datetime.now() + timedelta(minutes=recording_info['duration_minutes'])
            
            return {
                'new_duration_minutes': recording_info['duration_minutes'],
                'new_end_time': new_end_time
            }
    
    def get_user_recordings(self, user_id):
        """Récupère tous les enregistrements actifs d'un utilisateur"""
        with self.lock:
            user_recordings = []
            current_time = datetime.now()
            
            for session_id, recording_info in self.active_recordings.items():
                if recording_info['user_id'] == user_id:
                    # Obtenir les infos du timer
                    timer_info = self.recording_timers.get(session_id, {})
                    start_time = timer_info.get('start_time', recording_info['start_time'])
                    end_time = timer_info.get('end_time')
                    duration_minutes = timer_info.get('duration_minutes', recording_info['duration_minutes'])
                    status = timer_info.get('status', 'running')
                    
                    elapsed_minutes = (current_time - start_time).total_seconds() / 60
                    remaining_minutes = 0
                    if end_time:
                        remaining_minutes = max(0, (end_time - current_time).total_seconds() / 60)
                    
                    progress_percent = min(100, (elapsed_minutes / duration_minutes) * 100) if duration_minutes > 0 else 0
                    
                    user_recordings.append({
                        'session_id': session_id,
                        'court_id': recording_info['court_id'],
                        'session_name': recording_info['session_name'],
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat() if end_time else None,
                        'duration_minutes': duration_minutes,
                        'elapsed_minutes': round(elapsed_minutes, 2),
                        'remaining_minutes': round(remaining_minutes, 2),
                        'progress_percent': round(progress_percent, 2),
                        'status': status
                    })
            
            return user_recordings
    
    def belongs_to_user(self, session_id, user_id):
        """Vérifie si un enregistrement appartient à un utilisateur spécifique"""
        with self.lock:
            if session_id not in self.active_recordings:
                return False
            return self.active_recordings[session_id]['user_id'] == user_id
    
    def clean_old_timers(self, max_age_hours=24):
        """Nettoie les anciens timers pour éviter la croissance indéfinie"""
        with self.lock:
            current_time = datetime.now()
            sessions_to_remove = []
            
            # Identifier les sessions terminées et anciennes
            for session_id, timer_info in self.recording_timers.items():
                if timer_info['status'] in ['completed', 'stopped_manually', 'error', 'canceled']:
                    age = (current_time - timer_info['end_time']).total_seconds() / 3600
                    if age > max_age_hours:
                        sessions_to_remove.append(session_id)
            
            # Supprimer les sessions
            for session_id in sessions_to_remove:
                if session_id in self.recording_timers:
                    del self.recording_timers[session_id]
            
            return len(sessions_to_remove)

# Initialiser le gestionnaire d'enregistrements
recording_manager = RecordingManager()

# Planifier un nettoyage périodique des anciens timers
def schedule_timer_cleanup():
    """Fonction pour planifier le nettoyage périodique des anciens timers"""
    recording_manager.clean_old_timers()
    # Replanifier toutes les 6 heures
    threading.Timer(6 * 60 * 60, schedule_timer_cleanup).start()

# Démarrer le nettoyage périodique
schedule_timer_cleanup()

def auto_stop_recording(session_id, court_id, duration_minutes, user_id):
    """
    Fonction qui s'exécute en arrière-plan pour arrêter automatiquement l'enregistrement
    après la durée spécifiée
    """
    try:
        logger.info(f"⏱️ Timer automatique démarré: {session_id} - {duration_minutes} minutes")
        
        # Attendre la durée spécifiée précisément
        time.sleep(duration_minutes * 60)
        
        # Vérifier si l'enregistrement est toujours actif
        if session_id in recording_manager.active_recordings:
            logger.info(f"⏹️ Arrêt automatique de l'enregistrement {session_id} après {duration_minutes} minutes")
            
            # Arrêter l'enregistrement avec le service de capture
            result = video_capture_service.stop_recording(session_id)
            
            # Utiliser une nouvelle session DB pour les opérations de ce thread
            with db.session.begin():
                # Mettre à jour le terrain
                court = Court.query.get(court_id)
                if court:
                    court.is_recording = False
                    court.recording_session_id = None
            
            # Mettre à jour les informations d'enregistrement
            recording_manager.stop_recording(session_id, stopped_by='auto')
            
            logger.info(f"✅ Enregistrement {session_id} arrêté automatiquement - durée exacte: {duration_minutes}min")
        else:
            logger.info(f"ℹ️ Enregistrement {session_id} déjà arrêté manuellement")
            
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'arrêt automatique: {e}")
        
        # Essayer de libérer le terrain même en cas d'erreur
        try:
            with db.session.begin():
                court = Court.query.get(court_id)
                if court and court.recording_session_id == session_id:
                    court.is_recording = False
                    court.recording_session_id = None
        except Exception as cleanup_error:
            logger.error(f"❌ Erreur lors du nettoyage du terrain {court_id}: {cleanup_error}")


# ====================================================================
# FONCTIONS UTILITAIRES
# ====================================================================

def get_current_user():
    """Récupère l'utilisateur actuellement connecté"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)


# ====================================================================
# ROUTES API POUR LES VIDÉOS
# ====================================================================

@videos_bp.route('/my-videos', methods=['GET'])
def get_my_videos():
    """Récupérer les vidéos de l'utilisateur courant"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        videos = Video.query.filter_by(user_id=user.id).order_by(Video.recorded_at.desc()).all()
        
        # Créer une version sécurisée du to_dict()
        videos_data = []
        for video in videos:
            video_dict = {
                "id": video.id,
                "title": video.title,
                "description": video.description,
                "file_url": video.file_url,
                "thumbnail_url": video.thumbnail_url,
                "duration": getattr(video, 'duration', None),
                "file_size": getattr(video, 'file_size', None),
                "is_unlocked": getattr(video, 'is_unlocked', True),
                "credits_cost": getattr(video, 'credits_cost', 1),
                "recorded_at": video.recorded_at.isoformat() if video.recorded_at else None,
                "created_at": video.created_at.isoformat() if video.created_at else None,
                "user_id": video.user_id,
                "court_id": video.court_id
            }
            videos_data.append(video_dict)
        
        return jsonify({'videos': videos_data}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des vidéos: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des vidéos'}), 500


@videos_bp.route('/record', methods=['POST'])
def start_recording():
    """Démarrage d'enregistrement avec service de capture vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    data = request.get_json()
    court_id = data.get('court_id')
    session_name = data.get('session_name', f"Match du {datetime.now().strftime('%d/%m/%Y')}")
    duration_minutes = data.get('duration_minutes', 60)  # Durée par défaut : 60 minutes
    
    if not court_id:
        return jsonify({'error': 'Le terrain est requis'}), 400
    
    try:
        # Vérifier que le terrain existe
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 400
        
        # Vérifier que le terrain n'est pas déjà en cours d'enregistrement
        if hasattr(court, 'is_recording') and court.is_recording:
            return jsonify({'error': 'Ce terrain est déjà en cours d\'enregistrement'}), 400
        
        # Démarrer l'enregistrement avec le service de capture
        result = video_capture_service.start_recording(
            court_id=court_id,
            user_id=user.id,
            session_name=session_name
        )
        
        session_id = result['session_id']
        
        # Marquer le terrain comme en cours d'enregistrement
        court.is_recording = True
        court.recording_session_id = session_id
        db.session.commit()
        
        # Initialiser l'enregistrement dans le gestionnaire
        recording_info = recording_manager.start_recording(
            session_id=session_id,
            user_id=user.id,
            court_id=court_id,
            duration_minutes=duration_minutes,
            session_name=session_name
        )
        
        # Démarrer le timer automatique en arrière-plan
        timer_thread = threading.Thread(
            target=auto_stop_recording,
            args=(session_id, court_id, duration_minutes, user.id),
            daemon=True  # Le thread se termine quand l'application se ferme
        )
        timer_thread.start()
        
        logger.info(f"🎬 Enregistrement démarré: user={user.id}, terrain={court_id}, durée={duration_minutes}min")
        
        return jsonify({
            'message': 'Enregistrement démarré avec succès',
            'session_id': session_id,
            'court_id': court_id,
            'session_name': session_name,
            'camera_url': result['camera_url'],
            'status': 'recording',
            'duration_minutes': duration_minutes,
            'start_time': recording_info['start_time'].isoformat(),
            'end_time': recording_info['end_time'].isoformat(),
            'auto_stop_time': recording_info['end_time'].isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors du démarrage: {e}")
        return jsonify({'error': f'Erreur lors du démarrage: {str(e)}'}), 500


@videos_bp.route('/stop-recording', methods=['POST'])
def stop_recording():
    """Arrêter l'enregistrement avec service de capture vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    data = request.get_json()
    session_id = data.get('session_id')
    court_id = data.get('court_id')
    manual_stop = data.get('manual_stop', True)
    
    if not session_id:
        return jsonify({'error': 'session_id manquant'}), 400
    
    try:
        # Vérifier que l'enregistrement appartient à l'utilisateur (sauf arrêt automatique)
        if manual_stop and not recording_manager.belongs_to_user(session_id, user.id):
            return jsonify({'error': 'Vous ne pouvez pas arrêter cet enregistrement'}), 403
        
        # Arrêter l'enregistrement avec le service de capture
        result = video_capture_service.stop_recording(session_id)
        
        if result.get('status') == 'error':
            return jsonify({'error': result.get('error', 'Erreur lors de l\'arrêt')}), 500
        
        # Mettre à jour le terrain
        if court_id:
            court = Court.query.get(court_id)
            if court:
                court.is_recording = False
                court.recording_session_id = None
                db.session.commit()
        
        # Arrêter l'enregistrement dans le gestionnaire
        stop_info = recording_manager.stop_recording(
            session_id=session_id, 
            stopped_by='manual' if manual_stop else 'auto'
        )
        
        if not stop_info:
            return jsonify({'error': 'Enregistrement non trouvé'}), 404
        
        recording_info = stop_info['recording_info']
        actual_duration = stop_info['actual_duration']
        
        stop_reason = "manual" if manual_stop else "auto"
        
        logger.info(f"⏹️ Enregistrement arrêté ({stop_reason}) par utilisateur {user.id}: {session_id}")
        
        return jsonify({
            'message': 'Enregistrement arrêté avec succès',
            'session_id': session_id,
            'status': result.get('status'),
            'video_id': result.get('video_id'),
            'video_filename': result.get('video_filename'),
            'duration': result.get('duration'),
            'actual_duration_minutes': round(actual_duration, 2) if actual_duration else None,
            'file_size': result.get('file_size'),
            'stopped_by': stop_reason
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors de l'arrêt: {e}")
        return jsonify({"error": f"Erreur lors de l'arrêt: {str(e)}"}), 500


@videos_bp.route('/active-recordings', methods=['GET'])
def get_active_recordings():
    """Obtenir la liste des enregistrements actifs"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Récupérer les enregistrements de l'utilisateur
        user_recordings = recording_manager.get_user_recordings(user.id)
        
        return jsonify({
            'active_recordings': user_recordings,
            'total_active': len(user_recordings)
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des enregistrements actifs: {e}")
        return jsonify({'error': 'Erreur lors de la récupération des enregistrements actifs'}), 500


@videos_bp.route('/recording-timer/<recording_id>', methods=['GET'])
def get_recording_timer(recording_id):
    """Obtenir l'état du compteur d'un enregistrement"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Récupérer les informations du timer
        timer_info = recording_manager.get_timer_info(recording_id)
        
        if not timer_info:
            return jsonify({
                'error': 'Compteur non trouvé pour cet enregistrement',
                'recording_id': recording_id
            }), 404
        
        return jsonify(timer_info), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du compteur: {e}")
        return jsonify({'error': f'Erreur lors de la récupération du compteur: {str(e)}'}), 500


@videos_bp.route('/recording/<recording_id>/extend', methods=['POST'])
def extend_recording(recording_id):
    """Prolonger un enregistrement en cours"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    data = request.get_json()
    additional_minutes = data.get('additional_minutes', 30)
    
    try:
        # Vérifier que l'enregistrement appartient à l'utilisateur
        if not recording_manager.belongs_to_user(recording_id, user.id):
            return jsonify({'error': 'Accès non autorisé'}), 403
        
        # Prolonger l'enregistrement
        extend_info = recording_manager.extend_recording(recording_id, additional_minutes)
        
        if not extend_info:
            return jsonify({'error': 'Enregistrement non trouvé ou déjà terminé'}), 404
        
        logger.info(f"⏱️ Enregistrement {recording_id} prolongé de {additional_minutes} minutes par utilisateur {user.id}")
        
        return jsonify({
            'message': f'Enregistrement prolongé de {additional_minutes} minutes',
            'new_duration_minutes': extend_info['new_duration_minutes'],
            'new_end_time': extend_info['new_end_time'].isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la prolongation: {e}")
        return jsonify({'error': 'Erreur lors de la prolongation'}), 500


@videos_bp.route('/<int:video_id>', methods=['DELETE'])
def delete_video(video_id):
    """Supprimer une vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        video = Video.query.get_or_404(video_id)
        
        # Vérifier que la vidéo appartient à l'utilisateur
        if video.user_id != user.id:
            return jsonify({'error': 'Accès non autorisé'}), 403
        
        db.session.delete(video)
        db.session.commit()
        
        logger.info(f"🗑️ Vidéo {video_id} supprimée par utilisateur {user.id}")
        
        return jsonify({'message': 'Vidéo supprimée'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors de la suppression: {e}")
        return jsonify({"error": "Erreur lors de la suppression"}), 500


# ====================================================================
# ROUTES API POUR LES TERRAINS ET CLUBS
# ====================================================================

@videos_bp.route("/clubs/<int:club_id>/courts", methods=["GET"])
def get_courts_for_club(club_id):
    """Récupérer les terrains d'un club"""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Accès non autorisé"}), 401
    
    try:
        courts = Court.query.filter_by(club_id=club_id).all()
        return jsonify({"courts": [c.to_dict() for c in courts]}), 200
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des terrains: {e}")
        return jsonify({"error": f"Erreur lors de la récupération des terrains: {str(e)}"}), 500


@videos_bp.route('/courts/available', methods=['GET'])
def get_available_courts():
    """Obtenir la liste des terrains disponibles pour l'enregistrement"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Récupérer tous les terrains non occupés
        courts = Court.query.filter_by(is_recording=False).all()
        
        # Grouper par club
        courts_by_club = {}
        for court in courts:
            club = Club.query.get(court.club_id)
            if club:
                if club.id not in courts_by_club:
                    courts_by_club[club.id] = {
                        'club': club.to_dict(),
                        'courts': []
                    }
                courts_by_club[club.id]['courts'].append(court.to_dict())
        
        return jsonify({
            'available_courts': list(courts_by_club.values()),
            'total_available': len(courts)
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération des terrains disponibles: {e}")
        return jsonify({'error': f'Erreur lors de la récupération des terrains: {str(e)}'}), 500


@videos_bp.route('/courts/<int:court_id>/camera-stream', methods=['GET'])
def get_camera_stream(court_id):
    """Endpoint pour récupérer le flux de la caméra d'un terrain"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        court = Court.query.get(court_id)
        if not court:
            return jsonify({'error': 'Terrain non trouvé'}), 404
        
        return jsonify({
            'court_id': court.id,
            'court_name': court.name,
            'camera_url': court.camera_url,
            'stream_type': 'mjpeg'  # Type de flux pour la caméra par défaut
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du flux caméra: {e}")
        return jsonify({'error': 'Erreur lors de la récupération du flux caméra'}), 500


# ====================================================================
# ROUTES API POUR LE PARTAGE DE VIDÉOS
# ====================================================================

@videos_bp.route('/<int:video_id>/share', methods=['POST'])
def share_video(video_id):
    """Partager une vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Vidéo non trouvée'}), 404
        
        # Vérifier que la vidéo appartient à l'utilisateur et est déverrouillée
        if video.user_id != user.id:
            return jsonify({'error': 'Accès non autorisé à cette vidéo'}), 403
        
        if not video.is_unlocked:
            return jsonify({'error': 'La vidéo doit être déverrouillée pour être partagée'}), 400
        
        data = request.get_json()
        platform = data.get('platform')  # 'facebook', 'instagram', 'youtube'
        
        # Générer les liens de partage
        base_url = request.host_url
        video_url = f"{base_url}videos/{video_id}/watch"
        
        share_urls = {
            'facebook': f"https://www.facebook.com/sharer/sharer.php?u={video_url}",
            'instagram': video_url,  # Instagram nécessite une approche différente
            'youtube': video_url,  # YouTube nécessite l'API YouTube
            'direct': video_url
        }
        
        return jsonify({
            'message': 'Liens de partage générés',
            'share_urls': share_urls,
            'video_url': video_url
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la génération des liens de partage: {e}")
        return jsonify({'error': 'Erreur lors de la génération des liens de partage'}), 500


@videos_bp.route('/<int:video_id>/watch', methods=['GET'])
def watch_video(video_id):
    """Route publique pour regarder une vidéo partagée"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Vidéo non trouvée'}), 404
        
        if not video.is_unlocked:
            return jsonify({'error': 'Vidéo non disponible'}), 403
        
        # Retourner les informations de la vidéo pour le lecteur
        return jsonify({
            'video': {
                'id': video.id,
                'title': video.title,
                'description': video.description,
                'file_url': video.file_url,
                'thumbnail_url': video.thumbnail_url,
                'duration': video.duration,
                'recorded_at': video.recorded_at.isoformat() if video.recorded_at else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la lecture de la vidéo: {e}")
        return jsonify({'error': 'Erreur lors de la lecture de la vidéo'}), 500


# ====================================================================
# ROUTES API POUR LA GESTION DES CRÉDITS
# ====================================================================

@videos_bp.route('/buy-credits', methods=['POST'])
def buy_credits():
    """Acheter des crédits"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.get_json()
        credits_to_buy = data.get('credits', 0)
        payment_method = data.get('payment_method', 'simulation')
        
        if credits_to_buy <= 0:
            return jsonify({'error': 'Le nombre de crédits doit être positif'}), 400
        
        # Pour le MVP, on simule le paiement
        # Dans une vraie implémentation, on intégrerait un système de paiement
        
        # Ajouter les crédits au solde de l'utilisateur
        user.credits_balance += credits_to_buy
        db.session.commit()
        
        transaction_id = f'txn_{user.id}_{int(datetime.now().timestamp())}'
        
        logger.info(f"💰 Achat de {credits_to_buy} crédits par utilisateur {user.id} - Transaction: {transaction_id}")
        
        return jsonify({
            'message': f'{credits_to_buy} crédits achetés avec succès',
            'new_balance': user.credits_balance,
            'transaction_id': transaction_id
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors de l'achat de crédits: {e}")
        return jsonify({'error': 'Erreur lors de l\'achat de crédits'}), 500


# ====================================================================
# ROUTES API POUR LA GESTION DES QR CODES
# ====================================================================

@videos_bp.route('/qr-scan', methods=['POST'])
def scan_qr_code():
    """Endpoint pour gérer le scan QR code et ouvrir la caméra sur mobile"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        data = request.get_json()
        qr_code = data.get('qr_code')
        
        if not qr_code:
            return jsonify({'error': 'QR code requis'}), 400
        
        # Rechercher le terrain correspondant au QR code ou au short code
        processed_code = qr_code
        if '/c/' in qr_code:
            processed_code = qr_code.split('/c/')[-1].split('?')[0].split('#')[0]
            
        from sqlalchemy import func
        court = Court.query.filter(
            (Court.qr_code == processed_code) | 
            (func.upper(Court.short_code) == processed_code.upper())
        ).first()
        if not court:
            return jsonify({'error': 'QR code invalide ou terrain non trouvé'}), 404
        
        # Récupérer les informations du club
        club = Club.query.get(court.club_id)
        
        return jsonify({
            'message': 'QR code scanné avec succès',
            'court': court.to_dict(),
            'club': club.to_dict() if club else None,
            'camera_url': court.camera_url,
            'can_record': True  # L'utilisateur peut démarrer un enregistrement
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du scan du QR code: {e}")
        return jsonify({'error': 'Erreur lors du scan du QR code'}), 500


# ====================================================================
# ROUTES API POUR LA GESTION DES ENREGISTREMENTS
# ====================================================================

@videos_bp.route('/recording/<recording_id>/status', methods=['GET'])
def get_recording_status_by_id(recording_id):
    """Obtenir le statut d'un enregistrement en cours avec le service de capture"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Obtenir le statut depuis le service de capture
        status = video_capture_service.get_recording_status(recording_id)
        
        if 'error' in status:
            return jsonify(status), 404
        
        # Ajouter les informations du timer si disponible
        timer_info = recording_manager.get_timer_info(recording_id)
        
        if timer_info:
            # Ajouter les informations du timer au statut
            status.update({
                'timer_status': timer_info['status'],
                'elapsed_minutes': timer_info['elapsed_minutes'],
                'remaining_minutes': timer_info['remaining_minutes'],
                'progress_percent': timer_info['progress_percent'],
                'duration_minutes': timer_info['duration_minutes'],
                'end_time': timer_info['end_time']
            })
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de la récupération du statut: {e}")
        return jsonify({'error': 'Erreur lors de la récupération du statut'}), 500


@videos_bp.route('/recording/<recording_id>/stop', methods=['POST'])
def stop_recording_by_id(recording_id):
    """Arrêter un enregistrement spécifique par son ID avec le service de capture"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Arrêter l'enregistrement avec le service de capture
        result = video_capture_service.stop_recording(recording_id)
        
        if result.get('status') == 'error':
            return jsonify({'error': result.get('error', 'Erreur lors de l\'arrêt')}), 500
        
        # Mettre à jour le terrain qui était en cours d'enregistrement
        court = Court.query.filter_by(recording_session_id=recording_id).first()
        if court:
            court.is_recording = False
            court.recording_session_id = None
            db.session.commit()
        
        # Arrêter l'enregistrement dans le gestionnaire
        recording_manager.stop_recording(recording_id, stopped_by='manual')
        
        logger.info(f"⏹️ Enregistrement arrêté par utilisateur {user.id}: {recording_id}")
        
        return jsonify({
            'message': 'Enregistrement arrêté avec succès',
            'recording_id': recording_id,
            'status': result.get('status'),
            'video_id': result.get('video_id'),
            'video_filename': result.get('video_filename'),
            'duration': result.get('duration'),
            'file_size': result.get('file_size')
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors de l'arrêt de l'enregistrement {recording_id}: {e}")
        return jsonify({'error': f'Erreur lors de l\'arrêt: {str(e)}'}), 500


# ====================================================================
# ROUTES API POUR LA GESTION DES VIDÉOS
# ====================================================================

@videos_bp.route('/<int:video_id>', methods=['PUT'])
def update_video(video_id):
    """Mettre à jour les informations d'une vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        video = Video.query.get_or_404(video_id)
        
        # Vérifier que la vidéo appartient à l'utilisateur
        if video.user_id != user.id:
            return jsonify({'error': 'Accès non autorisé'}), 403
            
        data = request.get_json()
        if 'title' in data:
            video.title = data['title']
        if 'description' in data:
            video.description = data['description']
        
        db.session.commit()
        
        logger.info(f"✏️ Vidéo {video_id} mise à jour par utilisateur {user.id}")
        
        return jsonify({'message': 'Vidéo mise à jour', 'video': video.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"❌ Erreur lors de la mise à jour de la vidéo: {e}")
        return jsonify({"error": "Erreur lors de la mise à jour"}), 500


# ====================================================================
# ROUTES API POUR SERVIR LES VIDÉOS ET THUMBNAILS
# ====================================================================

@videos_bp.route('/stream/<filename>', methods=['GET'])
def stream_video(filename):
    """Servir les fichiers vidéo (simulation pour le MVP)"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        # Pour le MVP, on génère une vidéo de test
        # Dans la vraie implémentation, on servirait le fichier réel
        
        # Créer une réponse de stream vidéo simulée
        def generate_fake_video():
            # Données de test pour simuler une vidéo MP4
            # En production, on lirait le vrai fichier
            fake_video_data = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + b'\x00' * 1000
            yield fake_video_data
        
        return Response(
            generate_fake_video(),
            mimetype='video/mp4',
            headers={
                'Content-Disposition': f'inline; filename="{filename}"',
                'Accept-Ranges': 'bytes',
                'Content-Length': '1024'
            }
        )
    except Exception as e:
        logger.error(f"❌ Erreur lors du streaming vidéo: {e}")
        return jsonify({'error': 'Erreur lors du streaming vidéo'}), 500


@videos_bp.route('/thumbnail/<filename>', methods=['GET'])
def get_thumbnail(filename):
    """Servir les thumbnails (simulation pour le MVP)"""
    try:
        # Pour le MVP, on génère une image de placeholder
        # Dans la vraie implémentation, on servirait la vraie thumbnail
        
        # Créer une image placeholder simple (1x1 pixel transparent PNG)
        placeholder_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x01\x00\x00\x00\x007n\xf9$\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01U\r\r\x82\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        
        return Response(
            placeholder_png,
            mimetype='image/png',
            headers={
                'Content-Disposition': f'inline; filename="{filename}"',
                'Cache-Control': 'public, max-age=3600'
            }
        )
    except Exception as e:
        logger.error(f"❌ Erreur lors du chargement de la thumbnail: {e}")
        return jsonify({'error': 'Erreur lors du chargement de la thumbnail'}), 500


@videos_bp.route('/download/<int:video_id>', methods=['GET'])
def download_video(video_id):
    """Télécharger une vidéo"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Non authentifié'}), 401
    
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'error': 'Vidéo non trouvée'}), 404
        
        # Vérifier les permissions
        if video.user_id != user.id and not video.is_unlocked:
            return jsonify({'error': 'Accès non autorisé'}), 403
        
        # Utiliser le proxy de téléchargement pour streamer depuis Bunny CDN
        from ..services.video_download_proxy import download_video_proxy
        return download_video_proxy(video_id, user, video, lambda **kwargs: (jsonify(kwargs), kwargs.get('status', 200)))
    except Exception as e:
        logger.error(f"❌ Erreur lors du téléchargement de la vidéo: {e}")
        return jsonify({'error': 'Erreur lors du téléchargement'}), 500

