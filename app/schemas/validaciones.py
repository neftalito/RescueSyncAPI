"""Snapshot T34 y perfiles por aporte; cantidades nacionales exactas y transitorias."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from app.db.models import NivelRiesgo
from app.schemas.disponibilidad import CantidadAgregada, cantidad_exacta
from app.schemas.inventario import Cantidad, Codigo, Contrato
from app.schemas.perfiles import PerfilCompetencia

type CantidadExacta = Annotated[
    Cantidad, PlainSerializer(cantidad_exacta, return_type=str, when_used="json")
]
type IdLocal = Annotated[int, Field(gt=0)]
type CantidadLegacy = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
type ReferenciaCaso = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class MotivoIntegracionSnapshot(Contrato):
    codigo: str
    mensaje: str
    oferta_id: int | None = None
    version: int | None = None
    ong_id: int | None = None
    lote_id: int | None = None
    item_id: int | None = None


class ParticipanteSnapshot(Contrato):
    ong_id: IdLocal
    ong_nacional_id: UUID | None
    rol: Literal["LIDER", "MIEMBRO"]


class AporteSnapshot(Contrato):
    aporte_id: IdLocal
    ong_id: IdLocal
    ong_nacional_id: UUID | None
    recurso_nacional_id: UUID
    capacidad_nacional_id: UUID
    cantidad: CantidadExacta
    unidad: str = Field(min_length=1, max_length=40)


class ItemSnapshot(Contrato):
    item_id: IdLocal
    lote_id: IdLocal
    tipo: Literal["RECURSO", "PERSONAL", "MIXTO"]
    descripcion: str
    cantidad_ofrecida: CantidadLegacy
    cantidad_ofrecida_exacta: CantidadExacta
    unidad: str = Field(min_length=1, max_length=40)
    aportes: list[AporteSnapshot] = Field(default_factory=list)


class OfertaSnapshot(Contrato):
    oferta_id: IdLocal
    ong_id: IdLocal
    ong_nacional_id: UUID | None
    estado: Literal[
        "PRESENTADA", "EN_VALIDACION", "VALIDADA", "ADJUDICADA", "NO_ADJUDICADA"
    ]
    version: IdLocal
    presentada_en: AwareDatetime
    items: list[ItemSnapshot]
    participantes: list[ParticipanteSnapshot] = Field(default_factory=list)
    referencias_nacionales_completas: bool
    motivos_integracion: list[MotivoIntegracionSnapshot] = Field(default_factory=list)


class LoteSnapshot(Contrato):
    lote_id: IdLocal
    tipo_necesidad: str
    cantidad_publicada: CantidadLegacy
    cantidad_ofrecida: CantidadLegacy
    cantidad_publicada_exacta: CantidadExacta
    cantidad_ofrecida_exacta: CantidadAgregada
    unidad: str = Field(min_length=1, max_length=40)
    cubierto: bool
    capacidad_nacional_id: UUID | None
    codigo_capacidad: str | None
    riesgo_requerido: NivelRiesgo | None


class ValidacionRequest(Contrato):
    contrato_version: Literal[2]
    sistema_origen: Codigo
    id_emergencia: IdLocal
    case_id: ReferenciaCaso
    convocatoria_id: IdLocal
    numero: IdLocal
    gravedad: NivelRiesgo | None
    cerrada_en: AwareDatetime
    lotes_cubiertos: bool
    referencias_nacionales_completas: bool
    motivos_integracion: list[MotivoIntegracionSnapshot] = Field(default_factory=list)
    lotes: list[LoteSnapshot]
    ofertas: list[OfertaSnapshot]

    @model_validator(mode="after")
    def referencias_coherentes(self) -> Self:
        """Rechaza contradicciones locales sin inventar asociaciones históricas."""
        lotes = {lote.lote_id for lote in self.lotes}
        if len(lotes) != len(self.lotes):
            raise ValueError("Los lotes no pueden repetirse.")
        if len({o.oferta_id for o in self.ofertas}) != len(self.ofertas):
            raise ValueError("Las ofertas no pueden repetirse.")
        aportes: set[int] = set()
        items: set[int] = set()
        for oferta in self.ofertas:
            participantes = {p.ong_id: p for p in oferta.participantes}
            if len(participantes) != len(oferta.participantes):
                raise ValueError("Las participantes no pueden repetirse.")
            nacionales = [p.ong_nacional_id for p in oferta.participantes]
            nacionales = [n for n in nacionales if n is not None]
            if len(set(nacionales)) != len(nacionales):
                raise ValueError("Una ONG nacional no puede representar dos miembros.")
            if participantes:
                lideres = [p for p in oferta.participantes if p.rol == "LIDER"]
                if (
                    len(lideres) != 1
                    or lideres[0].ong_id != oferta.ong_id
                    or lideres[0].ong_nacional_id != oferta.ong_nacional_id
                ):
                    raise ValueError("La líder no coincide con la creadora.")
            for item in oferta.items:
                if item.lote_id not in lotes or item.item_id in items:
                    raise ValueError("El ítem debe identificar un lote del snapshot.")
                items.add(item.item_id)
                if item.aportes and (
                    sum((a.cantidad for a in item.aportes), Decimal(0))
                    != item.cantidad_ofrecida_exacta
                ):
                    raise ValueError("El desglose no coincide con la cantidad exacta.")
                for aporte in item.aportes:
                    participante = participantes.get(aporte.ong_id)
                    if (
                        aporte.aporte_id in aportes
                        or participante is None
                        or participante.ong_nacional_id != aporte.ong_nacional_id
                    ):
                        raise ValueError("El aporte debe identificar una participante.")
                    aportes.add(aporte.aporte_id)
        return self


class CodigoMotivoValidacion(StrEnum):
    ONG_NO_ENCONTRADA = "ONG_NO_ENCONTRADA"
    ONG_NO_HABILITADA = "ONG_NO_HABILITADA"
    REFERENCIAS_INCOMPLETAS = "REFERENCIAS_INCOMPLETAS"
    DESGLOSE_NACIONAL_AUSENTE = "DESGLOSE_NACIONAL_AUSENTE"
    RECURSO_NO_ENCONTRADO = "RECURSO_NO_ENCONTRADO"
    RECURSO_INACTIVO = "RECURSO_INACTIVO"
    RECURSO_AJENO = "RECURSO_AJENO"
    CAPACIDAD_NO_ENCONTRADA = "CAPACIDAD_NO_ENCONTRADA"
    CAPACIDAD_INACTIVA = "CAPACIDAD_INACTIVA"
    CAPACIDAD_INCOMPATIBLE = "CAPACIDAD_INCOMPATIBLE"
    UNIDAD_INCOMPATIBLE = "UNIDAD_INCOMPATIBLE"
    CANTIDAD_NO_DISCRETA = "CANTIDAD_NO_DISCRETA"
    DISPONIBILIDAD_INSUFICIENTE = "DISPONIBILIDAD_INSUFICIENTE"


class MotivoValidacion(Contrato):
    codigo: CodigoMotivoValidacion
    mensaje: str


class PerfilAporte(Contrato):
    perfil_competencia: PerfilCompetencia | None
    cantidad_disponible_consultada: CantidadAgregada | None
    motivos: list[MotivoValidacion]


class AporteEvaluado(PerfilAporte):
    oferta_id: int
    version: int
    item_id: int
    lote_id: int
    aporte_id: int | None
    ong_id: int
    ong_nacional_id: UUID | None
    recurso_nacional_id: UUID | None
    cantidad_ofrecida: CantidadExacta
    unidad: str


class RecursoConsultado(Contrato):
    recurso_nacional_id: UUID
    ong_nacional_id: UUID
    capacidad_nacional_id: UUID
    unidad: str
    cantidad_disponible: CantidadAgregada
    cantidad_solicitada_snapshot: CantidadAgregada


class ValidacionResponse(Contrato):
    contrato_version: Literal[3] = 3
    sistema_origen: str
    id_emergencia: int
    case_id: str
    convocatoria_id: int
    numero: int
    evaluado_en: AwareDatetime
    aportes: list[AporteEvaluado]
    recursos_consultados: list[RecursoConsultado]
