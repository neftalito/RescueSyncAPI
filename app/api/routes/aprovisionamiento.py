"""Onboarding técnico reservado a instalaciones emisoras autenticadas."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.api.dependencies import CuentaActual, Db
from app.schemas.aprovisionamiento import (
    AprovisionamientoRequest,
    AprovisionamientoResponse,
)
from app.schemas.inventario import ErrorResponse
from app.services.aprovisionamiento import (
    AprovisionamientoConflictivoError,
    AprovisionamientoDenegadoError,
    aprovisionar_ong,
)

router = APIRouter()


@router.put(
    "/integraciones/ongs/{referencia_local}",
    response_model=AprovisionamientoResponse,
    responses={codigo: {"model": ErrorResponse} for codigo in (401, 403, 409, 422)},
    summary="Aprovisionar una ONG y su cuenta técnica",
    description=(
        "Sólo INTEGRACION con emisor activo. La referencia UUID es durable por emisor. "
        "Repetir los mismos datos devuelve la misma identidad, sin rotar secretos. "
        "El backend emisor genera y conserva el secreto; nunca se devuelve por HTTP. "
        "El alta queda PENDIENTE, sin certificaciones ni habilitación institucional."
    ),
)
def aprovisionar(
    referencia_local: UUID,
    datos: AprovisionamientoRequest,
    cuenta: CuentaActual,
    session: Db,
    response: Response,
) -> AprovisionamientoResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return aprovisionar_ong(session, cuenta.id, referencia_local, datos)
    except AprovisionamientoDenegadoError as error:
        session.rollback()
        raise HTTPException(403, str(error)) from error
    except AprovisionamientoConflictivoError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
