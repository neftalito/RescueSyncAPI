"""Directorio institucional sin historia administrativa ni datos de contacto."""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime

from app.db.models import EstadoOng
from app.schemas.certificaciones import CapacidadHabilitadaResponse
from app.schemas.inventario import Contrato


class CodigoMotivoPerfil(StrEnum):
    SIN_COMPETENCIAS_VIGENTES = "SIN_COMPETENCIAS_VIGENTES"


class MotivoPerfilResponse(Contrato):
    codigo: CodigoMotivoPerfil
    mensaje: str


class OngHabilitadaResponse(Contrato):
    ong_id: UUID
    nombre: str
    estado_ong: EstadoOng
    capacidades_habilitadas: list[CapacidadHabilitadaResponse]
    motivos_perfil: list[MotivoPerfilResponse]


class OngsHabilitadasResponse(Contrato):
    evaluado_en: AwareDatetime
    ongs: list[OngHabilitadaResponse]
