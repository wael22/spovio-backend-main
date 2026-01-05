# src/middleware/__init__.py

"""
Middleware pour PadelVar
Gère l'idempotence, le rate limiting, et autres aspects transversaux
"""

from .idempotence import IdempotenceMiddleware, with_idempotence, require_idempotence_key
from .rate_limiting import RateLimitMiddleware, rate_limit

__all__ = [
    'IdempotencyMiddleware',
    'RateLimitMiddleware', 
    'idempotent',
    'rate_limit',
    'get_idempotency_key',
    'mark_response_for_storage'
]