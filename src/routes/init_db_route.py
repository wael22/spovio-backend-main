"""
Endpoint temporaire pour initialiser la base de données
Appelez une fois: GET /init-database
Puis supprimez ce fichier
"""
from flask import Blueprint, jsonify
from src.models.database import db
from sqlalchemy import inspect

init_bp = Blueprint('init', __name__)

@init_bp.route('/init-database', methods=['GET'])
def init_database():
    """Initialize all database tables"""
    try:
        # Create all tables
        db.create_all()
        
        # List tables
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        return jsonify({
            'success': True,
            'message': f'Database initialized with {len(tables)} tables',
            'tables': sorted(tables)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
