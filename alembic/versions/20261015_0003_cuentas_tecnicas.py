"""Separar cuentas técnicas de ONG y permitir revocar sus tokens."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261015_0003"
down_revision = "20261014_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    proposito = postgresql.ENUM("PERSONAL", "TECNICA_ONG", name="proposito_cuenta")
    proposito.create(op.get_bind())
    op.add_column(
        "cuenta",
        sa.Column(
            "proposito",
            postgresql.ENUM(name="proposito_cuenta", create_type=False),
            nullable=False,
            server_default="PERSONAL",
        ),
    )
    op.add_column(
        "cuenta",
        sa.Column(
            "version_credencial", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.create_check_constraint(
        "ck_cuenta_version_credencial", "cuenta", "version_credencial > 0"
    )
    op.create_check_constraint(
        "ck_cuenta_proposito_rol", "cuenta", "proposito <> 'TECNICA_ONG' OR rol = 'ONG'"
    )
    op.create_index(
        "uq_cuenta_tecnica_ong",
        "cuenta",
        ["ong_id"],
        unique=True,
        postgresql_where=sa.text("proposito = 'TECNICA_ONG'"),
    )


def downgrade() -> None:
    # No convertir secretos técnicos en contraseñas personales utilizables.
    op.execute("UPDATE cuenta SET activa = false WHERE proposito = 'TECNICA_ONG'")
    op.drop_index("uq_cuenta_tecnica_ong", table_name="cuenta")
    op.drop_constraint("ck_cuenta_proposito_rol", "cuenta")
    op.drop_constraint("ck_cuenta_version_credencial", "cuenta")
    op.drop_column("cuenta", "version_credencial")
    op.drop_column("cuenta", "proposito")
    postgresql.ENUM(name="proposito_cuenta").drop(op.get_bind())
