"""
Fichier principal de l'application PadelVar
Factory pattern pour créer l'instance Flask
"""
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import generate_password_hash
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

# Importations relatives corrigées
from .config import DevelopmentConfig, ProductionConfig, Config
from .models.database import db
from .extensions import cache
from .models.user import User, UserRole
from .routes.auth import auth_bp
from .routes.super_admin_auth import super_admin_auth_bp  # 🆕 Authentification super admin avec 2FA
from .routes.admin import admin_bp
from .routes.videos import videos_bp  # Réactivé pour les vidéos
from .routes.clubs import clubs_bp
from .routes.frontend import frontend_bp
from .routes.all_clubs import all_clubs_bp
# from .routes.payment import payment_bp  # Temporarily disabled due to blocking imports
from .routes.system import system_bp

# Configuration des environnements
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
from .routes.players import players_bp
from .routes.recording import recording_bp  # Réactivé pour les terrains
from .routes.video import video_bp  # 🆕 Nouveau système vidéo stable
from .routes.video_preview import preview_bp  # 🆕 Preview vidéo temps réel
from .routes.support import support_bp  # Système de support
from .routes.notifications import notifications_bp  # Système de notifications
# from .routes.recording_v2 import recording_bp as recording_v2_bp  # Temporarily disabled
# from .routes.recording_new import recording_api, init_recording_service  # Temporarily disabled
from .routes.password_reset_routes import password_reset_bp
from .routes.diagnostic import diagnostic_bp
from .routes.highlights import highlights_bp  # 🆕 Highlights generation
from .routes.support import support_bp  # 🆕 Support messages
from .routes.notifications import notifications_bp  # 🆕 Notifications system
from .routes.video_sharing_routes import video_sharing_bp  # 🆕 Video sharing between users
from .routes.analytics_routes import analytics_bp  # 🆕 Analytics dashboard
from .routes.system_settings_routes import system_settings_bp  # 🆕 System settings
from .routes.clip_routes import clip_bp  # 🆕 Manual clip creation and social sharing
from .routes.public_clip_routes import public_clip_bp  # 🆕 Public clip sharing (no auth required)
from .routes.tutorial_routes import tutorial_bp  # 🆕 Tutorial system for new players
from .routes.player_interests import player_interests_bp  # 🆕 Player interests dashboard
from .routes.arbitre_routes import arbitre_bp  # 🆕 Tableau de bord arbitre
from .routes.live_routes import live_bp  # 🆕 Live streaming padel

