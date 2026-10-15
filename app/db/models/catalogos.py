"""Catálogo versionado y acreditaciones institucionales con vigencia explícita."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.comunes import ActualizadoMixin, CreadoMixin
from app.db.models.enums import EstadoAcreditacion, NivelRiesgo, TipoRecurso

nivel_riesgo = Enum(NivelRiesgo, name="nivel_riesgo")


class Unidad(Base):
    """Unidad predefinida por migración; la API sólo permite consultarla."""

    __tablename__ = "unidad"
    __table_args__ = (
        CheckConstraint("btrim(codigo) <> ''", name="ck_unidad_codigo"),
        CheckConstraint("btrim(nombre) <> ''", name="ck_unidad_nombre"),
    )

    codigo: Mapped[str] = mapped_column(String(40), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80))


class Capacidad(ActualizadoMixin, Base):
    """Define una capacidad y su unidad canónica sin conversiones implícitas."""

    __tablename__ = "capacidad"
    __table_args__ = (
        CheckConstraint("btrim(codigo) <> ''", name="ck_capacidad_codigo"),
        CheckConstraint("btrim(nombre) <> ''", name="ck_capacidad_nombre"),
        CheckConstraint("btrim(unidad) <> ''", name="ck_capacidad_unidad"),
        CheckConstraint(
            "tipo NOT IN ('PERSONAL', 'VEHICULO') OR NOT admite_fracciones",
            name="ck_capacidad_discreta",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    codigo: Mapped[str] = mapped_column(String(80), unique=True)
    nombre: Mapped[str] = mapped_column(String(160))
    tipo: Mapped[TipoRecurso] = mapped_column(Enum(TipoRecurso, name="tipo_recurso"))
    unidad: Mapped[str] = mapped_column(
        ForeignKey("unidad.codigo", name="fk_capacidad_unidad", ondelete="RESTRICT")
    )
    admite_fracciones: Mapped[bool] = mapped_column(server_default=text("false"))
    activa: Mapped[bool] = mapped_column(server_default=text("true"))


class Certificacion(ActualizadoMixin, Base):
    """Una revisión otorgada conserva los alcances con los que fue emitida."""

    __tablename__ = "certificacion"
    __table_args__ = (
        UniqueConstraint("codigo", "revision", name="uq_certificacion_revision"),
        CheckConstraint("btrim(codigo) <> ''", name="ck_certificacion_codigo"),
        CheckConstraint("btrim(nombre) <> ''", name="ck_certificacion_nombre"),
        CheckConstraint("revision > 0", name="ck_certificacion_revision"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    codigo: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column()
    nombre: Mapped[str] = mapped_column(String(160))
    activa: Mapped[bool] = mapped_column(server_default=text("false"))


class CertificacionCapacidad(CreadoMixin, Base):
    __tablename__ = "certificacion_capacidad"
    __table_args__ = (Index("ix_certificacion_capacidad", "capacidad_id"),)

    certificacion_id: Mapped[UUID] = mapped_column(
        ForeignKey("certificacion.id", ondelete="RESTRICT"), primary_key=True
    )
    capacidad_id: Mapped[UUID] = mapped_column(
        ForeignKey("capacidad.id", ondelete="RESTRICT"), primary_key=True
    )
    riesgo_maximo: Mapped[NivelRiesgo] = mapped_column(nivel_riesgo)


class OngCertificacion(CreadoMixin, Base):
    """Registra una credencial verificada; una renovación crea otra fila."""

    __tablename__ = "ong_certificacion"
    __table_args__ = (
        UniqueConstraint(
            "ong_id", "emisor", "numero_credencial", name="uq_ong_credencial"
        ),
        CheckConstraint("btrim(emisor) <> ''", name="ck_acreditacion_emisor"),
        CheckConstraint(
            "btrim(numero_credencial) <> ''", name="ck_acreditacion_numero"
        ),
        CheckConstraint(
            "vigente_hasta > vigente_desde "
            "AND isfinite(vigente_desde) AND isfinite(vigente_hasta)",
            name="ck_acreditacion_vigencia",
        ),
        CheckConstraint(
            "(estado = 'OTORGADA' AND revocada_en IS NULL "
            "AND revocada_por_id IS NULL AND motivo_revocacion IS NULL) "
            "OR (estado = 'REVOCADA' AND revocada_en IS NOT NULL "
            "AND revocada_por_id IS NOT NULL "
            "AND motivo_revocacion IS NOT NULL "
            "AND btrim(motivo_revocacion) <> '' "
            "AND revocada_en >= creado_en)",
            name="ck_acreditacion_revocacion",
        ),
        Index("ix_acreditacion_ong_vigencia", "ong_id", "estado", "vigente_hasta"),
        Index("ix_acreditacion_certificacion", "certificacion_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ong_id: Mapped[UUID] = mapped_column(ForeignKey("ong.id", ondelete="RESTRICT"))
    certificacion_id: Mapped[UUID] = mapped_column(
        ForeignKey("certificacion.id", ondelete="RESTRICT")
    )
    emisor: Mapped[str] = mapped_column(String(160))
    numero_credencial: Mapped[str] = mapped_column(String(120))
    vigente_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    vigente_hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estado: Mapped[EstadoAcreditacion] = mapped_column(
        Enum(EstadoAcreditacion, name="estado_acreditacion"), server_default="OTORGADA"
    )
    registrada_por_id: Mapped[UUID] = mapped_column(
        ForeignKey("cuenta.id", ondelete="RESTRICT")
    )
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocada_por_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cuenta.id", ondelete="RESTRICT")
    )
    motivo_revocacion: Mapped[str | None] = mapped_column(String(255))
