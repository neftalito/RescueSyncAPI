"""Operaciones nacionales de cuenta, onboarding, catálogo e inventario."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Path, Response

from app.api import ejemplos
from app.api.dependencies import CuentaActual, Db, autorizar_inventario
from app.api.documentacion import respuestas
from app.api.routes.disponibilidad import router as disponibilidad_router
from app.core.config import get_settings
from app.core.security import emitir_token
from app.db.models import PropositoCuenta
from app.schemas.inventario import (
    CapacidadResponse,
    CuentaResponse,
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
    summary="Iniciar sesión nacional",
    description=(
        "Acceso público. Recibe identificadorLogin y password; devuelve "
        "access_token, token_type=bearer y expires_in en segundos. Enviar "
        "Authorization: Bearer <access_token>. Al expirar, autenticar de "
        "nuevo; no hay refresh tokens. Cuentas técnicas ONG: 300 segundos; "
        "otras cuentas: JWT_ACCESS_SECONDS (1800 por defecto)."
    ),
    responses=respuestas(
        401,
        422,
        ejemplo=ejemplos.TOKEN,
        exito=200,
        detalles={401: "El identificador o la contraseña son incorrectos."},
    ),
)
def login(
    datos: Annotated[LoginRequest, Body(examples=[ejemplos.LOGIN])],
    session: Db,
    response: Response,
) -> TokenResponse:
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
        access_token=emitir_token(
            cuenta.id,
            version_credencial=cuenta.version_credencial
            if cuenta.proposito == PropositoCuenta.TECNICA_ONG
            else None,
        ),
        expires_in=300
        if cuenta.proposito == PropositoCuenta.TECNICA_ONG
        else get_settings().jwt_access_seconds,
    )


@router.get(
    "/me",
    response_model=CuentaResponse,
    summary="Consultar la cuenta nacional vigente",
    description=(
        "Acceso: ONG, ADMIN_NACIONAL o INTEGRACION con cuenta vigente. "
        "Devuelve rol, ONG y propósito actuales, recargados desde la base "
        "nacional."
    ),
    responses=respuestas(401, 403, ejemplo=ejemplos.CUENTA, exito=200),
)
def me(cuenta: CuentaActual, response: Response) -> CuentaResponse:
    response.headers["Cache-Control"] = "no-store"
    return CuentaResponse(
        id=cuenta.id, rol=cuenta.rol, ong_id=cuenta.ong_id, proposito=cuenta.proposito
    )


@router.post(
    "/ongs",
    response_model=OngResponse,
    status_code=201,
    summary="Registrar una ONG y su cuenta",
    description=(
        "Acceso público. Crea atómicamente cuenta y ONG PENDIENTE, sin "
        "habilitación ni certificaciones. Login o identificador institucional"
        " duplicados producen 409."
    ),
    responses=respuestas(409, 422, ejemplo=ejemplos.ONG, exito=201),
)
def onboarding(
    datos: Annotated[OngCreate, Body(examples=[ejemplos.ALTA_ONG])], session: Db
) -> OngResponse:
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
    summary="Consultar capacidades y unidades activas",
    description=(
        "Acceso: ONG, ADMIN_NACIONAL o INTEGRACION con cuenta vigente. Lista "
        "capacidades activas, tipo, unidad y admisión de fracciones; no "
        "asigna competencias."
    ),
    responses=respuestas(401, 403, ejemplo=[ejemplos.CAPACIDAD], exito=200),
)
def capacidades(session: Db, _: CuentaActual) -> list[CapacidadResponse]:
    return listar_capacidades(session)


@router.get(
    "/ongs/{ong_id}/recursos",
    response_model=list[RecursoResponse],
    summary="Consultar inventario y disponibilidad de una ONG",
    description=(
        "Acceso: ONG propietaria, ADMIN_NACIONAL o INTEGRACION. Otra ONG "
        "recibe 403. Devuelve total, comprometido y disponible en un mismo "
        "snapshot; consultar no reserva stock."
    ),
    responses=respuestas(401, 403, 404, 422, ejemplo=[ejemplos.RECURSO], exito=200),
)
def recursos(
    ong_id: Annotated[
        UUID,
        Path(
            description="UUID de la ONG en el sistema nacional; no es el ID local.",
            examples=[ejemplos.ONG_ID],
        ),
    ],
    session: Db,
    cuenta: CuentaActual,
) -> list[RecursoResponse]:
    autorizar_inventario(cuenta, ong_id, escritura=False)
    return _ejecutar(session, lambda: listar_recursos(session, ong_id))


@router.post(
    "/ongs/{ong_id}/recursos",
    response_model=RecursoResponse,
    status_code=201,
    summary="Registrar un recurso propio",
    description=(
        "Acceso: ONG propietaria o ADMIN_NACIONAL; INTEGRACION no puede "
        "escribir inventario. Capacidad y propietario son inmutables; "
        "codigoInterno es único por ONG. Cantidades positivas y compatibles "
        "con la unidad."
    ),
    responses=respuestas(401, 403, 404, 409, 422, ejemplo=ejemplos.RECURSO, exito=201),
)
def crear(
    ong_id: Annotated[
        UUID,
        Path(
            description="UUID de la ONG en el sistema nacional; no es el ID local.",
            examples=[ejemplos.ONG_ID],
        ),
    ],
    datos: Annotated[RecursoCreate, Body(examples=[ejemplos.ALTA_RECURSO])],
    session: Db,
    cuenta: CuentaActual,
) -> RecursoResponse:
    autorizar_inventario(cuenta, ong_id, escritura=True)
    return _ejecutar(session, lambda: crear_recurso(session, ong_id, datos))


@router.patch(
    "/ongs/{ong_id}/recursos/{recurso_id}",
    response_model=RecursoResponse,
    summary="Actualizar el total de un recurso",
    description=(
        "Acceso: ONG propietaria o ADMIN_NACIONAL. Bloquea la fila y "
        "recalcula compromisos activos. Enviar actualizadoEn de la última "
        "lectura; versión obsoleta o total inferior a lo comprometido "
        "producen 409. No cambia propietario ni capacidad."
    ),
    responses=respuestas(
        401, 403, 404, 409, 422, ejemplo=ejemplos.RECURSO_EDITADO, exito=200
    ),
)
def actualizar(
    ong_id: Annotated[
        UUID,
        Path(
            description="UUID de la ONG en el sistema nacional; no es el ID local.",
            examples=[ejemplos.ONG_ID],
        ),
    ],
    recurso_id: Annotated[
        UUID,
        Path(
            description="UUID nacional del recurso perteneciente a la ONG de la ruta.",
            examples=[ejemplos.RECURSO_ID],
        ),
    ],
    datos: Annotated[RecursoUpdate, Body(examples=[ejemplos.EDICION_RECURSO])],
    session: Db,
    cuenta: CuentaActual,
) -> RecursoResponse:
    autorizar_inventario(cuenta, ong_id, escritura=True)
    return _ejecutar(
        session, lambda: actualizar_recurso(session, ong_id, recurso_id, datos)
    )
