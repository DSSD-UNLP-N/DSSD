"""estado de la adjudicación (reserva, compromiso, liberación, cierre) y fuera las tablas de compromiso

Las filas que ya existen quedan ADJUDICADAS: eran compromisos firmes. Las tablas `compromiso*` nunca se usaron.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch: en SQLite recrea la tabla; en Postgres es un ALTER común.
    with op.batch_alter_table("adjudicacion") as batch:
        batch.add_column(sa.Column("estado", sa.String(length=20), nullable=False, server_default="ADJUDICADA"))
        batch.create_check_constraint(
            "estadoadjudicacion", "estado IN ('RESERVADA', 'ADJUDICADA', 'LIBERADA', 'CERRADA')"
        )
    op.drop_index(op.f("ix_compromiso_item_id"), table_name="compromiso_item")
    op.drop_table("compromiso_item")
    op.drop_index(op.f("ix_compromiso_id"), table_name="compromiso")
    op.drop_index(op.f("ix_compromiso_emergencia_id"), table_name="compromiso")
    op.drop_table("compromiso")


def downgrade() -> None:
    op.create_table(
        "compromiso",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("emergencia_id", sa.Integer(), nullable=False),
        sa.Column("ong_id", sa.Integer(), nullable=False),
        sa.Column(
            "estado",
            sa.Enum("ACTIVO", "LIBERADO", name="estadocompromiso", native_enum=False, create_constraint=True, length=20),
            server_default="ACTIVO",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["ong_id"], ["ong.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("emergencia_id", "ong_id", name="uq_compromiso_emergencia_ong"),
    )
    op.create_index(op.f("ix_compromiso_emergencia_id"), "compromiso", ["emergencia_id"], unique=False)
    op.create_index(op.f("ix_compromiso_id"), "compromiso", ["id"], unique=False)
    op.create_table(
        "compromiso_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("compromiso_id", sa.Integer(), nullable=False),
        sa.Column("tipo_recurso_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.CheckConstraint("cantidad > 0", name="ck_compromiso_item_cantidad"),
        sa.ForeignKeyConstraint(["compromiso_id"], ["compromiso.id"]),
        sa.ForeignKeyConstraint(["tipo_recurso_id"], ["tipo_recurso.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("compromiso_id", "tipo_recurso_id", name="uq_compromiso_item_recurso"),
    )
    op.create_index(op.f("ix_compromiso_item_id"), "compromiso_item", ["id"], unique=False)
    with op.batch_alter_table("adjudicacion") as batch:
        batch.drop_constraint("estadoadjudicacion", type_="check")
        batch.drop_column("estado")
