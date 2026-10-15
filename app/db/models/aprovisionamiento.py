"""Correlación durable del alta institucional con su instalación de origen."""

from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AprovisionamientoOng(Base):
    __tablename__ = "aprovisionamiento_ong"

    sistema_origen_id: Mapped[UUID] = mapped_column(
        ForeignKey("sistema_origen.id", ondelete="RESTRICT"), primary_key=True
    )
    referencia_local: Mapped[UUID] = mapped_column(primary_key=True)
    ong_id: Mapped[UUID] = mapped_column(
        ForeignKey("ong.id", ondelete="RESTRICT"), unique=True
    )
    huella: Mapped[str] = mapped_column(String(64))
