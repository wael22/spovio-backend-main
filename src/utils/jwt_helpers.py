"""
JWT Token Helper Functions
Provides utilities for generating and verifying JWT tokens for authentication
"""
import jwt
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, session
from ..models.user import User

# JWT Configuration
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'your-secret-key-change-in-production-' + os.urandom(24).hex())
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_DAYS = 7


def generate_jwt_token(user_id: int, role: str) -> str:
    """
    Generate a JWT token for a user
    
    Args:
        user_id: User's database ID
        role: User's role (PLAYER, CLUB, ADMIN, SUPER_ADMIN)
    
    Returns:
        str: JWT token
    """
    payload = {
        'user_id': user_id,
        'role': role,
        'exp': datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS),
        'iat': datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def verify_jwt_token(token: str) -> dict:
    """
    Verify and decode a JWT token
    
    Args:
        token: JWT token string
    
    Returns:
        dict: Decoded payload with user_id and role
        None: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_token_from_header() -> str:
    """
    Extract JWT token from X-API-Key header (commonly allowed in CORS)
    Falls back to Authorization header for backward compatibility
    
    Returns:
        str: Token string or None
    """
    # Try X-API-Key first (commonly allowed in CORS)
    token = request.headers.get('X-API-Key', '')
    if token:
        print(f"[JWT DEBUG] ✅ Token from X-API-Key: {token[:20]}...")
        return token
    
    # Fallback to Authorization header
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        print(f"[JWT DEBUG] ✅ Token from Authorization: {token[:20]}...")
        return token
    
    print(f"[JWT DEBUG] ❌ No valid token found")
    return None


def get_current_user_from_token():
    """
    Get current user from JWT token or session (fallback)
    Supports both JWT and session-based authentication
    
    Returns:
        User: User object or None
    """
    # Try JWT token first
    token = get_token_from_header()
    print(f"[JWT DEBUG] Token from header: {token[:20] if token else 'None'}...")
    
    if token:
        payload = verify_jwt_token(token)
        print(f"[JWT DEBUG] Token verification result: {payload}")
        
        if payload:
            user_id = payload.get('user_id')
            print(f"[JWT DEBUG] User ID from payload: {user_id}")
            
            if user_id:
                user = User.query.get(user_id)
                print(f"[JWT DEBUG] User found: {user.email if user else 'None'}")
                return user
        else:
            print(f"[JWT DEBUG] Token verification failed!")
    
    # Fallback to session-based auth (for backward compatibility)
    user_id = session.get('user_id')
    if user_id:
        print(f"[JWT DEBUG] Fallback to session, user_id: {user_id}")
        return User.query.get(user_id)
    
    print(f"[JWT DEBUG] No valid authentication found")
    return None


def require_jwt_auth(f):
    """
    Decorator to protect routes that require JWT authentication
    Supports both JWT tokens and session-based auth
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_current_user_from_token()
        if not current_user:
            return jsonify({'error': 'Authentification requise'}), 401
        return f(*args, **kwargs)
    return decorated_function


def require_jwt_admin(f):
    """
    Decorator to protect routes that require admin privileges
    Supports both JWT tokens and session-based auth
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user = get_current_user_from_token()
        if not current_user:
            return jsonify({'error': 'Authentification requise'}), 401
        
        from ..models.user import UserRole
        if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
            return jsonify({'error': 'Privilèges administrateur requis'}), 403
        
        return f(*args, **kwargs)
    return decorated_function
