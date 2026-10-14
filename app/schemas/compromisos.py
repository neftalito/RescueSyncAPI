"""Adjudicación mínima, confirmación estable y consulta de reservas efectivas."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    Field,
    StringConstraints,
    model_validator,
)

from app.db.models import EstadoCompromiso, NivelRiesgo
from app.schemas.inventario import Codigo, Contrato
from app.schemas.validaciones import CantidadExacta, ReferenciaCaso


def referencia_externa(valor: object) -> object:
    """IDs locales positivos se guardan como referencias opacas, nunca como FKs."""
    if isinstance(valor, bool):
        raise ValueError("La referencia no puede ser booleana.")
    if isinstance(valor, int):
        if valor <= 0:
            raise ValueError("La referencia debe ser positiva.")
        return str(valor)
    return valor


type Referencia = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    BeforeValidator(referencia_externa),
]


class AporteCompromiso(Contrato):
    oferta_id: Referencia
    version: int = Field(gt=0)
    lote_id: Referencia
    aporte_id: Referencia
    ong_nacional_id: UUID
    recurso_nacional_id: UUID
    capacidad_nacional_id: UUID
    riesgo_requerido: NivelRiesgo
    cantidad: CantidadExacta
    unidad: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class CompromisoRequest(Contrato):
    sistema_origen: Codigo
    id_emergencia: Referencia
    case_id: ReferenciaCaso
    convocatoria_id: Referencia
    adjudicacion_id: Referencia
    aportes: list[AporteCompromiso] = Field(min_length=1)

    @model_validator(mode="after")
    def aportes_unicos(self) -> Self:
        """Un aporte congelado se adjudica una sola vez por solicitud completa."""
        if len({a.aporte_id for a in self.aportes}) != len(self.aportes):
            raise ValueError("Los aportes no pueden repetirse.")
        versiones: dict[str, int] = {}
        for aporte in self.aportes:
            anterior = versiones.setdefault(aporte.oferta_id, aporte.version)
            if anterior != aporte.version:
                raise ValueError("Una adjudicación usa una versión por oferta.")
        return self


class ConfirmacionCompromisos(Contrato):
    operacion_id: UUID
    proyecto_id: UUID
    compromiso_ids: list[UUID]
    registrado_en: AwareDatetime


class ItemCompromisoResponse(AporteCompromiso):
    id: UUID
    convocatoria_id: str


class CompromisoResponse(Contrato):
    id: UUID
    proyecto_id: UUID
    sistema_origen: str
    id_emergencia: str
    case_id: str
    adjudicacion_id: str
    ong_nacional_id: UUID
    estado: EstadoCompromiso
    creado_en: AwareDatetime
    liberado_en: AwareDatetime | None
    liberado_por_id: UUID | None
    items: list[ItemCompromisoResponse]
