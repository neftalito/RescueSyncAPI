"""Alta automática sin aprobación administrativa ni pérdida de historia.

Revision ID: 20261020_0006
Revises: 20261015_0005
"""

from alembic import op

revision: str = "20261020_0006"
down_revision: str | None = "20261015_0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint("ck_ong_habilitacion", "ong", type_="check")
    op.create_check_constraint(
        "ck_ong_habilitacion",
        "ong",
        "(habilitada_en IS NULL) = (habilitada_por_id IS NULL)",
    )
    op.alter_column("ong", "estado", server_default="HABILITADA")
    op.execute("UPDATE ong SET estado = 'HABILITADA' WHERE estado = 'PENDIENTE'")


def downgrade() -> None:
    # Sin autor histórico no se puede afirmar una aprobación administrativa.
    op.execute(
        "UPDATE ong SET estado = 'PENDIENTE' "
        "WHERE estado = 'HABILITADA' AND habilitada_en IS NULL"
    )
    op.alter_column("ong", "estado", server_default="PENDIENTE")
    op.drop_constraint("ck_ong_habilitacion", "ong", type_="check")
    op.create_check_constraint(
        "ck_ong_habilitacion",
        "ong",
        "(habilitada_en IS NULL) = (habilitada_por_id IS NULL) "
        "AND (estado <> 'HABILITADA' OR habilitada_en IS NOT NULL)",
    )
