"""
Migration Alembic pour créer la table recordings
"""

# revision identifiers, used by Alembic.
revision = '6c7d8e9f0123'
down_revision = '5a6b7c8d9e0f'  # Remplacer par votre dernière révision
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def upgrade():
    """Crée la table recordings pour le nouveau système d'enregistrement"""
    op.create_table(
        'recordings',
        
        # Identifiants
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column('court_id', sa.Integer, nullable=False),
        sa.Column('match_id', sa.Integer, nullable=True),
        sa.Column('club_id', sa.Integer, nullable=True),
        
        # Métadonnées vidéo
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('file_url', sa.String(500), nullable=False),
        sa.Column('thumbnail_url', sa.String(500), nullable=True),
        
        # Timing
        sa.Column('started_at', sa.DateTime, nullable=False),
        sa.Column('ended_at', sa.DateTime, nullable=True),
        sa.Column('duration', sa.Integer, nullable=True),  # secondes
        
        # Fichier
        sa.Column('file_size', sa.Integer, nullable=True),  # bytes
        sa.Column('resolution_width', sa.Integer, nullable=True),
        sa.Column('resolution_height', sa.Integer, nullable=True),
        sa.Column('fps', sa.Float, nullable=True),
        sa.Column('bitrate', sa.String(20), nullable=True),
        
        # État
        sa.Column('status', sa.String(20), nullable=False, default='created'),
        sa.Column('upload_status', sa.String(20), nullable=False, default='pending'),
        sa.Column('error_message', sa.Text, nullable=True),
        
        # Bunny Stream
        sa.Column('bunny_video_id', sa.String(100), nullable=True),
        sa.Column('bunny_url', sa.String(500), nullable=True),
        
        # Paramètres
        sa.Column('quality_preset', sa.String(20), nullable=True),
        sa.Column('camera_type', sa.String(20), nullable=True),
        sa.Column('max_duration', sa.Integer, nullable=False, default=3600),
        
        # Accès
        sa.Column('is_public', sa.Boolean, nullable=False, default=False),
        sa.Column('credits_cost', sa.Integer, nullable=False, default=10),
        
        # Audit
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
    )
    
    # Index pour les requêtes fréquentes
    op.create_index('idx_recordings_user_id', 'recordings', ['user_id'])
    op.create_index('idx_recordings_court_id', 'recordings', ['court_id'])
    op.create_index('idx_recordings_status', 'recordings', ['status'])
    op.create_index('idx_recordings_created_at', 'recordings', ['created_at'])
    op.create_index('idx_recordings_club_id', 'recordings', ['club_id'])


def downgrade():
    """Supprime la table recordings"""
    op.drop_index('idx_recordings_club_id')
    op.drop_index('idx_recordings_created_at')
    op.drop_index('idx_recordings_status')
    op.drop_index('idx_recordings_court_id')
    op.drop_index('idx_recordings_user_id')
    op.drop_table('recordings')
