"""
Migration pour ajouter la table user_clip
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# Revision identifiers
revision = 'add_user_clip_table'
down_revision = None  # À adapter selon votre dernière migration
branch_labels = None
depends_on = None


def upgrade():
    # Créer la table user_clip
    op.create_table(
        'user_clip',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('start_time', sa.Float(), nullable=False),
        sa.Column('end_time', sa.Float(), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=True),
        sa.Column('file_url', sa.String(length=500), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=500), nullable=True),
        sa.Column('bunny_video_id', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('share_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('download_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['video_id'], ['video.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], )
    )
    
    # Créer des index pour améliorer les performances
    op.create_index('ix_user_clip_video_id', 'user_clip', ['video_id'])
    op.create_index('ix_user_clip_user_id', 'user_clip', ['user_id'])
    op.create_index('ix_user_clip_status', 'user_clip', ['status'])


def downgrade():
    # Supprimer les index
    op.drop_index('ix_user_clip_status', table_name='user_clip')
    op.drop_index('ix_user_clip_user_id', table_name='user_clip')
    op.drop_index('ix_user_clip_video_id', table_name='user_clip')
    
    # Supprimer la table
    op.drop_table('user_clip')
