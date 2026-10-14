"""Agregados exactos sin el límite numérico de una única fila de inventario."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field, PlainSerializer

from app.db.models import EstadoOng, TipoRecurso
from app.schemas.inventario import Contrato


def cantidad_exacta(cantidad: Decimal) -> str:
    return format(cantidad, ".3f")


type CantidadAgregada = Annotated[
    Decimal,
    Field(ge=0, decimal_places=3, allow_inf_nan=False),
    PlainSerializer(cantidad_exacta, return_type=str, when_used="json"),
]


class CantidadesResponse(Contrato):
    cantidad_total: CantidadAgregada
    cantidad_comprometida: CantidadAgregada
    cantidad_disponible: CantidadAgregada


class DisponibilidadOngResponse(CantidadesResponse):
    ong_id: UUID
    nombre: str
    estado_ong: EstadoOng


class DisponibilidadCapacidadResponse(CantidadesResponse):
    capacidad_id: UUID
    codigo: str
    nombre: str
    tipo: TipoRecurso
    unidad: str
    admite_fracciones: bool
    ongs: list[DisponibilidadOngResponse]


class DisponibilidadResponse(Contrato):
    consultado_en: AwareDatetime
    recursos: list[DisponibilidadCapacidadResponse]
