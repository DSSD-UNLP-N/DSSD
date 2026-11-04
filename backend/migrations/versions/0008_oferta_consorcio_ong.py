"""relaciona ofertas consorcio con sus ONGs participantes

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oferta_consorcio_ong",
        sa.Column("oferta_id", sa.Integer(), nullable=False),
        sa.Column("ong_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["oferta_id"], ["oferta.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ong_id"], ["ong.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("oferta_id", "ong_id"),
    )


def downgrade() -> None:
    op.drop_table("oferta_consorcio_ong")
