from flask_caching import Cache

# Cache global utilisé par l'application
# En développement/local on peut temporairement utiliser SimpleCache si Redis n'est pas installé,
# mais pour le VPS on utilisera RedisCache.
cache = Cache(config={
    'CACHE_TYPE': 'RedisCache',
    'CACHE_REDIS_URL': 'redis://localhost:6379/0',
    'CACHE_DEFAULT_TIMEOUT': 60
})
