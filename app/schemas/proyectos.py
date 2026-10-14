"""Finalización técnica por compromiso y cierre terminal con correlación de caso."""

from uuid import UUID

from pydantic import AwareDatetime

from app.schemas.inventario import Contrato
from app.schemas.validaciones import ReferenciaCaso


class FinalizacionRequest(Contrato):
    case_id: ReferenciaCaso


class ConfirmacionLiberacion(Contrato):
    operacion_id: UUID
    proyecto_id: UUID
    compromiso_id: UUID
    ong_nacional_id: UUID
    liberado_en: AwareDatetime


class ConfirmacionCierre(Contrato):
    operacion_id: UUID
    proyecto_id: UUID
    cerrado_en: AwareDatetime
