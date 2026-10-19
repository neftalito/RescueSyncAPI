"""Catálogo, credenciales verificadas y perfiles calculados sin reservar recursos."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.db.models.enums import EstadoAcreditacion, EstadoOng, NivelRiesgo, TipoRecurso
from app.schemas.inventario import Codigo, Contrato, Nombre


class EstadoVigencia(StrEnum):
    FUTURA = "FUTURA"
    VIGENTE = "VIGENTE"
    VENCIDA = "VENCIDA"
    REVOCADA = "REVOCADA"


class CodigoMotivo(StrEnum):
    ACREDITACION_FUTURA = "ACREDITACION_FUTURA"
    ACREDITACION_VENCIDA = "ACREDITACION_VENCIDA"
    ACREDITACION_REVOCADA = "ACREDITACION_REVOCADA"
    CERTIFICACION_INACTIVA = "CERTIFICACION_INACTIVA"
    CAPACIDAD_INACTIVA = "CAPACIDAD_INACTIVA"
    ONG_PENDIENTE = "ONG_PENDIENTE"
    ONG_SUSPENDIDA = "ONG_SUSPENDIDA"
    ONG_BAJA = "ONG_BAJA"


class MotivoResponse(Contrato):
    codigo: CodigoMotivo
    mensaje: str
    capacidad_id: UUID | None = None


class AlcanceResponse(Contrato):
    capacidad_id: UUID
    codigo: str
    nombre: str
    tipo: TipoRecurso
    unidad: str
    admite_fracciones: bool
    activa: bool
    riesgo_maximo: NivelRiesgo


class CertificacionResponse(Contrato):
    id: UUID
    codigo: str
    revision: int
    nombre: str
    activa: bool
    alcances: list[AlcanceResponse]


class AcreditacionResponse(Contrato):
    id: UUID
    certificacion: CertificacionResponse
    emisor: str
    numero_credencial: str
    vigente_desde: AwareDatetime
    vigente_hasta: AwareDatetime
    estado: EstadoAcreditacion
    estado_vigencia: EstadoVigencia
    revocada_en: AwareDatetime | None
    motivo_revocacion: str | None
    motivos: list[MotivoResponse]


class CapacidadHabilitadaResponse(Contrato):
    capacidad_id: UUID
    codigo: str
    nombre: str
    unidad: str
    riesgo_maximo: NivelRiesgo
    niveles_riesgo_permitidos: list[NivelRiesgo]
    acreditacion_ids: list[UUID]


class CertificacionesOngResponse(Contrato):
    ong_id: UUID
    estado_ong: EstadoOng
    evaluado_en: AwareDatetime
    acreditaciones: list[AcreditacionResponse]
    capacidades_habilitadas: list[CapacidadHabilitadaResponse]
    motivos_institucionales: list[MotivoResponse]


class AlcanceCreate(Contrato):
    capacidad_id: UUID
    riesgo_maximo: NivelRiesgo


class CertificacionCreate(Contrato):
    codigo: Codigo
    revision: int = Field(gt=0)
    nombre: Nombre
    alcances: list[AlcanceCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def capacidades_unicas(self) -> Self:
        """Una revisión no repite una capacidad con riesgos contradictorios."""
        if len({a.capacidad_id for a in self.alcances}) != len(self.alcances):
            raise ValueError("Las capacidades del alcance no pueden repetirse.")
        return self


class AcreditacionCreate(Contrato):
    ong_id: UUID
    certificacion_id: UUID
    emisor: Nombre
    numero_credencial: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    vigente_desde: AwareDatetime
    vigente_hasta: AwareDatetime

    @model_validator(mode="after")
    def intervalo_valido(self) -> Self:
        """El vencimiento es exclusivo y posterior al inicio."""
        if self.vigente_hasta <= self.vigente_desde:
            raise ValueError("La vigencia final debe ser posterior al inicio.")
        return self


class RevocacionRequest(Contrato):
    ong_id: UUID
    acreditacion_id: UUID
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]


class HabilitacionRequest(Contrato):
    ong_id: UUID
