"""Perfiles informativos derivados del inventario declarado, sin habilitaciones."""

from uuid import UUID

from pydantic import AwareDatetime

from app.db.models import EstadoOng, TipoRecurso
from app.schemas.disponibilidad import CantidadAgregada
from app.schemas.inventario import Contrato


class CapacidadDeclarada(Contrato):
    capacidad_id: UUID
    codigo: str
    nombre: str
    tipo: TipoRecurso
    unidad: str
    admite_fracciones: bool
    cantidad_total: CantidadAgregada
    cantidad_comprometida: CantidadAgregada
    cantidad_disponible: CantidadAgregada


class PerfilCompetencia(Contrato):
    ong_id: UUID
    nombre: str
    estado_ong: EstadoOng
    evaluado_en: AwareDatetime
    capacidades_declaradas: list[CapacidadDeclarada]


class DirectorioOngs(Contrato):
    evaluado_en: AwareDatetime
    ongs: list[PerfilCompetencia]
