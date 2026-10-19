"""agrega lote.tipo_recurso (código del catálogo del Sistema Nacional)

Nullable: los lotes existentes no tienen tipo y no se validan contra el inventario.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('lote') as batch:
        batch.add_column(sa.Column('tipo_recurso', sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('lote') as batch:
        batch.drop_column('tipo_recurso')
