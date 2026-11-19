"""cuándo se adjudicó cada oferta, con backfill desde el aviso a la ONG

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('oferta') as batch:
        batch.add_column(sa.Column('adjudicada_en', sa.DateTime(timezone=True), nullable=True))

    # Las ofertas ya adjudicadas toman la fecha del aviso más viejo que recibió esa ONG para esa emergencia
    # (texto de registrar_adjudicacion). "no fue seleccionada" no coincide porque se compara el texto entero.
    op.execute(sa.text(
        "UPDATE oferta SET adjudicada_en = ("
        " SELECT MIN(n.creada_en) FROM notificacion n"
        " WHERE n.ong_id = oferta.ong_id AND n.emergencia_id = oferta.emergencia_id"
        " AND n.texto = 'Tu oferta para la emergencia #' || CAST(oferta.emergencia_id AS VARCHAR)"
        " || ' fue seleccionada.')"
        " WHERE estado = 'ADJUDICADA'"
    ))


def downgrade() -> None:
    with op.batch_alter_table('oferta') as batch:
        batch.drop_column('adjudicada_en')
