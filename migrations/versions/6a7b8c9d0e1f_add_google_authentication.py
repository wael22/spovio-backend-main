"""add google authentication

Revision ID: 6a7b8c9d0e1f
Revises: 5a6b7c8d9e0f
Create Date: 2023-07-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6a7b8c9d0e1f'
down_revision = '5a6b7c8d9e0f'
branch_labels = None
depends_on = None


def upgrade():
    # Ajout du champ google_id à la table user
    op.add_column('user', sa.Column('google_id', sa.String(100), nullable=True, unique=True))


def downgrade():
    # Suppression du champ google_id de la table user
    op.drop_column('user', 'google_id')
