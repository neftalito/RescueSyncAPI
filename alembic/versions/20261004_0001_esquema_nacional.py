"""Crea el esquema nacional acordado en T22.

Revision ID: 20261004_0001
Revises:
"""

from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "20261004_0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# Snapshot propio de la revisión: no importar modelos o constantes de aplicación.
rol = pg.ENUM(
    "ADMIN_NACIONAL", "ONG", "INTEGRACION", name="rol_nacional", create_type=False
)
estado_ong = pg.ENUM(
    "PENDIENTE",
    "HABILITADA",
    "SUSPENDIDA",
    "BAJA",
    name="estado_ong",
    create_type=False,
)
tipo_recurso = pg.ENUM(
    "PERSONAL",
    "VEHICULO",
    "EQUIPAMIENTO",
    "SUMINISTRO",
    name="tipo_recurso",
    create_type=False,
)
riesgo = pg.ENUM(
    "BAJA", "MEDIA", "ALTA", "CRITICA", name="nivel_riesgo", create_type=False
)
acreditacion = pg.ENUM(
    "OTORGADA", "REVOCADA", name="estado_acreditacion", create_type=False
)
proyecto = pg.ENUM("ABIERTO", "TERMINADO", name="estado_proyecto", create_type=False)
compromiso = pg.ENUM("ACTIVO", "LIBERADO", name="estado_compromiso", create_type=False)
operacion = pg.ENUM(
    "COMPROMETER",
    "LIBERAR",
    "CERRAR_PROYECTO",
    name="tipo_operacion",
    create_type=False,
)
enums = (
    rol,
    estado_ong,
    tipo_recurso,
    riesgo,
    acreditacion,
    proyecto,
    compromiso,
    operacion,
)


def fechas(*, actualizable: bool = True) -> list[sa.Column[datetime]]:
    """Crea columnas independientes para cada tabla de esta revisión."""

    columns = [
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        )
    ]
    if actualizable:
        columns.append(
            sa.Column(
                "actualizado_en",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            )
        )
    return columns


