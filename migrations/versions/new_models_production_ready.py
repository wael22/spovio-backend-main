"""
Migration pour les nouveaux modèles production-ready
Ajoute: UserStatus, Transaction, Notification, et améliorations sécurité

Revision ID: a1b2c3d4e5f6
Revises: 6c7d8e9f0123
Create Date: 2025-01-17 15:30:00.000000
"""

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '6c7d8e9f0123'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    """Crée les nouveaux modèles pour la version production"""
    
    # 1. Ajouter la colonne status à la table users
    try:
        # Créer le type enum pour UserStatus (PostgreSQL)
        user_status_enum = postgresql.ENUM(
            'ACTIVE', 'PENDING_VERIFICATION', 'SUSPENDED', 'INACTIVE',
            name='userstatus',
            create_type=False
        )
        user_status_enum.create(op.get_bind())
    except Exception:
        # L'enum existe déjà ou on est sur SQLite
        pass
    
    # Ajouter la colonne status avec une valeur par défaut
    op.add_column('users', sa.Column('status', sa.String(20), nullable=False, default='ACTIVE'))
    
    # Ajouter d'autres colonnes utiles à users si elles n'existent pas
    try:
        op.add_column('users', sa.Column('email_verified', sa.Boolean, default=False))
        op.add_column('users', sa.Column('email_verification_token', sa.String(100), nullable=True))
        op.add_column('users', sa.Column('password_reset_token', sa.String(100), nullable=True))
        op.add_column('users', sa.Column('password_reset_expires', sa.DateTime, nullable=True))
        op.add_column('users', sa.Column('last_login', sa.DateTime, nullable=True))
        op.add_column('users', sa.Column('failed_login_attempts', sa.Integer, default=0))
        op.add_column('users', sa.Column('locked_until', sa.DateTime, nullable=True))
    except Exception as e:
        # Les colonnes existent peut-être déjà
        print(f"Certaines colonnes users existent déjà: {e}")
    
    # 2. Créer la table des transactions
    try:
        transaction_status_enum = postgresql.ENUM(
            'PENDING', 'COMPLETED', 'FAILED', 'CANCELLED', 'REFUNDED',
            name='transactionstatus',
            create_type=False
        )
        transaction_status_enum.create(op.get_bind())
    except Exception:
        pass
    
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        
        # Informations de transaction
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, default='EUR'),
        sa.Column('package_name', sa.String(100), nullable=False),
        sa.Column('credits_amount', sa.Integer, nullable=False),
        
        # Statut et idempotence
        sa.Column('status', sa.String(20), nullable=False, default='PENDING'),
        sa.Column('idempotency_key', sa.String(100), nullable=True, unique=True),
        
        # Intégration Stripe
        sa.Column('stripe_payment_intent_id', sa.String(100), nullable=True),
        sa.Column('stripe_checkout_session_id', sa.String(100), nullable=True),
        sa.Column('payment_method', sa.String(50), nullable=False, default='stripe'),
        
        # Métadonnées
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('metadata', sa.JSON, nullable=True),
        
        # Horodatage
        sa.Column('created_at', sa.DateTime, nullable=False, default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        
        # Index pour performance
        sa.Index('idx_transactions_user_id', 'user_id'),
        sa.Index('idx_transactions_status', 'status'),
        sa.Index('idx_transactions_created_at', 'created_at'),
    )
    
    # 3. Créer la table des notifications
    try:
        notification_type_enum = postgresql.ENUM(
            'VIDEO_READY', 'VIDEO_FAILED', 'CREDITS_ADDED', 'CREDITS_LOW', 
            'RECORDING_STARTED', 'RECORDING_STOPPED', 'PAYMENT_SUCCESS', 
            'PAYMENT_FAILED', 'SYSTEM_MAINTENANCE', 'ACCOUNT_SUSPENDED', 
            'PASSWORD_RESET', 'EMAIL_VERIFICATION',
            name='notificationtype',
            create_type=False
        )
        notification_type_enum.create(op.get_bind())
    except Exception:
        pass
    
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        
        # Contenu de la notification
        sa.Column('notification_type', sa.String(30), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('priority', sa.String(10), nullable=False, default='normal'),
        
        # État de la notification
        sa.Column('is_read', sa.Boolean, nullable=False, default=False),
        sa.Column('is_deleted', sa.Boolean, nullable=False, default=False),
        
        # Métadonnées
        sa.Column('action_url', sa.String(500), nullable=True),
        sa.Column('metadata', sa.JSON, nullable=True),
        
        # Expiration automatique
        sa.Column('expires_at', sa.DateTime, nullable=True),
        
        # Horodatage
        sa.Column('created_at', sa.DateTime, nullable=False, default=sa.func.now()),
        sa.Column('read_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=False, default=sa.func.now(), onupdate=sa.func.now()),
        
        # Index pour performance
        sa.Index('idx_notifications_user_id', 'user_id'),
        sa.Index('idx_notifications_is_read', 'is_read'),
        sa.Index('idx_notifications_type', 'notification_type'),
        sa.Index('idx_notifications_created_at', 'created_at'),
        sa.Index('idx_notifications_expires_at', 'expires_at'),
    )
    
    # 4. Améliorer la table recording_sessions si nécessaire
    try:
        # Ajouter des colonnes de monitoring pour les sessions zombies
        op.add_column('recording_sessions', sa.Column('process_id', sa.String(50), nullable=True))
        op.add_column('recording_sessions', sa.Column('health_check_at', sa.DateTime, nullable=True))
        op.add_column('recording_sessions', sa.Column('failure_reason', sa.String(500), nullable=True))
        op.add_column('recording_sessions', sa.Column('auto_stopped', sa.Boolean, default=False))
        
        # Index pour les sessions zombies
        op.create_index('idx_recording_sessions_process_id', 'recording_sessions', ['process_id'])
        op.create_index('idx_recording_sessions_health_check', 'recording_sessions', ['health_check_at'])
    except Exception as e:
        print(f"Les colonnes recording_sessions existent peut-être déjà: {e}")
    
    # 5. Créer une table pour l'idempotence si nécessaire
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('key', sa.String(100), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('endpoint', sa.String(200), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('response_data', sa.JSON, nullable=True),
        sa.Column('status_code', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        
        # Index pour performance et nettoyage
        sa.Index('idx_idempotency_keys_expires_at', 'expires_at'),
        sa.Index('idx_idempotency_keys_endpoint', 'endpoint'),
    )
    
    print("✅ Migration des nouveaux modèles appliquée avec succès")


def downgrade():
    """Supprime les nouveaux modèles"""
    
    # Supprimer les tables dans l'ordre inverse
    op.drop_table('idempotency_keys')
    op.drop_table('notifications')
    op.drop_table('transactions')
    
    # Supprimer les colonnes ajoutées à users
    try:
        op.drop_column('users', 'status')
        op.drop_column('users', 'email_verified')
        op.drop_column('users', 'email_verification_token')
        op.drop_column('users', 'password_reset_token')
        op.drop_column('users', 'password_reset_expires')
        op.drop_column('users', 'last_login')
        op.drop_column('users', 'failed_login_attempts')
        op.drop_column('users', 'locked_until')
    except Exception as e:
        print(f"Erreur lors de la suppression des colonnes users: {e}")
    
    # Supprimer les colonnes ajoutées à recording_sessions
    try:
        op.drop_column('recording_sessions', 'process_id')
        op.drop_column('recording_sessions', 'health_check_at')
        op.drop_column('recording_sessions', 'failure_reason')
        op.drop_column('recording_sessions', 'auto_stopped')
    except Exception as e:
        print(f"Erreur lors de la suppression des colonnes recording_sessions: {e}")
    
    # Supprimer les enums (PostgreSQL)
    try:
        op.execute('DROP TYPE IF EXISTS userstatus CASCADE')
        op.execute('DROP TYPE IF EXISTS transactionstatus CASCADE')
        op.execute('DROP TYPE IF EXISTS notificationtype CASCADE')
    except Exception:
        pass
    
    print("✅ Migration des nouveaux modèles annulée avec succès")