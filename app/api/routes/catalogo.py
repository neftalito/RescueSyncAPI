"""Consulta unidades predefinidas y permite al administrador ampliar capacidades."""

from fastapi import APIRouter, HTTPException, Response

from app.api.dependencies import CuentaActual, Db
from app.db.models import RolNacional
from app.schemas.catalogo import CapacidadCreate, UnidadResponse
from app.schemas.inventario import CapacidadResponse, ErrorResponse
from app.services.catalogo import (
    CapacidadDuplicadaError,
    UnidadNoDisponibleError,
    crear_capacidad,
    listar_unidades,
)

router = APIRouter()


@router.get(
    "/unidades",
    response_model=list[UnidadResponse],
    summary="Consultar unidades predefinidas",
    description=(
        "Catálogo de solo lectura cargado por migraciones en todos los entornos."
    ),
    responses={codigo: {"model": ErrorResponse} for codigo in (401, 403)},
)
def unidades(session: Db, _: CuentaActual, response: Response) -> list[UnidadResponse]:
    response.headers["Cache-Control"] = "no-store"
    return listar_unidades(session)


@router.post(
    "/capacidades",
    response_model=CapacidadResponse,
    status_code=201,
    summary="Crear una capacidad nacional",
    description=(
        "Requiere una cuenta ADMIN_NACIONAL activa y una unidad predefinida. "
        "No crea unidades, certificaciones, acreditaciones ni inventario."
    ),
    responses={codigo: {"model": ErrorResponse} for codigo in (401, 403, 409, 422)},
)
def alta_capacidad(
    datos: CapacidadCreate,
    session: Db,
    cuenta: CuentaActual,
    response: Response,
) -> CapacidadResponse:
    if cuenta.rol != RolNacional.ADMIN_NACIONAL:
        raise HTTPException(
            403, "Sólo la administración nacional puede crear capacidades."
        )
    response.headers["Cache-Control"] = "no-store"
    try:
        return crear_capacidad(session, datos)
    except CapacidadDuplicadaError as error:
        raise HTTPException(409, str(error)) from error
    except UnidadNoDisponibleError as error:
        raise HTTPException(422, str(error)) from error
