"""agrega emergencia.monitoreo_completado para el flujo de cierre bilateral (WP6)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('emergencia') as batch:
        batch.add_column(sa.Column('monitoreo_completado', sa.Boolean(), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('emergencia') as batch:
        batch.drop_column('monitoreo_completado')