def create_app(config_name=None):
    """
    Factory pour créer l'application Flask
    
    Args:
        config_name (str): Nom de la configuration à utiliser ('development', 'production', 'testing')
                          Par défaut, utilise la variable d'environnement FLASK_ENV ou 'development'
    
    Returns:
        Flask: Instance de l'application configurée
    """
    
    # Déterminer la configuration à utiliser
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    # Créer l'instance Flask
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), 'static'),
        instance_relative_config=True
    )
    
    # Charger la configuration
    app.config.from_object(config[config_name])
    
    # Configuration UTF-8 pour JSON
    app.config['JSON_AS_ASCII'] = False
    app.config['JSON_SORT_KEYS'] = False
    app.config['JSONIFY_MIMETYPE'] = 'application/json; charset=utf-8'
    
    # S'assurer que le dossier instance existe
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass
    
    # Configuration de la base de données avec le chemin correct
    if config_name != 'testing':
        app.config['SQLALCHEMY_DATABASE_URI'] = config[config_name].get_database_uri()
    
    # Validation de la configuration en production
    if config_name == 'production':
        config[config_name].validate()
    
    # Initialisation des extensions
    db.init_app(app)
    migrate = Migrate(app, db)
    jwt = JWTManager(app)
    
    # Gestion du cache (Fallback vers SimpleCache si Redis est indisponible au démarrage)
    try:
        cache.init_app(app)
        with app.app_context():
            cache.clear()
    except Exception as e:
        print(f"⚠️ Redis indisponible, basculement vers SimpleCache local. Erreur: {e}")
        cache.init_app(app, config={'CACHE_TYPE': 'SimpleCache'})
    
    # 🍪 Configuration des cookies de session pour OVH (HTTP temporaire)
    # Pour HTTP (IPV4 access), il faut SameSite='Lax' et Secure=False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   # Permet le fonctionnement en HTTP
    app.config['SESSION_COOKIE_SECURE'] = False     # Désactivé pour HTTP
    app.config['SESSION_COOKIE_HTTPONLY'] = True    # Sécurité: empêche l'accès JS
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 jours
    
    
    # =============================================================================
    # CORS CONFIGURATION - Manual handling with explicit Authorization support
    # =============================================================================
    
    import re
    
    # Define allowed headers EXPLICITLY
    ALLOWED_HEADERS = "Content-Type, Authorization, X-API-Key, Accept, Origin, X-Requested-With"
    ALLOWED_METHODS = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
    
    def is_origin_allowed(origin):
        """Check if origin is allowed (including Vercel preview URLs)"""
        if not origin:
            return True  # Allow requests without origin
        
        # Allow production Vercel URL and Custom Domains
        if origin in [
            'https://spovio-frontend.vercel.app',
            'https://spovio.net',
            'https://www.spovio.net',
            'http://spovio.net',
            'http://www.spovio.net'
        ]:
            return True
        
        # Allow ALL Vercel preview URLs for spovio-frontend
        vercel_patterns = [
            r'^https://spovio-frontend-[a-z0-9]+-[a-z0-9-]+\.vercel\.app$',
            r'^https://spovio-frontend-.*\.vercel\.app$',
        ]
        
        for pattern in vercel_patterns:
            if re.match(pattern, origin):
                return True
        
        # Allow localhost for development
        if origin.startswith('http://localhost:'):
            return True
            
        # Allow OVH IP
        if origin.startswith('http://213.32.23.209'):
            return True
            
        return False
        
        return False
    
    @app.before_request
    def handle_cors_preflight():
        """Handle CORS preflight OPTIONS requests - MUST include Authorization in Allow-Headers"""
        if request.method == 'OPTIONS':
            origin = request.headers.get('Origin', '*')
            
            # Create empty response with 204 status
            response = app.make_response(('', 204))
            
            # Set CORS headers
            if is_origin_allowed(origin):
                response.headers['Access-Control-Allow-Origin'] = origin
            else:
                response.headers['Access-Control-Allow-Origin'] = '*'
            
            response.headers['Access-Control-Allow-Methods'] = ALLOWED_METHODS
            # CRITICAL: Must explicitly include Authorization!
            response.headers['Access-Control-Allow-Headers'] = ALLOWED_HEADERS
            response.headers['Access-Control-Allow-Credentials'] = 'true'  # Required for session-based auth!
            response.headers['Access-Control-Max-Age'] = '86400'
            
            print(f"✅ CORS Preflight Response for {origin}:")
            print(f"   Allow-Methods: {ALLOWED_METHODS}")
            print(f"   Allow-Headers: {ALLOWED_HEADERS}")
            
            return response
    
    @app.after_request
    def add_cors_headers(response):
        """Add CORS headers to all responses"""
        origin = request.headers.get('Origin')
        
        if origin and is_origin_allowed(origin) and not request.path.startswith('/api/static/'):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        else:
            # Pour les requêtes sans Origin, les images statiques, ou non autorisées
            response.headers['Access-Control-Allow-Origin'] = '*'
            # Pas de credentials avec '*'
            if 'Access-Control-Allow-Credentials' in response.headers:
                del response.headers['Access-Control-Allow-Credentials']
        
        response.headers['Access-Control-Allow-Methods'] = ALLOWED_METHODS
        response.headers['Access-Control-Allow-Headers'] = ALLOWED_HEADERS
        
        return response
    
    print(f"🌐 CORS: Manual handling configured with explicit Authorization support")
    
    # Enregistrement des blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(super_admin_auth_bp, url_prefix='/api/auth/super-admin')  # 🆕 Auth super admin
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(system_settings_bp)  # Settings admin (prefix in blueprint)
    app.register_blueprint(videos_bp, url_prefix='/api/videos')  # Réactivé pour les vidéos
    app.register_blueprint(clubs_bp, url_prefix='/api/clubs')
    app.register_blueprint(all_clubs_bp, url_prefix='/api/all-clubs')
    app.register_blueprint(players_bp, url_prefix='/api/players')
    app.register_blueprint(recording_bp, url_prefix='/api/recording')
    app.register_blueprint(video_bp)  # 🆕 Système vidéo stable (prefix inclus dans blueprint)
    app.register_blueprint(preview_bp)  # 🆕 Preview vidéo temps réel (prefix inclus dans blueprint)
    app.register_blueprint(support_bp, url_prefix='/api/support')  # Système de support
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')  # Notifications
    # app.register_blueprint(recording_v2_bp, url_prefix='/api/recording/v2')  # Temporarily disabled
    # app.register_blueprint(recording_api, url_prefix='/api/recording/v3')  # Temporarily disabled
    app.register_blueprint(diagnostic_bp, url_prefix='/api/diagnostic')
    
    # ⚠️ TEMPORAIRE - Endpoint init DB (appeler une fois puis supprimer)
    from src.routes.init_db_route import init_bp
    app.register_blueprint(init_bp, url_prefix='/api')
    
    # ⚠️ TEMPORAIRE - Endpoint pour cr\u00e9er compte de test en production
    from src.routes.test_admin import test_bp
    app.register_blueprint(test_bp, url_prefix='/api/test-admin')
    # app.register_blueprint(payment_bp, url_prefix='/api/payment')  # Temporarily disabled
    app.register_blueprint(system_bp, url_prefix='/api/system')
    app.register_blueprint(highlights_bp)  # 🆕 Highlights (prefix in blueprint)
    app.register_blueprint(video_sharing_bp, url_prefix='/api/videos')  # 🆕 Video sharing
    app.register_blueprint(analytics_bp, url_prefix='/api/analytics')  # 🆕 Analytics dashboard
    app.register_blueprint(clip_bp)  # 🆕 Manual clips (prefix in blueprint)
    app.register_blueprint(public_clip_bp)  # 🆕 Public clip sharing (no auth, root level)
    app.register_blueprint(tutorial_bp, url_prefix='/api/tutorial')  # 🆕 Tutorial system
    app.register_blueprint(player_interests_bp, url_prefix='/api')  # 🆕 Player interests
    app.register_blueprint(arbitre_bp)  # 🆕 Tableau de bord arbitre (/arbitre + /api/arbitre/*)
    app.register_blueprint(live_bp)     # 🆕 Live streaming (/live + /watch/<code> + /api/live/*)
    app.register_blueprint(password_reset_bp)
    
    # 🆕 Video Recovery System
    from .routes.recovery import recovery_bp
    app.register_blueprint(recovery_bp)

    # Frontend blueprint en dernier pour éviter d'intercepter les routes API
    app.register_blueprint(frontend_bp)
    
    # Initialiser le nouveau service d'enregistrement
    # init_recording_service(app)  # Temporarily disabled
    
    # Route de test pour le développement
    if config_name == 'development':
        @app.route('/test')
        def test_page():
            """Page de test d'authentification"""
            from flask import send_from_directory
            import os
            test_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_auth.html')
            if os.path.exists(test_file_path):
                return send_from_directory(os.path.dirname(test_file_path), 'test_auth.html')
            else:
                return """
                <html><body>
                <h1>Page de test PadelVar</h1>
                <p>Fichier test_auth.html non trouvé.</p>
                <p>Essayez d'accéder directement au fichier test_auth.html dans le répertoire backend.</p>
                </body></html>
                """
    
    # Routes de base
    @app.route('/api/health')
    def health_check():
        """Point de contrôle de santé de l'API"""
        return {
            'status': 'OK', 
            'message': 'PadelVar API is running',
            'environment': config_name
        }
    

    

    def get_avatar_dir():
        """Retourne le dossier d'avatars en utilisant un chemin absolu robuste."""
        # En Docker: workdir est /app, src est dans /app/src
        docker_path = '/app/src/static/uploads/avatars'
        if os.path.isdir('/app/src'):
            return docker_path
        # En local: app.root_path pointe vers le dossier 'src'
        return os.path.join(app.root_path, 'static', 'uploads', 'avatars')

    @app.route('/api/static/avatars/<path:filename>')
    def serve_avatar(filename):
        """Sert un avatar ou logo — route utilisée par getAssetUrl() du frontend."""
        from flask import send_from_directory, make_response
        avatar_dir = get_avatar_dir()
        os.makedirs(avatar_dir, exist_ok=True)
        try:
            response = make_response(send_from_directory(avatar_dir, filename))
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
            response.headers['Cache-Control'] = 'public, max-age=86400'
            return response
        except Exception as e:
            print(f"❌ Avatar non trouvé: {filename} — {e}")
            return jsonify({'error': 'Fichier non trouvé'}), 404

    @app.route('/api/static/uploads/avatars/<path:filename>')
    def serve_avatar_full_path(filename):
        """Sert les logos club via le chemin complet /static/uploads/avatars/ (non transformé par getAssetUrl)."""
        from flask import send_from_directory, make_response
        avatar_dir = get_avatar_dir()
        os.makedirs(avatar_dir, exist_ok=True)
        try:
            response = make_response(send_from_directory(avatar_dir, filename))
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Cross-Origin-Resource-Policy'] = 'cross-origin'
            response.headers['Cache-Control'] = 'public, max-age=86400'
            return response
        except Exception as e:
            print(f"❌ Logo non trouvé: {filename} — {e}")
            return jsonify({'error': 'Fichier non trouvé'}), 404

    @app.route('/')
    def index():
        """Page d'accueil de l'API"""
        return {
            'message': 'Bienvenue sur l\'API PadelVar',
            'version': '1.0.0',
            'endpoints': {
                'health': '/api/health',
                'auth': '/api/auth',
                'admin': '/api/admin',
                'videos': '/api/videos',
                'clubs': '/api/clubs',
                'players': '/api/players'
            }
        }
    
    # Initialisation de la base de données et création de l'admin
    # Uniquement en mode développement et si la base n'existe pas
    if config_name == 'development':
        with app.app_context():
            # Créer toutes les tables
            db.create_all()
            
            # Créer l'admin par défaut s'il n'existe pas
            _create_default_admin(app)
            
            # Démarrer le monitoring périodique en développement
            _init_periodic_monitoring(app)
    elif config_name == 'production':
        # En production, s'assurer que le monitoring est actif
        with app.app_context():
            # Temporarily disabled to isolate startup issues
            # _init_periodic_monitoring(app)
            pass
    
    
    # Démarrer le scheduler de nettoyage et le service Bunny
    _init_recording_scheduler(app)
    
    return app

