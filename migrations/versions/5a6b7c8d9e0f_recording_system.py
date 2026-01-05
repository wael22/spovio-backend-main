"""Ajout du système d'enregistrement avancé

Revision ID: 5a6b7c8d9e0f
Revises: 4b4dcdcd2ce8
Create Date: 2025-01-29 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = '5a6b7c8d9e0f'
down_revision = '4b4dcdcd2ce8'
branch_labels = None
depends_on = None


def upgrade():
    # Ajouter les nouvelles colonnes à la table court
    with op.batch_alter_table('court', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_recording', sa.Boolean(), nullable=True, default=False))
        batch_op.add_column(sa.Column('current_recording_id', sa.String(100), nullable=True))

    # Créer la table recording_session
    op.create_table('recording_session',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recording_id', sa.String(100), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('court_id', sa.Integer(), nullable=False),
        sa.Column('club_id', sa.Integer(), nullable=False),
        sa.Column('planned_duration', sa.Integer(), nullable=False),
        sa.Column('max_duration', sa.Integer(), nullable=True, default=200),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(20), nullable=True, default='active'),
        sa.Column('stopped_by', sa.String(20), nullable=True),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['club_id'], ['club.id'], ),
        sa.ForeignKeyConstraint(['court_id'], ['court.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recording_id')
    )

    # Mettre à jour les valeurs par défaut pour les colonnes existantes
    op.execute("UPDATE court SET is_recording = 0 WHERE is_recording IS NULL")
    
    # Rendre les colonnes non-nullables après avoir défini les valeurs par défaut
    with op.batch_alter_table('court', schema=None) as batch_op:
        batch_op.alter_column('is_recording', nullable=False, server_default='0')


def downgrade():
    # Supprimer la table recording_session
    op.drop_table('recording_session')
    
    # Supprimer les colonnes ajoutées à court
    with op.batch_alter_table('court', schema=None) as batch_op:
        batch_op.drop_column('current_recording_id')
        batch_op.drop_column('is_recording')
