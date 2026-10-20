"""Consulta unidades predefinidas y permite al administrador ampliar capacidades."""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Response

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db
from app.api.documentacion import respuestas
from app.db.models import RolNacional
from app.schemas.catalogo import CapacidadCreate, UnidadResponse
from app.schemas.inventario import CapacidadResponse
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
        "Acceso: ONG, ADMIN_NACIONAL o INTEGRACION con cuenta vigente. "
        "Catálogo de solo lectura instalado por migraciones en todos los "
        "entornos."
    ),
    responses=respuestas(401, 403, ejemplo=ejemplos.UNIDADES, exito=200),
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
        "Acceso exclusivo: ADMIN_NACIONAL con cuenta activa. Exige unidad "
        "predefinida; código duplicado produce 409 y unidad inexistente o "
        "fracciones incompatibles, 422. No crea unidades, acreditaciones ni "
        "inventario."
    ),
    responses=respuestas(401, 403, 409, 422, ejemplo=ejemplos.CAPACIDAD, exito=201),
)
def alta_capacidad(
    datos: Annotated[CapacidadCreate, Body(examples=[ejemplos.ALTA_CAPACIDAD])],
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