def _create_default_admin(app):
    """
    Crée l'administrateur par défaut s'il n'existe pas
    
    Args:
        app: Instance Flask avec contexte d'application actif
    """
    try:
        admin_email = app.config['DEFAULT_ADMIN_EMAIL']
        super_admin = User.query.filter_by(email=admin_email).first()
        
        if not super_admin:
            super_admin = User(
                email=admin_email,
                password_hash=generate_password_hash(app.config['DEFAULT_ADMIN_PASSWORD']),
                name=app.config['DEFAULT_ADMIN_NAME'],
                role=UserRole.SUPER_ADMIN,
                credits_balance=app.config['DEFAULT_ADMIN_CREDITS']
            )
            db.session.add(super_admin)
            db.session.commit()
            
            print(f"✅ Super admin créé: {admin_email} / {app.config['DEFAULT_ADMIN_PASSWORD']}")
        else:
            print(f"ℹ️  Super admin existe déjà: {admin_email}")
            
    except Exception as e:
        print(f"❌ Erreur lors de la création de l'admin: {e}")
        db.session.rollback()

def init_db(app):
    """
    Initialise la base de données avec les tables
    Fonction utilitaire pour les scripts d'initialisation
    
    Args:
        app: Instance Flask
    """
    with app.app_context():
        db.create_all()
        print("✅ Base de données initialisée")

