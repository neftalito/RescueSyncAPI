"""Onboarding técnico reservado a instalaciones emisoras autenticadas."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Path, Response

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db
from app.api.documentacion import respuestas
from app.schemas.aprovisionamiento import (
    AprovisionamientoRequest,
    AprovisionamientoResponse,
)
from app.services.aprovisionamiento import (
    AprovisionamientoConflictivoError,
    AprovisionamientoDenegadoError,
    aprovisionar_ong,
)

router = APIRouter()


@router.put(
    "/integraciones/ongs/{referencia_local}",
    response_model=AprovisionamientoResponse,
    summary="Aprovisionar una ONG y su cuenta técnica",
    description=(
        "Acceso exclusivo: INTEGRACION con emisor activo. referencia_local es"
        " un UUID durable por emisor. Repetir los mismos datos devuelve la "
        "misma identidad sin rotar secretos; contenido distinto produce 409. "
        "El backend emisor genera y conserva el secreto, que nunca se "
        "devuelve por HTTP. Alta automática sin aprobación previa."
    ),
    responses=respuestas(
        401, 403, 409, 422, ejemplo=ejemplos.ONG_APROVISIONADA, exito=200
    ),
)
def aprovisionar(
    referencia_local: Annotated[
        UUID,
        Path(
            description="UUID durable del backend local, único por emisor.",
            examples=["00000000-0000-4000-8000-000000000201"],
        ),
    ],
    datos: Annotated[
        AprovisionamientoRequest, Body(examples=[ejemplos.APROVISIONAMIENTO])
    ],
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
