"""Idempotencia y autorización transaccional compartidas por T32 y T33."""

from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Cuenta,
    OperacionIdempotente,
    RolNacional,
    SistemaOrigen,
    TipoOperacion,
)
from app.db.models.compromisos import RespuestaOperacion
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.emisores import EmisorDenegadoError, EmisorNoEncontradoError


class ErrorOperacion(Exception):
    """Error seguro de contrato, permisos, referencias o estado nacional."""

    status: int = 409


class OperacionNoEncontradaError(ErrorOperacion):
    status = 404


class OperacionDenegadaError(ErrorOperacion):
    status = 403


class OperacionCredencialError(ErrorOperacion):
    status = 401


@contextmanager
def transaccion_operacion(session: Session) -> Iterator[None]:
    """Confirma sólo resultados completos y revierte errores de negocio/base."""
    settings = get_settings()
    try:
        session.execute(
            text("SELECT set_config('lock_timeout', :valor, true)"),
            {"valor": f"{settings.operacion_lock_timeout_ms}ms"},
        )
        session.execute(
            text("SELECT set_config('statement_timeout', :valor, true)"),
            {"valor": f"{settings.operacion_statement_timeout_ms}ms"},
        )
        yield
        session.commit()
    except (
        ErrorOperacion,
        EmisorDenegadoError,
        EmisorNoEncontradoError,
        SQLAlchemyError,
        InventarioInconsistenteError,
    ):
        session.rollback()
        raise


def huella_operacion(
    operacion: TipoOperacion, destino: str, contenido: BaseModel
) -> str:
    """La representación validada excluye orden incidental y decimales equivalentes."""
    serializado = contenido.model_dump_json(by_alias=True)
    return sha256(f"{operacion}:{destino}:{serializado}".encode()).hexdigest()


def reclamar_operacion(
    session: Session,
    *,
    origen_id: UUID,
    cuenta_id: UUID,
    tipo: TipoOperacion,
    clave: str,
    huella: str,
) -> tuple[OperacionIdempotente, bool]:
    """Un conflicto único espera el commit ganador y luego lee su confirmación."""
    nuevo = session.scalar(
        insert(OperacionIdempotente)
        .values(
            id=uuid4(),
            sistema_origen_id=origen_id,
            cuenta_id=cuenta_id,
            operacion=tipo,
            clave=clave,
            huella_sha256=huella,
        )
        .on_conflict_do_nothing(constraint="uq_operacion_clave")
        .returning(OperacionIdempotente.id)
    )
    operacion = session.scalar(
        select(OperacionIdempotente)
        .where(
            OperacionIdempotente.sistema_origen_id == origen_id,
            OperacionIdempotente.operacion == tipo,
            OperacionIdempotente.clave == clave,
        )
        .execution_options(populate_existing=True)
    )
    assert operacion is not None
    if operacion.huella_sha256 != huella:
        raise ErrorOperacion(
            "La clave idempotente ya identifica otro contenido o destino."
        )
    return operacion, nuevo is not None


def bloquear_autor(session: Session, cuenta_id: UUID, origen_id: UUID) -> Cuenta:
    """Recarga permisos bajo locks compartidos, incluso para repetir resultados."""
    cuenta = session.scalar(
        select(Cuenta)
        .where(Cuenta.id == cuenta_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if cuenta is None or not cuenta.activa:
        raise OperacionCredencialError("La cuenta nacional no está activa.")
    if cuenta.rol not in {RolNacional.ADMIN_NACIONAL, RolNacional.INTEGRACION} or (
        cuenta.rol == RolNacional.INTEGRACION and cuenta.sistema_origen_id != origen_id
    ):
        raise OperacionDenegadaError("La cuenta no representa el emisor del proyecto.")
    origen = session.scalar(
        select(SistemaOrigen)
        .where(SistemaOrigen.id == origen_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if origen is None or not origen.activo:
        raise OperacionDenegadaError("El sistema de origen no está activo.")
    return cuenta


def confirmar_operacion(
    operacion: OperacionIdempotente,
    proyecto_id: UUID,
    codigo: int,
    respuesta: RespuestaOperacion,
) -> None:
    """Completa el resultado mínimo junto con el negocio, antes del commit diferido."""
    operacion.proyecto_id = proyecto_id
    operacion.codigo_http = codigo
    operacion.respuesta_minima = respuesta
