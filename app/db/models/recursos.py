"""Inventario homogéneo cuya disponibilidad se deriva de los compromisos activos."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.comunes import ActualizadoMixin


class Recurso(ActualizadoMixin, Base):
    __tablename__ = "recurso"
    __table_args__ = (
        UniqueConstraint("ong_id", "codigo_interno", name="uq_recurso_codigo_ong"),
        UniqueConstraint("id", "ong_id", name="uq_recurso_id_ong"),
        CheckConstraint("btrim(nombre) <> ''", name="ck_recurso_nombre"),
        CheckConstraint("btrim(codigo_interno) <> ''", name="ck_recurso_codigo"),
        CheckConstraint(
            "cantidad_total >= 0 AND cantidad_total < 'Infinity'::numeric",
            name="ck_recurso_total_finito",
        ),
        Index("ix_recurso_ong_activo", "ong_id", "activo"),
        Index("ix_recurso_capacidad_activo", "capacidad_id", "activo"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ong_id: Mapped[UUID] = mapped_column(ForeignKey("ong.id", ondelete="RESTRICT"))
    capacidad_id: Mapped[UUID] = mapped_column(
        ForeignKey("capacidad.id", ondelete="RESTRICT")
    )
    codigo_interno: Mapped[str] = mapped_column(String(80))
    nombre: Mapped[str] = mapped_column(String(160))
    cantidad_total: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    activo: Mapped[bool] = mapped_column(server_default=text("true"))
