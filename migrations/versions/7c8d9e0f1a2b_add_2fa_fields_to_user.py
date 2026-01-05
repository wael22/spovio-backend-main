"""add_2fa_fields_to_user

Revision ID: 7c8d9e0f1a2b
Revises: 6a7b8c9d0e1f
Create Date: 2025-12-11 00:08:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c8d9e0f1a2b'
down_revision = '6a7b8c9d0e1f'
branch_labels = None
depends_on = None


def upgrade():
    # Ajouter les colonnes pour l'authentification à deux facteurs
    op.add_column('user', sa.Column('two_factor_secret', sa.String(length=255), nullable=True))
    op.add_column('user', sa.Column('two_factor_enabled', sa.Boolean(), nullable=True, server_default='0'))
    op.add_column('user', sa.Column('two_factor_backup_codes', sa.Text(), nullable=True))


def downgrade():
    # Supprimer les colonnes 2FA
    op.drop_column('user', 'two_factor_backup_codes')
    op.drop_column('user', 'two_factor_enabled')
    op.drop_column('user', 'two_factor_secret')
