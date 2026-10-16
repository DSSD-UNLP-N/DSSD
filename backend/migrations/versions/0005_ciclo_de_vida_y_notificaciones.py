"""estados de la evaluación/adjudicación/ejecución, ronda, estado de la oferta y notificaciones

Una sola migración para todo el cierre de la Entrega 3 (ver entrega-3/contratos.md): estados
nuevos de emergencia, `emergencia.ronda`, `oferta.estado` y la tabla `notificacion`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

ESTADOS_VIEJOS = "'REGISTRADA', 'CONVOCATORIA', 'CERRADA'"
ESTADOS_NUEVOS = ESTADOS_VIEJOS + ", 'EN_EVALUACION', 'ADJUDICACION', 'EN_EJECUCION', 'RESUELTA'"
ESTADOS_OFERTA = "'PRESENTADA', 'ADJUDICADA', 'NO_ADJUDICADA', 'FINALIZADA'"


def upgrade() -> None:
    # batch: en SQLite recrea la tabla; en Postgres es un ALTER común.
    with op.batch_alter_table('emergencia') as batch:
        batch.drop_constraint('estadoemergencia', type_='check')
        batch.create_check_constraint('estadoemergencia', f"estado IN ({ESTADOS_NUEVOS})")
        batch.add_column(sa.Column('ronda', sa.Integer(), nullable=False, server_default='1'))
    with op.batch_alter_table('oferta') as batch:
        batch.add_column(sa.Column('estado', sa.String(length=20), nullable=False, server_default='PRESENTADA'))
        batch.create_check_constraint('estadooferta', f"estado IN ({ESTADOS_OFERTA})")
    op.create_table(
        'notificacion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ong_id', sa.Integer(), sa.ForeignKey('ong.id'), nullable=False),
        sa.Column('emergencia_id', sa.Integer(), sa.ForeignKey('emergencia.id'), nullable=False),
        sa.Column('texto', sa.String(length=300), nullable=False),
        sa.Column('creada_en', sa.DateTime(timezone=True), nullable=False),
        sa.Column('leida', sa.Boolean(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_table('notificacion')
    with op.batch_alter_table('oferta') as batch:
        batch.drop_constraint('estadooferta', type_='check')
        batch.drop_column('estado')
    # Los estados nuevos no existen en el esquema viejo: lo que ya pasó la evaluación queda CERRADA.
    op.execute(
        "UPDATE emergencia SET estado = 'CERRADA' "
        "WHERE estado IN ('EN_EVALUACION', 'ADJUDICACION', 'EN_EJECUCION', 'RESUELTA')"
    )
    with op.batch_alter_table('emergencia') as batch:
        batch.drop_column('ronda')
        batch.drop_constraint('estadoemergencia', type_='check')
        batch.create_check_constraint('estadoemergencia', f"estado IN ({ESTADOS_VIEJOS})")
