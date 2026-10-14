"""Autentica cuentas vigentes y delimita el inventario accesible."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.security import leer_token
from app.db.models import Cuenta, EstadoOng, Ong, RolNacional, SistemaOrigen
from app.db.session import get_db, get_db_evaluacion

Db = Annotated[Session, Depends(get_db)]
DbEvaluacion = Annotated[Session, Depends(get_db_evaluacion)]
_bearer = HTTPBearer(auto_error=False)
Credencial = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


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
        cuenta_id = leer_token(credencial.credentials) if credencial else None
    except (InvalidTokenError, ValueError, TypeError):
        cuenta_id = None
    cuenta = session.get(Cuenta, cuenta_id) if cuenta_id is not None else None
    if cuenta is None or not cuenta.activa:
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
