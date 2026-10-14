"""Inventario nacional; las ediciones serializan el cálculo de compromisos."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.db.models import (
    Capacidad,
    Compromiso,
    CompromisoItem,
    EstadoCompromiso,
    Ong,
    Recurso,
)
from app.schemas.inventario import (
    CapacidadResponse,
    RecursoCreate,
    RecursoResponse,
    RecursoUpdate,
)


class ReferenciaNoEncontradaError(LookupError):
    """La ONG, capacidad o recurso solicitado no existe."""


class InventarioConflictivoError(ValueError):
    """Hay stock comprometido, un código repetido o una edición obsoleta."""


class CantidadInvalidaError(ValueError):
    """La cantidad no respeta la unidad del catálogo."""


def listar_capacidades(session: Session) -> list[CapacidadResponse]:
    return [
        CapacidadResponse(
            id=c.id,
            codigo=c.codigo,
            nombre=c.nombre,
            tipo=c.tipo,
            unidad=c.unidad,
            admite_fracciones=c.admite_fracciones,
        )
        for c in session.scalars(
            select(Capacidad).where(Capacidad.activa).order_by(Capacidad.nombre)
        )
    ]


def cantidad_comprometida(session: Session, recurso_id: UUID) -> Decimal:
    """Suma sólo compromisos activos; no almacena otro contador de stock."""

    return session.scalar(
        select(func.coalesce(func.sum(CompromisoItem.cantidad), 0))
        .join(Compromiso, Compromiso.id == CompromisoItem.compromiso_id)
        .where(
            CompromisoItem.recurso_id == recurso_id,
            Compromiso.estado == EstadoCompromiso.ACTIVO,
        )
    ) or Decimal(0)


def _respuesta(
    recurso: Recurso, capacidad: Capacidad, comprometida: Decimal
) -> RecursoResponse:
    return RecursoResponse(
        id=recurso.id,
        ong_id=recurso.ong_id,
        capacidad_id=recurso.capacidad_id,
        codigo_interno=recurso.codigo_interno,
        nombre=recurso.nombre,
        capacidad=capacidad.nombre,
        unidad=capacidad.unidad,
        admite_fracciones=capacidad.admite_fracciones,
        cantidad_total=recurso.cantidad_total.quantize(Decimal("0.001")),
        cantidad_comprometida=comprometida.quantize(Decimal("0.001")),
        cantidad_disponible=(recurso.cantidad_total - comprometida).quantize(
            Decimal("0.001")
        ),
        activo=recurso.activo,
        actualizado_en=recurso.actualizado_en,
    )


def _exigir_ong(session: Session, ong_id: UUID) -> None:
    if session.get(Ong, ong_id) is None:
        raise ReferenciaNoEncontradaError("La ONG no existe.")


def listar_recursos(session: Session, ong_id: UUID) -> list[RecursoResponse]:
    """Lee totales y compromisos en un único snapshot de PostgreSQL."""
    _exigir_ong(session, ong_id)
    compromisos = compromisos_activos_por_recurso()
    filas = session.execute(
        select(Recurso, Capacidad, func.coalesce(compromisos.c.cantidad, 0))
        .join(Capacidad, Capacidad.id == Recurso.capacidad_id)
        .outerjoin(compromisos, compromisos.c.recurso_id == Recurso.id)
        .where(Recurso.ong_id == ong_id)
        .order_by(Recurso.nombre, Recurso.id)
    )
    return [
        _respuesta(recurso, capacidad, comprometida)
        for recurso, capacidad, comprometida in filas
    ]


def compromisos_activos_por_recurso() -> Subquery:
    """Preagrega una fila por recurso para evitar multiplicar el stock en joins."""
    return (
        select(
            CompromisoItem.recurso_id,
            func.sum(CompromisoItem.cantidad).label("cantidad"),
        )
        .join(Compromiso, Compromiso.id == CompromisoItem.compromiso_id)
        .where(Compromiso.estado == EstadoCompromiso.ACTIVO)
        .group_by(CompromisoItem.recurso_id)
        .subquery()
    )


def _validar_cantidad(capacidad: Capacidad, cantidad: Decimal) -> None:
    if not capacidad.admite_fracciones and cantidad != cantidad.to_integral_value():
        raise CantidadInvalidaError("Esta capacidad requiere cantidades enteras.")


def crear_recurso(
    session: Session, ong_id: UUID, datos: RecursoCreate
) -> RecursoResponse:
    """Registra una fila de inventario con capacidad y propietario inmutables."""

    _exigir_ong(session, ong_id)
    capacidad = session.scalar(
        select(Capacidad)
        .where(Capacidad.id == datos.capacidad_id, Capacidad.activa)
        .with_for_update(read=True)
    )
    if capacidad is None:
        raise ReferenciaNoEncontradaError("La capacidad no existe o está inactiva.")
    _validar_cantidad(capacidad, datos.cantidad_total)
    recurso = Recurso(
        ong_id=ong_id,
        capacidad_id=datos.capacidad_id,
        codigo_interno=datos.codigo_interno,
        nombre=datos.nombre,
        cantidad_total=datos.cantidad_total,
    )
    try:
        session.add(recurso)
        session.flush()
        respuesta = _respuesta(recurso, capacidad, Decimal(0))
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise InventarioConflictivoError(
            "El código interno ya existe para esta ONG."
        ) from error
    return respuesta


def actualizar_recurso(
    session: Session, ong_id: UUID, recurso_id: UUID, datos: RecursoUpdate
) -> RecursoResponse:
    """Bloquea la fila y luego recalcula stock; rechaza cambios desactualizados."""

    recurso = session.scalar(
        select(Recurso)
        .where(Recurso.id == recurso_id, Recurso.ong_id == ong_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if recurso is None:
        raise ReferenciaNoEncontradaError("El recurso no existe en esta ONG.")
    if recurso.actualizado_en != datos.actualizado_en:
        raise InventarioConflictivoError(
            "El recurso cambió. Actualizá el listado antes de editarlo."
        )
    capacidad = session.get(Capacidad, recurso.capacidad_id)
    assert capacidad is not None
    _validar_cantidad(capacidad, datos.cantidad_total)
    comprometida = cantidad_comprometida(session, recurso_id)
    if datos.cantidad_total < comprometida:
        raise InventarioConflictivoError(
            "El total no puede ser menor que la cantidad comprometida."
        )
    recurso.cantidad_total = datos.cantidad_total
    recurso.actualizado_en = datetime.now(UTC)
    session.flush()
    respuesta = _respuesta(recurso, capacidad, comprometida)
    session.commit()
    return respuesta
