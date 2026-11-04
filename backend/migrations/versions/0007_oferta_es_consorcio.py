"""marca de oferta presentada por consorcio

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "oferta",
        sa.Column(
            "es_consorcio",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("oferta", "es_consorcio")
