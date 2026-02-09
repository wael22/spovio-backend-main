"""
Version minimale de main.py pour diagnostiquer les problèmes de démarrage
Cette version désactive toutes les fonctionnalités non essentielles
"""
import os
from flask import Flask, jsonify
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

# Importations de base uniquement
from .config import DevelopmentConfig, ProductionConfig
from .models.database import db
from .models.user import User, UserRole
from werkzeug.security import generate_password_hash

# Configuration des environnements
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

def create_app(config_name=None):
    """
    Factory minimaliste pour créer l'application Flask
    Version de diagnostic - fonctionnalités limitées
    """
    
    # Déterminer la configuration
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    print(f"🚀 Démarrage en mode MINIMAL - Config: {config_name}")
    
    # Créer l'instance Flask
    app = Flask(__name__)
    
    # Charger la configuration
    app.config.from_object(config[config_name])
    
    # Configuration UTF-8
    app.config['JSON_AS_ASCII'] = False
    app.config['JSON_SORT_KEYS'] = False
    
    # Configuration de la base de données
    if config_name != 'testing':
        app.config['SQLALCHEMY_DATABASE_URI'] = config[config_name].get_database_uri()
    
    # Initialisation des extensions de base
    db.init_app(app)
    migrate = Migrate(app, db)
    jwt = JWTManager(app)
    
    print("✅ Extensions de base initialisées")
    
    # CORS simplifié
    @app.after_request
    def add_cors_headers(response):
        """Headers CORS simples"""
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response
    
    @app.before_request
    def handle_preflight():
        """Handle OPTIONS requests"""
        from flask import request
        if request.method == 'OPTIONS':
            response = app.make_response(('', 204))
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            return response
    
    print("✅ CORS configuré")
    
    # AUCUN Blueprint pour l'instant - version ultra-minimale
    print("⚠️  Aucun blueprint chargé (mode ultra-minimal)")
    
    # Routes de base
    @app.route('/api/health')
    def health_check():
        """Point de contrôle de santé"""
        return {
            'status': 'OK',
            'message': 'Spovio API is running (MINIMAL MODE)',
            'environment': config_name,
            'mode': 'minimal'
        }
    
    @app.route('/')
    def index():
        """Page d'accueil"""
        return {
            'message': 'Bienvenue sur l\'API Spovio (Mode Minimal)',
            'version': '1.0.0-minimal',
            'mode': 'diagnostic',
            'endpoints': {
                'health': '/api/health',
                'auth': '/api/auth',
                'admin': '/api/admin'
            }
        }
    
    # Initialisation de la base de données en développement
    if config_name == 'development':
        with app.app_context():
            try:
                db.create_all()
                _create_default_admin(app)
                print("✅ Base de données initialisée")
            except Exception as e:
                print(f"⚠️ Erreur init DB: {e}")
    
    print("🎉 Application créée avec succès (MODE MINIMAL)")
    return app

def _create_default_admin(app):
    """Crée l'admin par défaut si nécessaire"""
    try:
        admin_email = app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@spovio.net')
        super_admin = User.query.filter_by(email=admin_email).first()
        
        if not super_admin:
            super_admin = User(
                email=admin_email,
                password_hash=generate_password_hash(app.config.get('DEFAULT_ADMIN_PASSWORD', 'admin123')),
                name=app.config.get('DEFAULT_ADMIN_NAME', 'Super Admin'),
                role=UserRole.SUPER_ADMIN,
                credits_balance=10000
            )
            db.session.add(super_admin)
            db.session.commit()
            print(f"✅ Super admin créé: {admin_email}")
        else:
            print(f"ℹ️  Super admin existe: {admin_email}")
    except Exception as e:
        print(f"⚠️ Erreur création admin: {e}")
        db.session.rollback()