def create_admin(app, email, password, name="Admin"):
    """
    Crée un administrateur
    Fonction utilitaire pour les scripts d'administration
    
    Args:
        app: Instance Flask
        email (str): Email de l'administrateur
        password (str): Mot de passe
        name (str): Nom de l'administrateur
    """
    with app.app_context():
        existing_admin = User.query.filter_by(email=email).first()
        if existing_admin:
            print(f"❌ Un utilisateur avec l'email {email} existe déjà")
            return False
        
        admin = User(
            email=email,
            password_hash=generate_password_hash(password),
            name=name,
            role=UserRole.SUPER_ADMIN,
            credits_balance=1000
        )
        
        db.session.add(admin)
        db.session.commit()
        print(f"✅ Administrateur créé: {email}")
        return True


def _init_periodic_monitoring(app):
    """
    Initialise le monitoring périodique du système
    
    Args:
        app: Instance Flask
    """
    try:
        # Importer et démarrer le monitoring seulement si Celery est disponible
        from .tasks.maintenance_tasks import system_monitoring_check
        
        # Exécuter une vérification immédiate au démarrage
        with app.app_context():
            result = system_monitoring_check.delay()
            print(f"✅ Monitoring système initialisé")
            
    except ImportError:
        print(f"⚠️  Celery non disponible, monitoring périodique désactivé")
    except Exception as e:
        print(f"⚠️  Erreur lors de l'initialisation du monitoring: {e}")


