"""Compromiso nacional atómico y consulta autenticada para reconciliar resultados."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Path, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db, IdempotencyKey
from app.api.documentacion import respuestas
from app.schemas.compromisos import (
    CompromisoRequest,
    CompromisoResponse,
    ConfirmacionCompromisos,
)
from app.schemas.proyectos import ConfirmacionLiberacion, FinalizacionRequest
from app.services.compromisos import consultar_compromiso, registrar_compromisos
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.emisores import EmisorDenegadoError, EmisorNoEncontradoError
from app.services.liberaciones import liberar_compromiso
from app.services.operaciones import ErrorOperacion

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/compromisos/{compromiso_id}/liberacion",
    response_model=ConfirmacionLiberacion,
    summary="Liberar una vez el compromiso de una ONG y conservar historial",
    description=(
        "Acceso: INTEGRACION del emisor dueño o ADMIN_NACIONAL; cuentas ONG "
        "reciben 403. caseId debe coincidir con el proyecto. Exige "
        "Idempotency-Key estable. Libera una sola vez el compromiso de esa "
        "ONG y conserva historial; otras ONGs continúan reservadas. ONG "
        "suspendida o acreditación vencida no impiden devolver la reserva. "
        "Misma clave/contenido reproduce la confirmación; cambiar caso o "
        "destino con esa clave produce 409. Otra clave sobre un compromiso "
        "liberado conserva la primera fecha y no duplica stock. Comparte "
        "locks de proyecto y recursos con compromiso/cierre. Tras timeout, "
        "reintentar la misma clave."
    ),
    responses=respuestas(
        401, 403, 404, 409, 422, 503, ejemplo=ejemplos.LIBERACION, exito=200
    ),
)
def liberar(
    compromiso_id: Annotated[
        UUID,
        Path(
            description="UUID nacional obtenido de compromisoIds al comprometer.",
            examples=[ejemplos.COMPROMISO_ID],
        ),
    ],
    datos: Annotated[FinalizacionRequest, Body(examples=[ejemplos.FINALIZACION])],
    clave: IdempotencyKey,
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> ConfirmacionLiberacion:
    response.headers["Cache-Control"] = "no-store"
    try:
        return liberar_compromiso(session, cuenta, compromiso_id, datos, clave)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except SQLAlchemyError as error:
        logger.error("No se confirmó la liberación; reintentar con la misma clave.")
        raise HTTPException(
            503, "Liberación temporalmente no disponible. Reintentá con la misma clave."
        ) from error


@router.post(
    "/compromisos",
    response_model=ConfirmacionCompromisos,
    status_code=201,
    summary="Comprometer atómicamente cantidades adjudicadas por ONG",
    description=(
        "Acceso: INTEGRACION del sistemaOrigen autenticado o ADMIN_NACIONAL "
        "seleccionando emisor activo; cuentas ONG reciben 403. Idempotency-"
        "Key identifica la adjudicación completa por emisor y operación. "
        "Misma clave/contenido reproduce el 201 original; contenido distinto "
        "o adjudicación repetida con otra clave producen 409. Revalida "
        "permisos, competencias y stock bajo locks PostgreSQL ordenados: "
        "proyecto, ONGs, capacidades y recursos. Todos los aportes se "
        "confirman o revierten juntos; sólo guarda asignaciones efectivas y "
        "referencias mínimas. Tras timeout o 503, reintentar con la misma "
        "clave; no generar otra para un resultado incierto."
    ),
    responses=respuestas(
        401, 403, 404, 409, 422, 500, 503, ejemplo=ejemplos.CONFIRMACION, exito=201
    ),
)
def comprometer(
    datos: Annotated[CompromisoRequest, Body(examples=[ejemplos.ADJUDICACION])],
    clave: IdempotencyKey,
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> ConfirmacionCompromisos:
    response.headers["Cache-Control"] = "no-store"
    try:
        return registrar_compromisos(session, cuenta, datos, clave)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except EmisorNoEncontradoError as error:
        raise HTTPException(404, str(error)) from error
    except InventarioInconsistenteError as error:
        logger.error("No se confirmó por inconsistencia del inventario nacional.")
        raise HTTPException(500, "El inventario nacional no es consistente.") from error
    except SQLAlchemyError as error:
        logger.error(
            "No se confirmó el compromiso nacional; reintentar con la misma clave."
        )
        raise HTTPException(
            503, "Operación temporalmente no disponible. Reintentá con la misma clave."
        ) from error


@router.get(
    "/compromisos/{compromiso_id}",
    response_model=CompromisoResponse,
    summary="Consultar el estado vigente y referencias de un compromiso",
    description=(
        "Acceso: INTEGRACION del emisor dueño o ADMIN_NACIONAL; cuentas ONG u"
        " otro emisor reciben 403. Devuelve estado actual e ítems, incluso "
        "después de liberar. Permite reconciliar un timeout cuando ya se "
        "conoce el ID del compromiso."
    ),
    responses=respuestas(
        401, 403, 404, 422, 503, ejemplo=ejemplos.COMPROMISO, exito=200
    ),
)
def consultar(
    compromiso_id: Annotated[
        UUID,
        Path(
            description="UUID nacional obtenido de compromisoIds al comprometer.",
            examples=[ejemplos.COMPROMISO_ID],
        ),
    ],
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> CompromisoResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return consultar_compromiso(session, cuenta, compromiso_id)
    except ErrorOperacion as error:
        raise HTTPException(error.status, str(error)) from error
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.error("No se pudo consultar un compromiso nacional.")
        raise HTTPException(503, "La consulta nacional no está disponible.") from error
