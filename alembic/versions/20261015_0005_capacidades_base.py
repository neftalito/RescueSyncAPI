"""Instalar capacidades de referencia en todos los entornos.

Revision ID: 20261015_0005
Revises: 20261015_0004
"""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision: str = "20261015_0005"
down_revision: str | None = "20261015_0004"
branch_labels: str | None = None
depends_on: str | None = None

# Snapshot de referencia: no importar modelos ni catálogos que puedan evolucionar.
CAPACIDADES: tuple[tuple[str, str, str, str, bool], ...] = (
    ("PARAMEDICOS", "Personal paramédico", "PERSONAL", "personas", False),
    ("MEDICOS", "Personal médico", "PERSONAL", "personas", False),
    ("ENFERMEROS", "Personal de enfermería", "PERSONAL", "personas", False),
    ("BOMBEROS", "Bomberos", "PERSONAL", "personas", False),
    ("RESCATISTAS_URBANOS", "Rescatistas urbanos", "PERSONAL", "personas", False),
    ("RESCATISTAS_ACUATICOS", "Rescatistas acuáticos", "PERSONAL", "personas", False),
    ("RESCATISTAS_ALTURA", "Rescatistas en altura", "PERSONAL", "personas", False),
    ("PSICOLOGOS", "Personal de psicología", "PERSONAL", "personas", False),
    ("VETERINARIOS", "Personal veterinario", "PERSONAL", "personas", False),
    ("PERSONAL_LOGISTICA", "Personal de logística", "PERSONAL", "personas", False),
    (
        "OPERADORES_COMUNICACIONES",
        "Operadores de comunicaciones",
        "PERSONAL",
        "personas",
        False,
    ),
    (
        "VOLUNTARIOS_APOYO",
        "Voluntariado de apoyo general",
        "PERSONAL",
        "personas",
        False,
    ),
    ("AMBULANCIAS", "Ambulancias", "VEHICULO", "vehículos", False),
    ("CAMIONETAS_4X4", "Camionetas 4x4", "VEHICULO", "vehículos", False),
    ("CAMIONES_CARGA", "Camiones de carga", "VEHICULO", "vehículos", False),
    (
        "CAMIONES_CISTERNA_AGUA",
        "Camiones cisterna para agua",
        "VEHICULO",
        "vehículos",
        False,
    ),
    (
        "MINIBUSES",
        "Minibuses para traslado de personas",
        "VEHICULO",
        "vehículos",
        False,
    ),
    ("LANCHAS_RESCATE", "Lanchas de rescate", "VEHICULO", "vehículos", False),
    ("BOTES_RESCATE", "Botes de rescate sin motor", "VEHICULO", "vehículos", False),
    ("EXCAVADORAS", "Excavadoras", "VEHICULO", "vehículos", False),
    ("AUTOBOMBAS", "Autobombas contra incendios", "VEHICULO", "vehículos", False),
    ("GENERADORES", "Generadores eléctricos", "EQUIPAMIENTO", "equipos", False),
    ("MOTOBOMBAS", "Motobombas de desagote", "EQUIPAMIENTO", "equipos", False),
    (
        "POTABILIZADORES",
        "Equipos potabilizadores de agua",
        "EQUIPAMIENTO",
        "equipos",
        False,
    ),
    (
        "TANQUES_AGUA",
        "Tanques para almacenar agua potable",
        "EQUIPAMIENTO",
        "unidades",
        False,
    ),
    ("RADIOS", "Radios de comunicación", "EQUIPAMIENTO", "equipos", False),
    (
        "TELEFONOS_SATELITALES",
        "Teléfonos satelitales",
        "EQUIPAMIENTO",
        "equipos",
        False,
    ),
    (
        "ILUMINACION_PORTATIL",
        "Equipos de iluminación portátil",
        "EQUIPAMIENTO",
        "equipos",
        False,
    ),
    ("CAMILLAS", "Camillas", "EQUIPAMIENTO", "unidades", False),
    (
        "DESFIBRILADORES",
        "Desfibriladores externos automáticos",
        "EQUIPAMIENTO",
        "equipos",
        False,
    ),
    ("BOTIQUINES", "Botiquines de primeros auxilios", "EQUIPAMIENTO", "kits", False),
    ("CARPAS", "Carpas de alojamiento", "EQUIPAMIENTO", "unidades", False),
    ("CATRES", "Catres", "EQUIPAMIENTO", "unidades", False),
    ("COLCHONES", "Colchones", "EQUIPAMIENTO", "unidades", False),
    ("BANOS_PORTATILES", "Baños portátiles", "EQUIPAMIENTO", "unidades", False),
    ("COCINAS_CAMPANA", "Cocinas de campaña", "EQUIPAMIENTO", "equipos", False),
    (
        "EQUIPOS_RESCATE_HIDRAULICO",
        "Equipos de rescate hidráulico",
        "EQUIPAMIENTO",
        "equipos",
        False,
    ),
    ("CUERDAS_RESCATE", "Cuerdas de rescate", "EQUIPAMIENTO", "metros", True),
    ("CHALECOS_SALVAVIDAS", "Chalecos salvavidas", "EQUIPAMIENTO", "unidades", False),
    ("AGUA", "Agua potable", "SUMINISTRO", "litros", True),
    ("ALIMENTOS", "Alimentos no perecederos", "SUMINISTRO", "kg", True),
    (
        "RACIONES",
        "Raciones de alimento listas para consumo",
        "SUMINISTRO",
        "raciones",
        False,
    ),
    ("MANTAS", "Mantas", "SUMINISTRO", "unidades", False),
    ("ABRIGOS", "Abrigos", "SUMINISTRO", "unidades", False),
    ("CALZADO", "Calzado", "SUMINISTRO", "pares", False),
    ("KITS_HIGIENE", "Kits de higiene personal", "SUMINISTRO", "kits", False),
    ("KITS_LIMPIEZA", "Kits de limpieza", "SUMINISTRO", "kits", False),
    ("PANALES_ADULTOS", "Pañales para adultos", "SUMINISTRO", "unidades", False),
    ("PANALES_INFANTILES", "Pañales infantiles", "SUMINISTRO", "unidades", False),
    ("BARBIJOS", "Barbijos", "SUMINISTRO", "unidades", False),
    ("GUANTES_DESCARTABLES", "Guantes descartables", "SUMINISTRO", "pares", False),
    ("ALCOHOL", "Alcohol de uso sanitario", "SUMINISTRO", "litros", True),
    ("DESINFECTANTE", "Desinfectante para superficies", "SUMINISTRO", "litros", True),
    ("COMBUSTIBLE_DIESEL", "Combustible diésel", "SUMINISTRO", "litros", True),
    ("COMBUSTIBLE_NAFTA", "Combustible nafta", "SUMINISTRO", "litros", True),
    ("BOLSAS_ARENA", "Bolsas de arena para contención", "SUMINISTRO", "bolsas", False),
)


def upgrade() -> None:
    capacidades = sa.table(
        "capacidad",
        sa.column("id", sa.Uuid()),
        sa.column("codigo", sa.String(80)),
        sa.column("nombre", sa.String(160)),
        sa.column(
            "tipo",
            sa.Enum(
                "PERSONAL",
                "VEHICULO",
                "EQUIPAMIENTO",
                "SUMINISTRO",
                name="tipo_recurso",
            ),
        ),
        sa.column("unidad", sa.String(40)),
        sa.column("admite_fracciones", sa.Boolean()),
    )
    op.execute(
        insert(capacidades)
        .values(
            [
                {
                    "id": uuid5(NAMESPACE_URL, f"rescuesync:capacidad:{codigo}"),
                    "codigo": codigo,
                    "nombre": nombre,
                    "tipo": tipo,
                    "unidad": unidad,
                    "admite_fracciones": fracciones,
                }
                for codigo, nombre, tipo, unidad, fracciones in CAPACIDADES
            ]
        )
        .on_conflict_do_nothing(index_elements=["codigo"])
    )


def downgrade() -> None:
    """Conserva el catálogo: puede tener stock, acreditaciones y referencias externas."""