def upgrade() -> None:
    """Crea tipos, tablas y las restricciones relacionales nacionales."""

    for enum in enums:
        enum.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "sistema_origen",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("codigo", sa.String(80), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column(
            "activo", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        *fechas(),
        sa.UniqueConstraint("codigo", name="uq_sistema_origen_codigo"),
        sa.CheckConstraint("btrim(codigo) <> ''", name="ck_origen_codigo"),
        sa.CheckConstraint("btrim(nombre) <> ''", name="ck_origen_nombre"),
    )
    op.create_table(
        "ong",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identificador_institucional", sa.String(80), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("email_contacto", sa.String(320), nullable=False),
        sa.Column("telefono_contacto", sa.String(40)),
        sa.Column("estado", estado_ong, nullable=False, server_default="PENDIENTE"),
        sa.Column("habilitada_en", sa.DateTime(timezone=True)),
        sa.Column("habilitada_por_id", sa.Uuid()),
        *fechas(),
        sa.UniqueConstraint(
            "identificador_institucional", name="uq_ong_identificador_institucional"
        ),
        sa.CheckConstraint("btrim(nombre) <> ''", name="ck_ong_nombre"),
        sa.CheckConstraint(
            "identificador_institucional = lower(btrim(identificador_institucional)) AND identificador_institucional <> ''",
            name="ck_ong_identificador_normalizado",
        ),
        sa.CheckConstraint("btrim(email_contacto) <> ''", name="ck_ong_email"),
        sa.CheckConstraint(
            "telefono_contacto IS NULL OR btrim(telefono_contacto) <> ''",
            name="ck_ong_telefono",
        ),
        sa.CheckConstraint(
            "(habilitada_en IS NULL) = (habilitada_por_id IS NULL) AND (estado <> 'HABILITADA' OR habilitada_en IS NOT NULL)",
            name="ck_ong_habilitacion",
        ),
    )
    op.create_index("ix_ong_estado", "ong", ["estado"])
    op.create_table(
        "cuenta",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identificador_login", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("rol", rol, nullable=False),
        sa.Column(
            "activa", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("ong_id", sa.Uuid(), sa.ForeignKey("ong.id", ondelete="RESTRICT")),
        sa.Column(
            "sistema_origen_id",
            sa.Uuid(),
            sa.ForeignKey("sistema_origen.id", ondelete="RESTRICT"),
        ),
        *fechas(),
        sa.UniqueConstraint(
            "identificador_login", name="uq_cuenta_identificador_login"
        ),
        sa.CheckConstraint(
            "identificador_login = lower(btrim(identificador_login)) AND identificador_login <> ''",
            name="ck_cuenta_login_normalizado",
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%'", name="ck_cuenta_hash_argon2id"
        ),
        sa.CheckConstraint(
            "(rol = 'ONG' AND ong_id IS NOT NULL AND sistema_origen_id IS NULL) OR (rol = 'INTEGRACION' AND ong_id IS NULL AND sistema_origen_id IS NOT NULL) OR (rol = 'ADMIN_NACIONAL' AND ong_id IS NULL AND sistema_origen_id IS NULL)",
            name="ck_cuenta_rol_vinculos",
        ),
    )
    op.create_index("ix_cuenta_ong", "cuenta", ["ong_id"])
    op.create_index("ix_cuenta_origen", "cuenta", ["sistema_origen_id"])
    op.create_foreign_key(
        "fk_ong_habilitada_por",
        "ong",
        "cuenta",
        ["habilitada_por_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "capacidad",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("codigo", sa.String(80), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("tipo", tipo_recurso, nullable=False),
        sa.Column("unidad", sa.String(40), nullable=False),
        sa.Column(
            "admite_fracciones",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "activa", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        *fechas(),
        sa.UniqueConstraint("codigo", name="uq_capacidad_codigo"),
        sa.CheckConstraint("btrim(codigo) <> ''", name="ck_capacidad_codigo"),
        sa.CheckConstraint("btrim(nombre) <> ''", name="ck_capacidad_nombre"),
        sa.CheckConstraint("btrim(unidad) <> ''", name="ck_capacidad_unidad"),
        sa.CheckConstraint(
            "tipo NOT IN ('PERSONAL', 'VEHICULO') OR NOT admite_fracciones",
            name="ck_capacidad_discreta",
        ),
    )
    op.create_table(
        "certificacion",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("codigo", sa.String(80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column(
            "activa", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        *fechas(),
        sa.UniqueConstraint("codigo", "revision", name="uq_certificacion_revision"),
        sa.CheckConstraint("btrim(codigo) <> ''", name="ck_certificacion_codigo"),
        sa.CheckConstraint("btrim(nombre) <> ''", name="ck_certificacion_nombre"),
        sa.CheckConstraint("revision > 0", name="ck_certificacion_revision"),
    )
    op.create_table(
        "certificacion_capacidad",
        sa.Column(
            "certificacion_id",
            sa.Uuid(),
            sa.ForeignKey("certificacion.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "capacidad_id",
            sa.Uuid(),
            sa.ForeignKey("capacidad.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("riesgo_maximo", riesgo, nullable=False),
        *fechas(actualizable=False),
    )
    op.create_index(
        "ix_certificacion_capacidad", "certificacion_capacidad", ["capacidad_id"]
    )
    op.create_table(
        "ong_certificacion",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ong_id",
            sa.Uuid(),
            sa.ForeignKey("ong.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "certificacion_id",
            sa.Uuid(),
            sa.ForeignKey("certificacion.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("emisor", sa.String(160), nullable=False),
        sa.Column("numero_credencial", sa.String(120), nullable=False),
        sa.Column("vigente_desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vigente_hasta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estado", acreditacion, nullable=False, server_default="OTORGADA"),
        sa.Column(
            "registrada_por_id",
            sa.Uuid(),
            sa.ForeignKey("cuenta.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revocada_en", sa.DateTime(timezone=True)),
        sa.Column(
            "revocada_por_id",
            sa.Uuid(),
            sa.ForeignKey("cuenta.id", ondelete="RESTRICT"),
        ),
        sa.Column("motivo_revocacion", sa.String(255)),
        *fechas(actualizable=False),
        sa.UniqueConstraint(
            "ong_id", "emisor", "numero_credencial", name="uq_ong_credencial"
        ),
        sa.CheckConstraint("btrim(emisor) <> ''", name="ck_acreditacion_emisor"),
        sa.CheckConstraint(
            "btrim(numero_credencial) <> ''", name="ck_acreditacion_numero"
        ),
        sa.CheckConstraint(
            "vigente_hasta > vigente_desde AND isfinite(vigente_desde) AND isfinite(vigente_hasta)",
            name="ck_acreditacion_vigencia",
        ),
        sa.CheckConstraint(
            "(estado = 'OTORGADA' AND revocada_en IS NULL AND revocada_por_id IS NULL AND motivo_revocacion IS NULL) OR (estado = 'REVOCADA' AND revocada_en IS NOT NULL AND revocada_por_id IS NOT NULL AND motivo_revocacion IS NOT NULL AND btrim(motivo_revocacion) <> '' AND revocada_en >= creado_en)",
            name="ck_acreditacion_revocacion",
        ),
    )
    op.create_index(
        "ix_acreditacion_ong_vigencia",
        "ong_certificacion",
        ["ong_id", "estado", "vigente_hasta"],
    )
    op.create_index(
        "ix_acreditacion_certificacion", "ong_certificacion", ["certificacion_id"]
    )

    op.create_table(
        "recurso",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ong_id",
            sa.Uuid(),
            sa.ForeignKey("ong.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "capacidad_id",
            sa.Uuid(),
            sa.ForeignKey("capacidad.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("codigo_interno", sa.String(80), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("cantidad_total", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "activo", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        *fechas(),
        sa.UniqueConstraint("ong_id", "codigo_interno", name="uq_recurso_codigo_ong"),
        sa.UniqueConstraint("id", "ong_id", name="uq_recurso_id_ong"),
        sa.CheckConstraint("btrim(nombre) <> ''", name="ck_recurso_nombre"),
        sa.CheckConstraint("btrim(codigo_interno) <> ''", name="ck_recurso_codigo"),
        sa.CheckConstraint(
            "cantidad_total >= 0 AND cantidad_total < 'Infinity'::numeric",
            name="ck_recurso_total_finito",
        ),
    )
    op.create_index("ix_recurso_ong_activo", "recurso", ["ong_id", "activo"])
    op.create_index(
        "ix_recurso_capacidad_activo", "recurso", ["capacidad_id", "activo"]
    )

    op.create_table(
        "proyecto",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "sistema_origen_id",
            sa.Uuid(),
            sa.ForeignKey("sistema_origen.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("emergencia_ref", sa.String(120), nullable=False),
        sa.Column("case_ref", sa.String(120), nullable=False),
        sa.Column("estado", proyecto, nullable=False, server_default="ABIERTO"),
        sa.Column("cerrado_en", sa.DateTime(timezone=True)),
        sa.Column(
            "cerrado_por_id", sa.Uuid(), sa.ForeignKey("cuenta.id", ondelete="RESTRICT")
        ),
        *fechas(),
        sa.UniqueConstraint(
            "sistema_origen_id", "emergencia_ref", name="uq_proyecto_emergencia"
        ),
        sa.UniqueConstraint("id", "sistema_origen_id", name="uq_proyecto_id_origen"),
        sa.CheckConstraint(
            "btrim(emergencia_ref) <> ''", name="ck_proyecto_emergencia"
        ),
        sa.CheckConstraint("btrim(case_ref) <> ''", name="ck_proyecto_caso"),
        sa.CheckConstraint(
            "(estado = 'ABIERTO' AND cerrado_en IS NULL AND cerrado_por_id IS NULL) OR (estado = 'TERMINADO' AND cerrado_en IS NOT NULL AND cerrado_por_id IS NOT NULL AND cerrado_en >= creado_en)",
            name="ck_proyecto_cierre",
        ),
    )
    op.create_table(
        "operacion_idempotente",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "sistema_origen_id",
            sa.Uuid(),
            sa.ForeignKey("sistema_origen.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cuenta_id",
            sa.Uuid(),
            sa.ForeignKey("cuenta.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("proyecto_id", sa.Uuid()),
        sa.Column("operacion", operacion, nullable=False),
        sa.Column("clave", sa.String(160), nullable=False),
        sa.Column("huella_sha256", sa.CHAR(64), nullable=False),
        sa.Column("codigo_http", sa.SmallInteger()),
        sa.Column("respuesta_minima", pg.JSONB(none_as_null=True)),
        *fechas(actualizable=False),
        sa.UniqueConstraint(
            "sistema_origen_id", "operacion", "clave", name="uq_operacion_clave"
        ),
        sa.UniqueConstraint("id", "proyecto_id", name="uq_operacion_id_proyecto"),
        sa.ForeignKeyConstraint(
            ["proyecto_id", "sistema_origen_id"],
            ["proyecto.id", "proyecto.sistema_origen_id"],
            name="fk_operacion_proyecto_origen",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("btrim(clave) <> ''", name="ck_operacion_clave"),
        sa.CheckConstraint(
            "huella_sha256 ~ '^[0-9a-f]{64}$'", name="ck_operacion_huella"
        ),
        sa.CheckConstraint(
            "codigo_http IS NULL OR codigo_http BETWEEN 200 AND 299",
            name="ck_operacion_codigo_exitoso",
        ),
        sa.CheckConstraint(
            "respuesta_minima IS NULL OR jsonb_typeof(respuesta_minima) = 'object'",
            name="ck_operacion_respuesta_objeto",
        ),
    )
    op.create_index("ix_operacion_proyecto", "operacion_idempotente", ["proyecto_id"])
    op.create_index("ix_operacion_cuenta", "operacion_idempotente", ["cuenta_id"])
    op.create_table(
        "compromiso",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "proyecto_id",
            sa.Uuid(),
            sa.ForeignKey("proyecto.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ong_id",
            sa.Uuid(),
            sa.ForeignKey("ong.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operacion_creacion_id", sa.Uuid(), nullable=False),
        sa.Column("adjudicacion_ref", sa.String(120), nullable=False),
        sa.Column("estado", compromiso, nullable=False, server_default="ACTIVO"),
        sa.Column("liberado_en", sa.DateTime(timezone=True)),
        sa.Column(
            "liberado_por_id",
            sa.Uuid(),
            sa.ForeignKey("cuenta.id", ondelete="RESTRICT"),
        ),
        *fechas(),
        sa.UniqueConstraint(
            "proyecto_id",
            "adjudicacion_ref",
            "ong_id",
            name="uq_compromiso_adjudicacion",
        ),
        sa.UniqueConstraint("id", "ong_id", name="uq_compromiso_id_ong"),
        sa.ForeignKeyConstraint(
            ["operacion_creacion_id", "proyecto_id"],
            ["operacion_idempotente.id", "operacion_idempotente.proyecto_id"],
            name="fk_compromiso_operacion_proyecto",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "btrim(adjudicacion_ref) <> ''", name="ck_compromiso_adjudicacion"
        ),
        sa.CheckConstraint(
            "(estado = 'ACTIVO' AND liberado_en IS NULL AND liberado_por_id IS NULL) OR (estado = 'LIBERADO' AND liberado_en IS NOT NULL AND liberado_por_id IS NOT NULL AND liberado_en >= creado_en)",
            name="ck_compromiso_liberacion",
        ),
    )
    op.create_index(
        "ix_compromiso_proyecto_estado", "compromiso", ["proyecto_id", "estado"]
    )
    op.create_index("ix_compromiso_ong_estado", "compromiso", ["ong_id", "estado"])
    op.create_index("ix_compromiso_operacion", "compromiso", ["operacion_creacion_id"])
    op.create_table(
        "compromiso_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("compromiso_id", sa.Uuid(), nullable=False),
        sa.Column("recurso_id", sa.Uuid(), nullable=False),
        sa.Column("ong_id", sa.Uuid(), nullable=False),
        sa.Column("convocatoria_ref", sa.String(120), nullable=False),
        sa.Column("oferta_ref", sa.String(120), nullable=False),
        sa.Column("oferta_version", sa.Integer(), nullable=False),
        sa.Column("lote_ref", sa.String(120), nullable=False),
        sa.Column("aporte_ref", sa.String(120), nullable=False),
        sa.Column("riesgo_requerido", riesgo, nullable=False),
        sa.Column("cantidad", sa.Numeric(14, 3), nullable=False),
        *fechas(actualizable=False),
        sa.ForeignKeyConstraint(
            ["compromiso_id", "ong_id"],
            ["compromiso.id", "compromiso.ong_id"],
            name="fk_item_compromiso_ong",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recurso_id", "ong_id"],
            ["recurso.id", "recurso.ong_id"],
            name="fk_item_recurso_ong",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "compromiso_id", "aporte_ref", "recurso_id", name="uq_item_aporte_recurso"
        ),
        sa.CheckConstraint(
            "cantidad > 0 AND cantidad < 'Infinity'::numeric", name="ck_item_cantidad"
        ),
        sa.CheckConstraint("oferta_version > 0", name="ck_item_version"),
        sa.CheckConstraint(
            "btrim(convocatoria_ref) <> '' AND btrim(oferta_ref) <> '' AND btrim(lote_ref) <> '' AND btrim(aporte_ref) <> ''",
            name="ck_item_referencias",
        ),
    )
    op.create_index(
        "ix_item_recurso_compromiso", "compromiso_item", ["recurso_id", "compromiso_id"]
    )
    crear_triggers()


def crear_triggers() -> None:
    """Define restricciones entre filas y protege el historial persistido."""

    sql = Path(__file__).with_name("20261004_0001_integridad.sql").read_text()
    op.execute(sql)


def downgrade() -> None:
    """Elimina el esquema en orden inverso; sólo en bases descartables o vacías."""

    for tabla in (
        "compromiso_item",
        "compromiso",
        "operacion_idempotente",
        "proyecto",
        "recurso",
        "ong_certificacion",
        "certificacion_capacidad",
        "certificacion",
        "capacidad",
    ):
        op.drop_table(tabla)
    op.drop_constraint("fk_ong_habilitada_por", "ong", type_="foreignkey")
    for tabla in ("cuenta", "ong", "sistema_origen"):
        op.drop_table(tabla)
    for funcion in (
        "nacional_proteger_historial",
        "nacional_proteger_revision",
        "nacional_operacion_completa",
        "nacional_compromiso_completo",
        "nacional_validar_acreditacion",
        "nacional_cantidad_discreta",
        "nacional_proteger_capacidad",
        "nacional_proteger_alcance",
        "nacional_certificacion_completa",
    ):
        op.execute(sa.text(f"DROP FUNCTION {funcion}()"))
    for enum in reversed(enums):
        enum.drop(op.get_bind(), checkfirst=False)
