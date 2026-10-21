"""saca emergencia.plazo_adjudicacion

La consigna no pide un plazo de adjudicación y `plazoAdjudicacionISO` no la lee ningún
nodo del proceso (contrato: CONTRACT_INPUTS en app/integrations/bonita.py), así que la columna quedaba vacía.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('emergencia') as batch:
        batch.drop_column('plazo_adjudicacion')


def downgrade() -> None:
    with op.batch_alter_table('emergencia') as batch:
        batch.add_column(sa.Column('plazo_adjudicacion', sa.DateTime(timezone=True), nullable=True))
