"""Crear el catálogo fijo de unidades para todos los entornos.

Revision ID: 20261014_0002
Revises: 20261004_0001
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0002"
down_revision: str | None = "20261004_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    unidades = op.create_table(
        "unidad",
        sa.Column("codigo", sa.String(40), primary_key=True),
        sa.Column("nombre", sa.String(80), nullable=False),
        sa.CheckConstraint("btrim(codigo) <> ''", name="ck_unidad_codigo"),
        sa.CheckConstraint("btrim(nombre) <> ''", name="ck_unidad_nombre"),
    )
    # Datos de referencia obligatorios, independientes del seed de demostración.
    op.bulk_insert(
        unidades,
        [
            {"codigo": codigo, "nombre": nombre}
            for codigo, nombre in (
                ("unidades", "Unidades"),
                ("personas", "Personas"),
                ("vehículos", "Vehículos"),
                ("equipos", "Equipos"),
                ("kits", "Kits"),
                ("pares", "Pares"),
                ("juegos", "Juegos"),
                ("paquetes", "Paquetes"),
                ("cajas", "Cajas"),
                ("bolsas", "Bolsas"),
                ("bidones", "Bidones"),
                ("botellas", "Botellas"),
                ("raciones", "Raciones"),
                ("dosis", "Dosis"),
                ("camas", "Camas"),
                ("plazas", "Plazas"),
                ("litros", "Litros"),
                ("mililitros", "Mililitros"),
                ("metros cúbicos", "Metros cúbicos"),
                ("kg", "Kilogramos (kg)"),
                ("gramos", "Gramos"),
                ("toneladas", "Toneladas"),
                ("metros", "Metros"),
                ("kilómetros", "Kilómetros"),
                ("metros cuadrados", "Metros cuadrados"),
                ("hectáreas", "Hectáreas"),
                ("horas", "Horas"),
                ("días", "Días"),
                ("viajes", "Viajes"),
                ("servicios", "Servicios"),
                ("turnos", "Turnos"),
            )
        ],
    )
    # Conservar unidades ya usadas sin convertir ni modificar capacidades históricas.
    op.execute("""
        INSERT INTO unidad (codigo, nombre)
        SELECT DISTINCT unidad, unidad FROM capacidad
        ON CONFLICT (codigo) DO NOTHING
    """)
    op.create_foreign_key(
        "fk_capacidad_unidad",
        "capacidad",
        "unidad",
        ["unidad"],
        ["codigo"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_capacidad_unidad", "capacidad", type_="foreignkey")
    op.drop_table("unidad")
