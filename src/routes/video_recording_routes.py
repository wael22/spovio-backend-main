#!/usr/bin/env python3
"""
Video Recording API Routes for PadelVar
Endpoints for managing video recording during matches
"""

from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session, send_file
from src.models.user import db, Match, RecordingStatus, Court, Club, User
from src.services.video_recording_service import get_recording_service
import os
import logging
from pathlib import Path
import requests

# Configuration du logging
logger = logging.getLogger(__name__)

# Blueprint pour les routes d'enregistrement
video_recording_bp = Blueprint('video_recording', __name__)

# Service d'enregistrement
recording_service = get_recording_service()

@video_recording_bp.route('/start_recording', methods=['POST'])
def start_recording():
    """
    Démarrer un enregistrement vidéo pour un match
    
    Body JSON:
    {
        "match_id": 123,
        "duration_minutes": 90,
        "title": "Match amical",
        "quality": "1280x720"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON requises'}), 400
        
        match_id = data.get('match_id')
        if not match_id:
            return jsonify({'error': 'match_id requis'}), 400
        
        # Vérifier que le match existe
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'error': f'Match {match_id} introuvable'}), 404
        
        # Vérifier que le match n'est pas déjà en enregistrement
        if match.recording_status == RecordingStatus.RECORDING:
            return jsonify({'error': 'Enregistrement déjà en cours pour ce match'}), 409
        
        # Paramètres d'enregistrement
        duration_minutes = data.get('duration_minutes', match.planned_duration_minutes or 90)
        title = data.get('title', f"Match {match_id}")
        quality = data.get('quality', '1280x720')
        
        # Démarrer l'enregistrement via le service
        success, message = recording_service.start_recording(
            match_id=str(match_id),
            duration_minutes=duration_minutes,
            title=title,
            quality=quality
        )
        
        if success:
            # Mettre à jour le modèle Match
            match.start_recording()
            db.session.commit()
            
            logger.info(f"✅ Enregistrement démarré pour le match {match_id}")
            return jsonify({
                'success': True,
                'message': message,
                'match_id': match_id,
                'duration_minutes': duration_minutes,
                'status': 'recording'
            })
        else:
            return jsonify({'error': message}), 500
            
    except Exception as e:
        logger.error(f"Erreur lors du démarrage de l'enregistrement: {e}")
        db.session.rollback()
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/stop_recording', methods=['POST'])
def stop_recording():
    """
    Arrêter un enregistrement vidéo en cours
    
    Body JSON:
    {
        "match_id": 123,
        "reason": "manual"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON requises'}), 400
        
        match_id = data.get('match_id')
        if not match_id:
            return jsonify({'error': 'match_id requis'}), 400
        
        # Vérifier que le match existe
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'error': f'Match {match_id} introuvable'}), 404
        
        reason = data.get('reason', 'manual')
        
        # Arrêter l'enregistrement via le service
        success, message = recording_service.stop_recording(
            match_id=str(match_id),
            reason=reason
        )
        
        if success:
            # Obtenir les informations du fichier créé
            recording_status = recording_service.get_recording_status(str(match_id))
            
            # Mettre à jour le modèle Match
            video_path = None
            file_size_mb = None
            
            if recording_status:
                video_path = recording_status.get('output_path')
                if video_path and os.path.exists(video_path):
                    file_size_bytes = os.path.getsize(video_path)
                    file_size_mb = file_size_bytes / (1024 * 1024)  # Convertir en MB
            
            match.stop_recording(
                video_path=video_path,
                file_size_mb=file_size_mb
            )
            db.session.commit()
            
            logger.info(f"✅ Enregistrement arrêté pour le match {match_id}")
            return jsonify({
                'success': True,
                'message': message,
                'match_id': match_id,
                'video_path': video_path,
                'file_size_mb': file_size_mb,
                'status': 'stopped'
            })
        else:
            # Marquer comme erreur
            match.mark_recording_error()
            db.session.commit()
            return jsonify({'error': message}), 500
            
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt de l'enregistrement: {e}")
        db.session.rollback()
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/recording_status/<int:match_id>')
def get_recording_status(match_id):
    """Obtenir le statut d'un enregistrement"""
    try:
        # Vérifier que le match existe
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'error': f'Match {match_id} introuvable'}), 404
        
        # Obtenir le statut depuis le service
        service_status = recording_service.get_recording_status(str(match_id))
        
        # Construire la réponse
        response = {
            'match_id': match_id,
            'recording_status': match.recording_status.value if match.recording_status else 'idle',
            'recording_started_at': match.recording_started_at.isoformat() if match.recording_started_at else None,
            'recording_ended_at': match.recording_ended_at.isoformat() if match.recording_ended_at else None,
            'video_path': match.video_path,
            'video_file_size_mb': match.video_file_size_mb,
            'has_video': bool(match.video_path and os.path.exists(match.video_path) if match.video_path else False)
        }
        
        # Ajouter les informations temps réel si l'enregistrement est en cours
        if service_status:
            response.update({
                'is_active': service_status.get('is_active', False),
                'elapsed_minutes': service_status.get('elapsed_minutes', 0),
                'remaining_minutes': service_status.get('remaining_minutes', 0),
                'duration_minutes': service_status.get('duration_minutes', 0)
            })
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/active_recordings')
def list_active_recordings():
    """Lister tous les enregistrements en cours"""
    try:
        active_recordings = recording_service.list_active_recordings()
        
        # Enrichir avec les informations des matches
        enriched_recordings = []
        for recording in active_recordings:
            match_id = int(recording['match_id'])
            match = Match.query.get(match_id)
            
            if match:
                recording_info = recording.copy()
                recording_info.update({
                    'match_info': {
                        'id': match.id,
                        'title': match.title,
                        'club_id': match.club_id,
                        'court_id': match.court_id,
                        'start_time': match.start_time.isoformat() if match.start_time else None
                    }
                })
                enriched_recordings.append(recording_info)
        
        return jsonify({
            'active_recordings': enriched_recordings,
            'count': len(enriched_recordings)
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des enregistrements actifs: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/set_camera', methods=['POST'])
def set_camera():
    """
    Configurer l'URL de la caméra dans le proxy
    
    Body JSON:
    {
        "camera_url": "http://192.168.1.100:8080/video.mjpg"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON requises'}), 400
        
        camera_url = data.get('camera_url')
        if not camera_url:
            return jsonify({'error': 'camera_url requis'}), 400
        
        # Appeler l'API du proxy vidéo
        try:
            response = requests.post(
                'http://127.0.0.1:8080/api/set_camera',
                json={'url': camera_url},
                timeout=10
            )
            
            if response.status_code == 200:
                proxy_data = response.json()
                logger.info(f"✅ Caméra configurée: {camera_url}")
                return jsonify({
                    'success': True,
                    'message': f'Caméra configurée: {camera_url}',
                    'camera_url': camera_url,
                    'stream_url': proxy_data.get('stream_url'),
                    'proxy_response': proxy_data
                })
            else:
                return jsonify({'error': f'Erreur du proxy: {response.text}'}), 500
                
        except requests.exceptions.ConnectionError:
            return jsonify({'error': 'Proxy vidéo non disponible (port 8080)'}), 503
        except requests.exceptions.Timeout:
            return jsonify({'error': 'Timeout lors de la configuration de la caméra'}), 408
            
    except Exception as e:
        logger.error(f"Erreur lors de la configuration de la caméra: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/proxy_status')
def get_proxy_status():
    """Obtenir le statut du proxy vidéo"""
    try:
        response = requests.get('http://127.0.0.1:8080/api/status', timeout=5)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'error': f'Erreur du proxy: {response.text}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Proxy vidéo non disponible'}), 503
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Timeout du proxy'}), 408
    except Exception as e:
        return jsonify({'error': f'Erreur: {str(e)}'}), 500


@video_recording_bp.route('/video/<int:match_id>')
def serve_video(match_id):
    """Servir le fichier vidéo d'un match"""
    try:
        # Vérifier que le match existe
        match = Match.query.get(match_id)
        if not match:
            return jsonify({'error': f'Match {match_id} introuvable'}), 404
        
        # Vérifier que le fichier vidéo existe
        if not match.video_path or not os.path.exists(match.video_path):
            return jsonify({'error': 'Fichier vidéo introuvable'}), 404
        
        # Servir le fichier
        return send_file(
            match.video_path,
            as_attachment=False,
            mimetype='video/mp4'
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la diffusion de la vidéo: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/create_match', methods=['POST'])
def create_match():
    """
    Créer un nouveau match pour test
    
    Body JSON:
    {
        "club_id": 1,
        "court_id": 1,
        "player1_id": 1,
        "player2_id": 2,
        "title": "Match test",
        "planned_duration_minutes": 90
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Données JSON requises'}), 400
        
        # Validation des champs requis
        required_fields = ['club_id', 'court_id', 'player1_id', 'player2_id']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} requis'}), 400
        
        # Créer le match
        match = Match(
            club_id=data['club_id'],
            court_id=data['court_id'],
            player1_id=data['player1_id'],
            player2_id=data['player2_id'],
            player3_id=data.get('player3_id'),
            player4_id=data.get('player4_id'),
            title=data.get('title', 'Match PadelVar'),
            description=data.get('description'),
            planned_duration_minutes=data.get('planned_duration_minutes', 90),
            start_time=datetime.utcnow()
        )
        
        db.session.add(match)
        db.session.commit()
        
        logger.info(f"✅ Match créé: {match.id}")
        return jsonify({
            'success': True,
            'message': f'Match créé avec succès',
            'match': match.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Erreur lors de la création du match: {e}")
        db.session.rollback()
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@video_recording_bp.route('/matches')
def list_matches():
    """Lister les matches avec leur statut d'enregistrement"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        matches = Match.query.order_by(Match.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        matches_data = []
        for match in matches.items:
            match_dict = match.to_dict()
            # Ajouter des informations supplémentaires
            match_dict['has_video'] = bool(match.video_path and os.path.exists(match.video_path) if match.video_path else False)
            matches_data.append(match_dict)
        
        return jsonify({
            'matches': matches_data,
            'pagination': {
                'page': matches.page,
                'pages': matches.pages,
                'per_page': matches.per_page,
                'total': matches.total,
                'has_prev': matches.has_prev,
                'has_next': matches.has_next
            }
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des matches: {e}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500