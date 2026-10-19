"""Correlacionar altas técnicas idempotentes por instalación emisora."""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0004"
down_revision = "20261015_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ong", "email_contacto", existing_type=sa.String(320), nullable=True
    )
    op.create_table(
        "aprovisionamiento_ong",
        sa.Column(
            "sistema_origen_id",
            sa.Uuid(),
            sa.ForeignKey("sistema_origen.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("referencia_local", sa.Uuid(), primary_key=True),
        sa.Column(
            "ong_id",
            sa.Uuid(),
            sa.ForeignKey("ong.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("huella", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    # El esquema anterior exigía contacto. El dominio .invalid nunca entrega correo.
    op.execute(
        "UPDATE ong SET email_contacto = 'no-informado+' || id::text "
        "|| '@example.invalid' WHERE email_contacto IS NULL"
    )
    op.alter_column(
        "ong", "email_contacto", existing_type=sa.String(320), nullable=False
    )
    op.drop_table("aprovisionamiento_ong")
