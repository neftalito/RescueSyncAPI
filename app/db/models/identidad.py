"""Identidades nacionales independientes de los usuarios y sesiones locales."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.comunes import ActualizadoMixin
from app.db.models.enums import EstadoOng, PropositoCuenta, RolNacional


class SistemaOrigen(ActualizadoMixin, Base):
    """Delimita proyectos y claves idempotentes de una instalación emisora."""

    __tablename__ = "sistema_origen"
    __table_args__ = (
        CheckConstraint("btrim(codigo) <> ''", name="ck_origen_codigo"),
        CheckConstraint("btrim(nombre) <> ''", name="ck_origen_nombre"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    codigo: Mapped[str] = mapped_column(String(80), unique=True)
    nombre: Mapped[str] = mapped_column(String(160))
    activo: Mapped[bool] = mapped_column(server_default=text("true"))


class Ong(ActualizadoMixin, Base):
    """Separa habilitación institucional de acreditación por capacidad."""

    __tablename__ = "ong"
    __table_args__ = (
        CheckConstraint("btrim(nombre) <> ''", name="ck_ong_nombre"),
        CheckConstraint(
            "identificador_institucional = lower(btrim(identificador_institucional)) "
            "AND identificador_institucional <> ''",
            name="ck_ong_identificador_normalizado",
        ),
        CheckConstraint("btrim(email_contacto) <> ''", name="ck_ong_email"),
        CheckConstraint(
            "telefono_contacto IS NULL OR btrim(telefono_contacto) <> ''",
            name="ck_ong_telefono",
        ),
        CheckConstraint(
            "(habilitada_en IS NULL) = (habilitada_por_id IS NULL) "
            "AND (estado <> 'HABILITADA' OR habilitada_en IS NOT NULL)",
            name="ck_ong_habilitacion",
        ),
        Index("ix_ong_estado", "estado"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identificador_institucional: Mapped[str] = mapped_column(String(80), unique=True)
    nombre: Mapped[str] = mapped_column(String(160))
    email_contacto: Mapped[str] = mapped_column(String(320))
    telefono_contacto: Mapped[str | None] = mapped_column(String(40))
    estado: Mapped[EstadoOng] = mapped_column(
        Enum(EstadoOng, name="estado_ong"), server_default="PENDIENTE"
    )
    habilitada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    habilitada_por_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "cuenta.id",
            name="fk_ong_habilitada_por",
            use_alter=True,
            ondelete="RESTRICT",
        )
    )


class Cuenta(ActualizadoMixin, Base):
    """Una cuenta representa una ONG, un emisor técnico o la administración."""

    __tablename__ = "cuenta"
    __table_args__ = (
        CheckConstraint("version_credencial > 0", name="ck_cuenta_version_credencial"),
        CheckConstraint(
            "proposito <> 'TECNICA_ONG' OR rol = 'ONG'", name="ck_cuenta_proposito_rol"
        ),
        Index(
            "uq_cuenta_tecnica_ong",
            "ong_id",
            unique=True,
            postgresql_where=text("proposito = 'TECNICA_ONG'"),
        ),
        CheckConstraint(
            "identificador_login = lower(btrim(identificador_login)) "
            "AND identificador_login <> ''",
            name="ck_cuenta_login_normalizado",
        ),
        CheckConstraint(
            "password_hash LIKE '$argon2id$%'",
            name="ck_cuenta_hash_argon2id",
        ),
        CheckConstraint(
            "(rol = 'ONG' AND ong_id IS NOT NULL AND sistema_origen_id IS NULL) "
            "OR (rol = 'INTEGRACION' AND ong_id IS NULL "
            "AND sistema_origen_id IS NOT NULL) "
            "OR (rol = 'ADMIN_NACIONAL' AND ong_id IS NULL "
            "AND sistema_origen_id IS NULL)",
            name="ck_cuenta_rol_vinculos",
        ),
        Index("ix_cuenta_ong", "ong_id"),
        Index("ix_cuenta_origen", "sistema_origen_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identificador_login: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[RolNacional] = mapped_column(Enum(RolNacional, name="rol_nacional"))
    activa: Mapped[bool] = mapped_column(server_default=text("true"))
    proposito: Mapped[PropositoCuenta] = mapped_column(
        Enum(PropositoCuenta, name="proposito_cuenta"), server_default="PERSONAL"
    )
    version_credencial: Mapped[int] = mapped_column(Integer, server_default="1")
    ong_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ong.id", ondelete="RESTRICT")
    )
    sistema_origen_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sistema_origen.id", ondelete="RESTRICT")
    )
