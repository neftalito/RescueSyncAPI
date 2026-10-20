"""Autentica cuentas vigentes y delimita el inventario accesible."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.security import leer_token
from app.db.models import (
    Cuenta,
    EstadoOng,
    Ong,
    PropositoCuenta,
    RolNacional,
    SistemaOrigen,
)
from app.db.session import get_db, get_db_evaluacion

Db = Annotated[Session, Depends(get_db)]
DbEvaluacion = Annotated[Session, Depends(get_db_evaluacion)]
_bearer = HTTPBearer(
    auto_error=False,
    bearerFormat="JWT",
    description=(
        "Obtener access_token con POST /api/v1/login (JSON identificadorLogin y "
        "password). Enviar Authorization: Bearer <access_token>. expires_in indica "
        "la duración en segundos; al expirar, autenticar de nuevo. No hay refresh "
        "tokens. Se validan firma HS256, exp, issuer y audience y se recargan "
        "cuenta, ONG y emisor vigentes; los permisos no se toman de roles del JWT. "
        "BONITA_CALLBACK_TOKEN es una credencial local distinta."
    ),
)
Credencial = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=160,
        pattern=r"\S",
        description=(
            "Clave estable por emisor y tipo de operación. Misma clave/contenido "
            "reproduce la confirmación; contenido o destino distintos dan 409. "
            "Tras timeout o 503, reintentar con esta misma clave."
        ),
        examples=["seleccion-101-1"],
    ),
]


def obtener_cuenta(
    session: Db,
    credencial: Credencial,
) -> Cuenta:
    """Carga la identidad vigente; los roles nunca se toman del JWT."""
    return cargar_cuenta(session, credencial)


def obtener_cuenta_evaluacion(session: DbEvaluacion, credencial: Credencial) -> Cuenta:
    """Autentica dentro del mismo snapshot que usará la evaluación transitoria."""
    return cargar_cuenta(session, credencial)


def cargar_cuenta(
    session: Session, credencial: HTTPAuthorizationCredentials | None
) -> Cuenta:
    """Comparte validación de JWT y recarga de cuenta/ONG/emisor actuales."""

    try:
        identidad = leer_token(credencial.credentials) if credencial else None
    except (InvalidTokenError, ValueError, TypeError):
        identidad = None
    cuenta = session.get(Cuenta, identidad.cuenta_id) if identidad is not None else None
    if (
        cuenta is None
        or not cuenta.activa
        or (
            cuenta.proposito == PropositoCuenta.TECNICA_ONG
            and (
                identidad is None
                or identidad.version_credencial != cuenta.version_credencial
            )
        )
    ):
        raise HTTPException(
            401,
            "La credencial nacional no es válida o expiró.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if cuenta.ong_id is not None:
        ong = session.get(Ong, cuenta.ong_id)
        if ong is None or ong.estado in {EstadoOng.SUSPENDIDA, EstadoOng.BAJA}:
            raise HTTPException(403, "La ONG nacional no está activa.")
    if cuenta.sistema_origen_id is not None:
        origen = session.get(SistemaOrigen, cuenta.sistema_origen_id)
        if origen is None or not origen.activo:
            raise HTTPException(403, "El sistema de origen no está activo.")
    return cuenta


CuentaActual = Annotated[Cuenta, Depends(obtener_cuenta)]
CuentaEvaluacion = Annotated[Cuenta, Depends(obtener_cuenta_evaluacion)]


def autorizar_inventario(cuenta: Cuenta, ong_id: UUID, *, escritura: bool) -> None:
    """Impide a una ONG acceder a otra y a la integración editar stock."""

    if cuenta.rol == RolNacional.ONG and cuenta.ong_id == ong_id:
        return
    if cuenta.rol == RolNacional.ADMIN_NACIONAL:
        return
    if not escritura and cuenta.rol == RolNacional.INTEGRACION:
        return
    raise HTTPException(403, "No tenés permisos para acceder a ese inventario.")
