"""cuándo empezó el monitoreo de la ejecución y cuándo se validó el cierre bilateral

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
        batch.add_column(sa.Column('monitoreo_iniciado_en', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('cierre_validado_en', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('emergencia') as batch:
        batch.drop_column('cierre_validado_en')
        batch.drop_column('monitoreo_iniciado_en')
