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
    Extract JWT token from headers with full debug logging
    
    Returns:
        str: Token string or None
    """
    # Full debug logging
    print(f"\n{'='*60}")
    print(f"[JWT DEBUG] Processing: {request.method} {request.path}")
    print(f"[JWT DEBUG] Origin: {request.headers.get('Origin', 'None')}")
    
    # Print ALL headers received
    all_headers = dict(request.headers)
    print(f"[JWT DEBUG] All headers received ({len(all_headers)}):")
    for key, value in all_headers.items():
        # Truncate long values for readability
        display_value = value[:50] + '...' if len(str(value)) > 50 else value
        print(f"   - {key}: {display_value}")
    
    # Try Authorization header (STANDARD)
    auth_header = request.headers.get('Authorization', '')
    if auth_header:
        print(f"[JWT DEBUG] ✅ Authorization header FOUND: {auth_header[:30]}...")
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            print(f"[JWT DEBUG] ✅ Extracted Bearer token, length: {len(token)}")
            print(f"{'='*60}\n")
            return token
        else:
            print(f"[JWT DEBUG] ⚠️ No 'Bearer ' prefix, using raw value")
            print(f"{'='*60}\n")
            return auth_header
    else:
        print(f"[JWT DEBUG] ❌ Authorization header NOT FOUND")
    
    # Fallback: X-API-Key
    api_key = request.headers.get('X-API-Key', '')
    if api_key:
        print(f"[JWT DEBUG] ✅ X-API-Key FOUND, length: {len(api_key)}")
        print(f"{'='*60}\n")
        return api_key
    
    print(f"[JWT DEBUG] ❌ No valid token found in any header")
    print(f"[JWT DEBUG] Available headers: {list(all_headers.keys())}")
    print(f"{'='*60}\n")
    return None


def get_current_user_from_token():
    """
    Get current user from session or JWT token
    Prioritizes session-based auth (works in CORS) over JWT headers (blocked in CORS)
    
    Returns:
        User: User object or None
    """
    # Try session-based auth FIRST (works in CORS with cookies)
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            print(f"[AUTH] ✅ Session auth: {user.email}")
            return user
    
    # Fallback to JWT token (for non-CORS requests like mobile apps)
    token = get_token_from_header()
    if token:
        payload = verify_jwt_token(token)
        if payload:
            user_id = payload.get('user_id')
            if user_id:
                user = User.query.get(user_id)
                if user:
                    print(f"[AUTH] ✅ JWT auth: {user.email}")
                    return user
    
    print(f"[AUTH] ❌ No valid authentication")
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