def _init_recording_scheduler(app):
    """
    Initialise un scheduler en arrière-plan pour nettoyer les enregistrements expirés
    """
    import threading
    import time
    
    def run_scheduler():
        print("⏰ Scheduler de nettoyage des enregistrements démarré")
        while True:
            try:
                # Attendre 60 secondes
                time.sleep(60)
                
                with app.app_context():
                    # Import local pour éviter les cycles
                    from src.routes.recording import cleanup_expired_sessions
                    
                    # Exécuter le nettoyage
                    count = cleanup_expired_sessions()
                    if count > 0:
                        print(f"🧹 Scheduler: {count} enregistrements expirés nettoyés")
                        
            except Exception as e:
                print(f"❌ Erreur dans le scheduler de nettoyage: {e}")
                # Attendre un peu avant de retenter en cas d'erreur
                time.sleep(10)

    # Démarrer le thread en mode daemon
    thread = threading.Thread(target=run_scheduler, daemon=True, name="RecordingCleanupScheduler")
    thread.start()
    
    # 🆕 Démarrer le service de mise à jour du statut Bunny CDN
    try:
        from src.services.bunny_status_updater import BunnyStatusUpdater
        import os
        
        # Charger depuis variables d'environnement uniquement
        api_key = os.environ.get('BUNNY_API_KEY')
        library_id = os.environ.get('BUNNY_LIBRARY_ID')
        
        if api_key and library_id:
            bunny_updater = BunnyStatusUpdater(api_key, library_id, app)
            bunny_updater.start()
            print("✅ Service de mise à jour Bunny CDN démarré")
        else:
            print("⚠️ BUNNY_API_KEY ou BUNNY_LIBRARY_ID manquant - service Bunny non démarré")
    except Exception as e:
        print(f"⚠️  Erreur démarrage service Bunny: {e}")

