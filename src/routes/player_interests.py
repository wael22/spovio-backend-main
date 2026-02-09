"""
Routes API pour player_interests
Gestion des joueurs intéressés par la plateforme
"""

from flask import Blueprint, jsonify, request
from src.models.database import db
from sqlalchemy import text
from datetime import datetime

# Créer le blueprint
player_interests_bp = Blueprint('player_interests', __name__)


@player_interests_bp.route('/player-interests', methods=['GET'])
def get_all_players():
    """Récupérer tous les joueurs intéressés"""
    try:
        query = text("""
            SELECT id, first_name, last_name, phone, age, sport, city, created_at
            FROM player_interests
            ORDER BY created_at DESC
        """)
        
        result = db.session.execute(query)
        players = []
        
        for row in result:
            players.append({
                'id': str(row.id),
                'first_name': row.first_name,
                'last_name': row.last_name,
                'phone': row.phone,
                'age': row.age,
                'sport': row.sport,
                'city': row.city,
                'created_at': row.created_at.isoformat() if row.created_at else None
            })
        
        return jsonify(players), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des joueurs: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500


@player_interests_bp.route('/player-interests/<int:player_id>', methods=['GET'])
def get_player(player_id):
    """Récupérer un joueur spécifique"""
    try:
        query = text("""
            SELECT id, first_name, last_name, phone, age, sport, city, created_at
            FROM player_interests
            WHERE id = :id
        """)
        
        result = db.session.execute(query, {'id': player_id}).fetchone()
        
        if not result:
            return jsonify({'error': 'Joueur non trouvé'}), 404
        
        player = {
            'id': str(result.id),
            'first_name': result.first_name,
            'last_name': result.last_name,
            'phone': result.phone,
            'age': result.age,
            'sport': result.sport,
            'city': result.city,
            'created_at': result.created_at.isoformat() if result.created_at else None
        }
        
        return jsonify(player), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération du joueur {player_id}: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500


@player_interests_bp.route('/player-interests/stats', methods=['GET'])
def get_stats():
    """Récupérer les statistiques des joueurs"""
    try:
        query = text("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN sport = 'padel' THEN 1 END) as padel_count,
                COUNT(CASE WHEN sport = 'tennis' THEN 1 END) as tennis_count,
                COUNT(CASE WHEN sport = 'both' THEN 1 END) as both_count,
                COUNT(DISTINCT city) as cities_count
            FROM player_interests
        """)
        
        result = db.session.execute(query).fetchone()
        
        stats = {
            'total': result.total,
            'padel': result.padel_count,
            'tennis': result.tennis_count,
            'both': result.both_count,
            'cities': result.cities_count
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        print(f"Erreur lors de la récupération des stats: {e}")
        return jsonify({'error': 'Erreur serveur'}), 500
