"""Validación nacional transitoria del snapshot cerrado que Bonita obtiene de T34."""

import logging
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from app.api import ejemplos
from app.api.dependencies import CuentaEvaluacion, DbEvaluacion
from app.api.documentacion import respuestas
from app.schemas.validaciones import ValidacionRequest, ValidacionResponse
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.emisores import (
    EmisorDenegadoError,
    EmisorNoEncontradoError,
    autorizar_emisor,
)
from app.services.validaciones import validar_snapshot

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/validaciones",
    response_model=ValidacionResponse,
    summary="Evaluar competencias y disponibilidad por aporte sin reservar",
    description=(
        "Acceso: INTEGRACION del sistemaOrigen autenticado o ADMIN_NACIONAL "
        "seleccionando un emisor activo; cuentas ONG reciben 403. Bonita "
        "envía el snapshot contratoVersion=2 tras el cierre local. Evaluación"
        " transitoria READ ONLY / REPEATABLE READ: devuelve capacidades, "
        "riesgos, clasificación PRINCIPAL/APOYO/SIN_HABILITACION y motivos "
        "por aporte. No guarda ofertas ni resultados y no crea proyectos o "
        "reservas. La disponibilidad consultada no garantiza stock al "
        "adjudicar."
    ),
    responses=respuestas(
        401, 403, 404, 422, 500, 503, ejemplo=ejemplos.VALIDACION, exito=200
    ),
)
def validar(
    snapshot: Annotated[ValidacionRequest, Body(examples=[ejemplos.SNAPSHOT_CERRADO])],
    session: DbEvaluacion,
    cuenta: CuentaEvaluacion,
    response: Response,
) -> ValidacionResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        autorizar_emisor(session, cuenta, snapshot.sistema_origen)
        return validar_snapshot(session, snapshot)
    except EmisorDenegadoError as error:
        raise HTTPException(403, str(error)) from error
    except EmisorNoEncontradoError as error:
        raise HTTPException(404, str(error)) from error
    except InventarioInconsistenteError as error:
        logger.error("No se pudo evaluar por inconsistencia del inventario nacional.")
        raise HTTPException(500, "El inventario nacional no es consistente.") from error
    except SQLAlchemyError as error:
        session.rollback()
        logger.error("No se pudo consultar la base nacional para evaluar.")
        raise HTTPException(
            503, "La evaluación nacional no está disponible."
        ) from error
