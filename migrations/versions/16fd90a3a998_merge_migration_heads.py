"""merge_migration_heads

Revision ID: 16fd90a3a998
Revises: 7c8d9e0f1a2b, add_cdn_migrated_at, a1b2c3d4e5f6
Create Date: 2025-12-11 00:20:03.653260

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16fd90a3a998'
down_revision = ('7c8d9e0f1a2b', 'add_cdn_migrated_at', 'a1b2c3d4e5f6')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
