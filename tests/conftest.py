"""
Configuration pytest pour PadelVar
Fixtures partagées et configuration des tests
"""
import os
import sys
import pytest
import tempfile
from unittest.mock import Mock, patch

# Ajouter le chemin du projet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask
from src.config import Config
from src.models.database import db
from src.models.user import User, UserStatus
from src.models.recording import RecordingSession


class TestConfig(Config):
    """Configuration spécifique pour les tests"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key'
    
    # Désactiver les services externes pour les tests
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    
    # Configuration Stripe de test
    STRIPE_PUBLISHABLE_KEY = 'pk_test_123'
    STRIPE_SECRET_KEY = 'sk_test_123'
    STRIPE_WEBHOOK_SECRET = 'whsec_test_123'
    
    # Configuration Redis de test
    REDIS_URL = 'redis://localhost:6379/15'  # DB 15 pour tests
    
    # Configuration FFmpeg mock
    FFMPEG_PATH = '/usr/bin/ffmpeg'  # Mock dans les tests
    
    # Désactiver le rate limiting
    RATELIMIT_ENABLED = False


@pytest.fixture(scope='session')
def app():
    """Fixture de l'application Flask pour les tests"""
    app = Flask(__name__)
    app.config.from_object(TestConfig)
    
    # Importer et enregistrer les blueprints
    from src.routes.auth import auth_bp
    from src.routes.payment import payment_bp
    from src.routes.notifications import notifications_bp
    from src.routes.health import health_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(payment_bp, url_prefix='/api/payments')
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')
    app.register_blueprint(health_bp)
    
    # Initialiser la base de données
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Client de test Flask"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Runner CLI Flask"""
    return app.test_cli_runner()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Nettoie la base de données avant chaque test"""
    with app.app_context():
        # Supprimer toutes les données
        db.session.remove()
        db.drop_all()
        db.create_all()


@pytest.fixture
def admin_user(app):
    """Fixture utilisateur administrateur"""
    with app.app_context():
        admin = User(
            email='admin@test.com',
            name='Test Admin',
            role='admin',
            status=UserStatus.ACTIVE.value,
            credits=1000
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        return admin


@pytest.fixture
def club_user(app):
    """Fixture utilisateur club"""
    with app.app_context():
        club = User(
            email='club@test.com',
            name='Test Club',
            role='club',
            status=UserStatus.ACTIVE.value,
            credits=500
        )
        club.set_password('club123')
        db.session.add(club)
        db.session.commit()
        return club


@pytest.fixture
def player_user(app):
    """Fixture utilisateur joueur"""
    with app.app_context():
        player = User(
            email='player@test.com',
            name='Test Player',
            role='player',
            status=UserStatus.ACTIVE.value,
            credits=100
        )
        player.set_password('player123')
        db.session.add(player)
        db.session.commit()
        return player


@pytest.fixture
def auth_headers_admin(client, admin_user):
    """Headers d'authentification pour admin"""
    response = client.post('/api/auth/login', json={
        'email': 'admin@test.com',
        'password': 'admin123'
    })
    
    if response.status_code == 200:
        token = response.json['access_token']
        return {'Authorization': f'Bearer {token}'}
    else:
        pytest.fail(f"Failed to authenticate admin: {response.data}")


@pytest.fixture
def auth_headers_club(client, club_user):
    """Headers d'authentification pour club"""
    response = client.post('/api/auth/login', json={
        'email': 'club@test.com',
        'password': 'club123'
    })
    
    if response.status_code == 200:
        token = response.json['access_token']
        return {'Authorization': f'Bearer {token}'}
    else:
        pytest.fail(f"Failed to authenticate club: {response.data}")


@pytest.fixture
def auth_headers_player(client, player_user):
    """Headers d'authentification pour player"""
    response = client.post('/api/auth/login', json={
        'email': 'player@test.com',
        'password': 'player123'
    })
    
    if response.status_code == 200:
        token = response.json['access_token']
        return {'Authorization': f'Bearer {token}'}
    else:
        pytest.fail(f"Failed to authenticate player: {response.data}")


@pytest.fixture
def recording_session(app, player_user):
    """Fixture session d'enregistrement"""
    with app.app_context():
        session = RecordingSession(
            id='test-session-123',
            user_id=player_user.id,
            court_id=1,
            title='Test Recording',
            status='pending',
            file_url='',
            created_at=db.func.now()
        )
        db.session.add(session)
        db.session.commit()
        return session


@pytest.fixture
def mock_celery():
    """Mock Celery pour les tests"""
    with patch('src.tasks.video_processing.process_recording.delay') as mock_task:
        mock_task.return_value = Mock(id='test-task-123')
        yield mock_task


@pytest.fixture
def mock_stripe():
    """Mock Stripe pour les tests"""
    with patch('stripe.checkout.Session.create') as mock_create:
        mock_create.return_value = Mock(
            id='cs_test_123',
            url='https://checkout.stripe.com/test'
        )
        yield mock_create


@pytest.fixture
def mock_ffmpeg():
    """Mock FFmpeg pour les tests"""
    with patch('subprocess.Popen') as mock_popen:
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.poll.return_value = None  # Processus en cours
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        yield mock_process


@pytest.fixture
def temp_video_file():
    """Fichier vidéo temporaire pour les tests"""
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        # Créer un fichier vidéo minimal (header MP4)
        f.write(b'\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00')
        f.flush()
        yield f.name
    
    # Nettoyer le fichier après le test
    try:
        os.unlink(f.name)
    except OSError:
        pass


@pytest.fixture
def sample_notification_data():
    """Données de notification pour les tests"""
    return {
        'notification_type': 'VIDEO_READY',
        'title': 'Video Ready',
        'message': 'Your video is ready for download',
        'priority': 'normal'
    }


# Markers personnalisés pour organiser les tests
pytest.mark.integration = pytest.mark.integration
pytest.mark.unit = pytest.mark.unit
pytest.mark.slow = pytest.mark.slow
pytest.mark.celery = pytest.mark.celery
pytest.mark.database = pytest.mark.database