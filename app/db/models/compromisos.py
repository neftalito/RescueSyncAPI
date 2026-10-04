"""Asignaciones efectivas e historial nacional de operaciones idempotentes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.catalogos import nivel_riesgo
from app.db.models.comunes import ActualizadoMixin, CreadoMixin
from app.db.models.enums import (
    EstadoCompromiso,
    EstadoProyecto,
    NivelRiesgo,
    TipoOperacion,
)

type RespuestaOperacion = dict[str, str | int | bool | list[str]]


class Proyecto(ActualizadoMixin, Base):
    """Correlaciona una emergencia externa sin copiar su dominio local."""

    __tablename__ = "proyecto"
    __table_args__ = (
        UniqueConstraint(
            "sistema_origen_id", "emergencia_ref", name="uq_proyecto_emergencia"
        ),
        UniqueConstraint("id", "sistema_origen_id", name="uq_proyecto_id_origen"),
        CheckConstraint("btrim(emergencia_ref) <> ''", name="ck_proyecto_emergencia"),
        CheckConstraint("btrim(case_ref) <> ''", name="ck_proyecto_caso"),
        CheckConstraint(
            "(estado = 'ABIERTO' AND cerrado_en IS NULL AND cerrado_por_id IS NULL) "
            "OR (estado = 'TERMINADO' AND cerrado_en IS NOT NULL "
            "AND cerrado_por_id IS NOT NULL AND cerrado_en >= creado_en)",
            name="ck_proyecto_cierre",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sistema_origen_id: Mapped[UUID] = mapped_column(
        ForeignKey("sistema_origen.id", ondelete="RESTRICT")
    )
    emergencia_ref: Mapped[str] = mapped_column(String(120))
    case_ref: Mapped[str] = mapped_column(String(120))
    estado: Mapped[EstadoProyecto] = mapped_column(
        Enum(EstadoProyecto, name="estado_proyecto"), server_default="ABIERTO"
    )
    cerrado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cerrado_por_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cuenta.id", ondelete="RESTRICT")
    )


class OperacionIdempotente(CreadoMixin, Base):
    """Reclamo y respuesta se confirman en la misma transacción del negocio."""

    __tablename__ = "operacion_idempotente"
    __table_args__ = (
        UniqueConstraint(
            "sistema_origen_id", "operacion", "clave", name="uq_operacion_clave"
        ),
        UniqueConstraint("id", "proyecto_id", name="uq_operacion_id_proyecto"),
        ForeignKeyConstraint(
            ["proyecto_id", "sistema_origen_id"],
            ["proyecto.id", "proyecto.sistema_origen_id"],
            name="fk_operacion_proyecto_origen",
            ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(clave) <> ''", name="ck_operacion_clave"),
        CheckConstraint("huella_sha256 ~ '^[0-9a-f]{64}$'", name="ck_operacion_huella"),
        CheckConstraint(
            "codigo_http IS NULL OR codigo_http BETWEEN 200 AND 299",
            name="ck_operacion_codigo_exitoso",
        ),
        CheckConstraint(
            "respuesta_minima IS NULL OR jsonb_typeof(respuesta_minima) = 'object'",
            name="ck_operacion_respuesta_objeto",
        ),
        Index("ix_operacion_proyecto", "proyecto_id"),
        Index("ix_operacion_cuenta", "cuenta_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sistema_origen_id: Mapped[UUID] = mapped_column(
        ForeignKey("sistema_origen.id", ondelete="RESTRICT")
    )
    cuenta_id: Mapped[UUID] = mapped_column(
        ForeignKey("cuenta.id", ondelete="RESTRICT")
    )
    proyecto_id: Mapped[UUID | None] = mapped_column()
    operacion: Mapped[TipoOperacion] = mapped_column(
        Enum(TipoOperacion, name="tipo_operacion")
    )
    clave: Mapped[str] = mapped_column(String(160))
    huella_sha256: Mapped[str] = mapped_column(CHAR(64))
    codigo_http: Mapped[int | None] = mapped_column(SmallInteger)
    respuesta_minima: Mapped[RespuestaOperacion | None] = mapped_column(
        JSONB(none_as_null=True)
    )


class Compromiso(ActualizadoMixin, Base):
    """Reserva de una participante; liberar conserva ítems y primera fecha."""

    __tablename__ = "compromiso"
    __table_args__ = (
        UniqueConstraint(
            "proyecto_id",
            "adjudicacion_ref",
            "ong_id",
            name="uq_compromiso_adjudicacion",
        ),
        UniqueConstraint("id", "ong_id", name="uq_compromiso_id_ong"),
        ForeignKeyConstraint(
            ["operacion_creacion_id", "proyecto_id"],
            ["operacion_idempotente.id", "operacion_idempotente.proyecto_id"],
            name="fk_compromiso_operacion_proyecto",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "btrim(adjudicacion_ref) <> ''", name="ck_compromiso_adjudicacion"
        ),
        CheckConstraint(
            "(estado = 'ACTIVO' AND liberado_en IS NULL AND liberado_por_id IS NULL) "
            "OR (estado = 'LIBERADO' AND liberado_en IS NOT NULL "
            "AND liberado_por_id IS NOT NULL AND liberado_en >= creado_en)",
            name="ck_compromiso_liberacion",
        ),
        Index("ix_compromiso_proyecto_estado", "proyecto_id", "estado"),
        Index("ix_compromiso_ong_estado", "ong_id", "estado"),
        Index("ix_compromiso_operacion", "operacion_creacion_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proyecto_id: Mapped[UUID] = mapped_column(
        ForeignKey("proyecto.id", ondelete="RESTRICT")
    )
    ong_id: Mapped[UUID] = mapped_column(ForeignKey("ong.id", ondelete="RESTRICT"))
    operacion_creacion_id: Mapped[UUID] = mapped_column()
    adjudicacion_ref: Mapped[str] = mapped_column(String(120))
    estado: Mapped[EstadoCompromiso] = mapped_column(
        Enum(EstadoCompromiso, name="estado_compromiso"), server_default="ACTIVO"
    )
    liberado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    liberado_por_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cuenta.id", ondelete="RESTRICT")
    )
    items: Mapped[list[CompromisoItem]] = relationship(
        back_populates="compromiso",
        foreign_keys="CompromisoItem.compromiso_id",
        passive_deletes="all",
    )


class CompromisoItem(CreadoMixin, Base):
    """Aporte adjudicado inmutable con pertenencia validada por FKs compuestas."""

    __tablename__ = "compromiso_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["compromiso_id", "ong_id"],
            ["compromiso.id", "compromiso.ong_id"],
            name="fk_item_compromiso_ong",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["recurso_id", "ong_id"],
            ["recurso.id", "recurso.ong_id"],
            name="fk_item_recurso_ong",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "compromiso_id", "aporte_ref", "recurso_id", name="uq_item_aporte_recurso"
        ),
        CheckConstraint(
            "cantidad > 0 AND cantidad < 'Infinity'::numeric", name="ck_item_cantidad"
        ),
        CheckConstraint("oferta_version > 0", name="ck_item_version"),
        CheckConstraint(
            "btrim(convocatoria_ref) <> '' AND btrim(oferta_ref) <> '' "
            "AND btrim(lote_ref) <> '' AND btrim(aporte_ref) <> ''",
            name="ck_item_referencias",
        ),
        Index("ix_item_recurso_compromiso", "recurso_id", "compromiso_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    compromiso_id: Mapped[UUID] = mapped_column()
    recurso_id: Mapped[UUID] = mapped_column()
    ong_id: Mapped[UUID] = mapped_column()
    convocatoria_ref: Mapped[str] = mapped_column(String(120))
    oferta_ref: Mapped[str] = mapped_column(String(120))
    oferta_version: Mapped[int] = mapped_column()
    lote_ref: Mapped[str] = mapped_column(String(120))
    aporte_ref: Mapped[str] = mapped_column(String(120))
    riesgo_requerido: Mapped[NivelRiesgo] = mapped_column(nivel_riesgo)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    compromiso: Mapped[Compromiso] = relationship(
        back_populates="items", foreign_keys=[compromiso_id]
    )
