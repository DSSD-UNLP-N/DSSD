"""consorcios entre ONGs: tablas consorcio y consorcio_miembro

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('consorcio',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('emergencia_id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=80), nullable=False),
    sa.Column('ong_lider_id', sa.Integer(), nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('disuelto_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['emergencia_id'], ['emergencia.id'], ),
    sa.ForeignKeyConstraint(['ong_lider_id'], ['ong.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('emergencia_id', 'nombre')
    )
    op.create_table('consorcio_miembro',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('consorcio_id', sa.Integer(), nullable=False),
    sa.Column('ong_id', sa.Integer(), nullable=False),
    sa.Column('estado', sa.Enum('INVITADA', 'ACEPTADA', 'RECHAZADA', 'SALIO', name='estadomiembro', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('invitado_por_ong_id', sa.Integer(), nullable=False),
    sa.Column('invitado_en', sa.DateTime(timezone=True), nullable=False),
    sa.Column('respondido_en', sa.DateTime(timezone=True), nullable=True),
    sa.Column('salio_en', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['consorcio_id'], ['consorcio.id'], ),
    sa.ForeignKeyConstraint(['invitado_por_ong_id'], ['ong.id'], ),
    sa.ForeignKeyConstraint(['ong_id'], ['ong.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # El enum es VARCHAR + CHECK (no nativo): se va con la tabla, no hay tipo de Postgres que borrar.
    op.drop_table('consorcio_miembro')
    op.drop_table('consorcio')
