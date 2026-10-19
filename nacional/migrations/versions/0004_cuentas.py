"""cuentas para emitir tokens del Sistema Nacional

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cuenta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=60), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("ong_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["ong_id"], ["ong.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.CheckConstraint(
            "rol IN ('ONG', 'MUNICIPIO', 'COORDINADOR', 'AUDITOR', 'BONITA')",
            name="rolcuenta",
        ),
    )


def downgrade() -> None:
    op.drop_table("cuenta")
