# padelvar-backend/src/config.py

import os
from urllib.parse import quote_plus

class Config:
    """Configuration de base."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'une-cle-secrete-difficile-a-deviner-CHANGE-IN-PRODUCTION'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # JWT Configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or SECRET_KEY
    JWT_TOKEN_LOCATION = ['headers']
    JWT_ACCESS_TOKEN_EXPIRES = 86400  # 24 heures en secondes
    
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_HTTPONLY = True
    
    # Configuration utilisateurs par défaut
    DEFAULT_ADMIN_EMAIL = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@mysmash.com')
    DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'password123')
    DEFAULT_ADMIN_NAME = 'Super Admin'
    DEFAULT_ADMIN_CREDITS = 10000
    
    # Configuration Celery
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    
    # Configuration Stripe
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
    
    # Configuration Rate Limiting
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/1')
    RATELIMIT_STRATEGY = 'fixed-window'
    RATELIMIT_DEFAULT = '100 per hour, 10 per minute'
    
    # Configuration Bunny CDN
    BUNNY_API_KEY = os.environ.get('BUNNY_API_KEY', '')
    BUNNY_STORAGE_ZONE = os.environ.get('BUNNY_STORAGE_ZONE', 'padelvar-videos')
    BUNNY_HOSTNAME = os.environ.get('BUNNY_HOSTNAME', 'ny.storage.bunnycdn.com')
    BUNNY_REGION = os.environ.get('BUNNY_REGION', 'ny')
    
    @staticmethod
    def get_database_uri():
        """Retourne l'URI de la base de données selon l'environnement."""
        # Priorité 1: DATABASE_URL explicite (Render PostgreSQL)
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            return database_url
        
        env = os.environ.get('FLASK_ENV', 'development')
        
        if env == 'production':
            # PRODUCTION: PostgreSQL si configuré, sinon SQLite
            db_password = os.environ.get('DB_PASSWORD', '')
            
            if db_password:
                # PostgreSQL configuré
                db_user = os.environ.get('DB_USER', 'padelvar')
                db_password_encoded = quote_plus(db_password)
                db_host = os.environ.get('DB_HOST', 'localhost')
                db_port = os.environ.get('DB_PORT', '5432')
                db_name = os.environ.get('DB_NAME', 'padelvar_prod')
                return f'postgresql://{db_user}:{db_password_encoded}@{db_host}:{db_port}/{db_name}'
            else:
                # Fallback sur SQLite en production (données non persistantes sur Render!)
                print("⚠️  WARNING: Using SQLite in production. Data will be ephemeral on Render!")
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                db_path = os.path.join(base_dir, 'padelvar.db')
                return f'sqlite:///{db_path}'
        
        elif env == 'testing':
            # TESTS: SQLite en mémoire (rapide)
            return 'sqlite:///:memory:'
        
        else:
            # DEV: SQLite local avec chemin absolu pour garantir la persistance
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base_dir, 'instance', 'padelvar.db')
            return f'sqlite:///{db_path}'
    
    @staticmethod
    def validate():
        """Valide que les variables critiques sont définies."""
        env = os.environ.get('FLASK_ENV', 'development')
        if env == 'production':
            # Variables optionnelles mais recommandées
            required_vars = ['SECRET_KEY']
            missing_vars = [var for var in required_vars if not os.environ.get(var)]
            if missing_vars:
                raise ValueError(f"Variables d'environnement manquantes pour la production: {', '.join(missing_vars)}")
            
            # Avertissements pour variables optionnelles
            if not os.environ.get('DB_PASSWORD'):
                print("⚠️  WARNING: DB_PASSWORD not set, using SQLite (data will be ephemeral on Render)")
    
    @staticmethod
    def init_app(app):
        pass

class DevelopmentConfig(Config):
    """Configuration de développement."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri()
    SQLALCHEMY_ECHO = False  # Set to True pour voir les requêtes SQL
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://localhost:5173",  # Garder pour compatibilité Vite
        "http://localhost:8080",  # Spovio frontend
        "http://127.0.0.1:8080",  # Spovio frontend
    ]
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = None  # Pour le développement

class ProductionConfig(Config):
    """Configuration de production."""
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'pool_size': 20,
        'max_overflow': 30,
        'connect_args': {
            "options": "-c timezone=UTC"
        }
    }
    
    # Configuration sécurisée pour la production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '').split(',')

class TestingConfig(Config):
    """Configuration de test."""
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri()
    CELERY_TASK_ALWAYS_EAGER = True  # Exécuter les tâches Celery de manière synchrone
    CORS_ORIGINS = "*"

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

def get_config():
    """Retourne la configuration selon l'environnement."""
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, config['default'])