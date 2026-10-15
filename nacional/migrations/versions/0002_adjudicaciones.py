"""adjudicaciones y compromisos de inventario

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "b99371d39182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adjudicacion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referencia_id", sa.String(length=80), nullable=False),
        sa.Column("ong_id", sa.Integer(), nullable=False),
        sa.Column("emergencia_id", sa.Integer(), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ong_id"], ["ong.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("referencia_id", name="uq_adjudicacion_referencia"),
    )
    op.create_table(
        "adjudicacion_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("adjudicacion_id", sa.Integer(), nullable=False),
        sa.Column("inventario_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.CheckConstraint("cantidad > 0", name="ck_adjudicacion_item_cantidad"),
        sa.ForeignKeyConstraint(["adjudicacion_id"], ["adjudicacion.id"]),
        sa.ForeignKeyConstraint(["inventario_id"], ["inventario.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "adjudicacion_id", "inventario_id", name="uq_adjudicacion_inventario"
        ),
    )


def downgrade() -> None:
    op.drop_table("adjudicacion_item")
    op.drop_table("adjudicacion")
