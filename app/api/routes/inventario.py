"""Operaciones nacionales de cuenta, onboarding, catálogo e inventario."""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.api.dependencies import CuentaActual, Db, autorizar_inventario
from app.api.routes.disponibilidad import router as disponibilidad_router
from app.core.config import get_settings
from app.core.security import emitir_token
from app.schemas.inventario import (
    CapacidadResponse,
    CuentaResponse,
    ErrorResponse,
    LoginRequest,
    OngCreate,
    OngResponse,
    RecursoCreate,
    RecursoResponse,
    RecursoUpdate,
    TokenResponse,
)
from app.services.cuentas import CuentaDuplicadaError, autenticar, registrar_ong
from app.services.inventario import (
    CantidadInvalidaError,
    InventarioConflictivoError,
    ReferenciaNoEncontradaError,
    actualizar_recurso,
    crear_recurso,
    listar_capacidades,
    listar_recursos,
)

router = APIRouter()
router.include_router(disponibilidad_router, tags=["disponibilidad global"])
errores = {codigo: {"model": ErrorResponse} for codigo in (401, 403, 404, 409, 422)}


def _ejecutar[T](session: Db, operacion: Callable[[], T]) -> T:
    try:
        return operacion()
    except ReferenciaNoEncontradaError as error:
        session.rollback()
        raise HTTPException(404, str(error)) from error
    except InventarioConflictivoError as error:
        session.rollback()
        raise HTTPException(409, str(error)) from error
    except CantidadInvalidaError as error:
        session.rollback()
        raise HTTPException(422, str(error)) from error


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=errores,
    summary="Iniciar sesión nacional",
)
def login(datos: LoginRequest, session: Db, response: Response) -> TokenResponse:
    cuenta = autenticar(
        session, datos.identificador_login, datos.password.get_secret_value()
    )
    if cuenta is None:
        raise HTTPException(
            401,
            "El identificador o la contraseña son incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=emitir_token(cuenta.id),
        expires_in=get_settings().jwt_access_seconds,
    )


@router.get(
    "/me",
    response_model=CuentaResponse,
    responses=errores,
    summary="Consultar la cuenta nacional vigente",
)
def me(cuenta: CuentaActual, response: Response) -> CuentaResponse:
    response.headers["Cache-Control"] = "no-store"
    return CuentaResponse(id=cuenta.id, rol=cuenta.rol, ong_id=cuenta.ong_id)


@router.post(
    "/ongs",
    response_model=OngResponse,
    status_code=201,
    responses=errores,
    summary="Registrar una ONG y su cuenta",
    description=(
        "Alta atómica en estado PENDIENTE, "
        "sin otorgar habilitaciones ni certificaciones."
    ),
)
def onboarding(datos: OngCreate, session: Db) -> OngResponse:
    try:
        ong = registrar_ong(session, datos)
    except CuentaDuplicadaError as error:
        raise HTTPException(
            409, "El login o identificador institucional ya está registrado."
        ) from error
    return OngResponse(id=ong.id, nombre=ong.nombre, estado=ong.estado)


@router.get(
    "/capacidades",
    response_model=list[CapacidadResponse],
    responses=errores,
    summary="Consultar capacidades y unidades activas",
)
def capacidades(session: Db, _: CuentaActual) -> list[CapacidadResponse]:
    return listar_capacidades(session)


@router.get(
    "/ongs/{ong_id}/recursos",
    response_model=list[RecursoResponse],
    responses=errores,
    summary="Consultar inventario y disponibilidad de una ONG",
)
def recursos(ong_id: UUID, session: Db, cuenta: CuentaActual) -> list[RecursoResponse]:
    autorizar_inventario(cuenta, ong_id, escritura=False)
    return _ejecutar(session, lambda: listar_recursos(session, ong_id))


@router.post(
    "/ongs/{ong_id}/recursos",
    response_model=RecursoResponse,
    status_code=201,
    responses=errores,
    summary="Registrar un recurso propio",
)
def crear(
    ong_id: UUID, datos: RecursoCreate, session: Db, cuenta: CuentaActual
) -> RecursoResponse:
    autorizar_inventario(cuenta, ong_id, escritura=True)
    return _ejecutar(session, lambda: crear_recurso(session, ong_id, datos))


@router.patch(
    "/ongs/{ong_id}/recursos/{recurso_id}",
    response_model=RecursoResponse,
    responses=errores,
    summary="Actualizar el total de un recurso",
    description=(
        "Bloquea la fila y recalcula compromisos. "
        "Rechaza stock insuficiente o una versión desactualizada."
    ),
)
def actualizar(
    ong_id: UUID,
    recurso_id: UUID,
    datos: RecursoUpdate,
    session: Db,
    cuenta: CuentaActual,
) -> RecursoResponse:
    autorizar_inventario(cuenta, ong_id, escritura=True)
    return _ejecutar(
        session, lambda: actualizar_recurso(session, ong_id, recurso_id, datos)
    )
