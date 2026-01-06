"""
Endpoint temporaire pour supprimer un utilisateur de test
GET /api/test-admin/delete-user?email=xxx
"""
from flask import Blueprint, jsonify, request
from src.models.database import db
from src.models.user import User

delete_user_bp = Blueprint('delete_user', __name__)

@delete_user_bp.route('/delete-user', methods=['GET', 'DELETE'])
def delete_user():
    """Delete a test user by email"""
    email = request.args.get('email')
    
    if not email:
        return jsonify({'error': 'Email parameter required'}), 400
    
    try:
        user = User.query.filter_by(email=email.lower().strip()).first()
        
        if not user:
            return jsonify({'error': f'User {email} not found'}), 404
        
        db.session.delete(user)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'User {email} deleted successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
