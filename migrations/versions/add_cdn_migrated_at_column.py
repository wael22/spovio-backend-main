"""Ajout de la colonne cdn_migrated_at à la table videos

Revision ID: add_cdn_migrated_at
Revises: 5a6b7c8d9e0f
Create Date: 2025-08-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_cdn_migrated_at'
down_revision = '5a6b7c8d9e0f'  # Remplacez par la dernière révision existante
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('videos', sa.Column('cdn_migrated_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('videos', 'cdn_migrated_at')
