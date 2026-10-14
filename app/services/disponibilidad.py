"""Consolidación nacional informativa en un snapshot, sin locks ni escrituras."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Capacidad, EstadoOng, Ong, Recurso
from app.schemas.disponibilidad import (
    DisponibilidadCapacidadResponse,
    DisponibilidadOngResponse,
    DisponibilidadResponse,
)
from app.services.inventario import compromisos_activos_por_recurso


class InventarioInconsistenteError(ValueError):
    """Impide que stock negativo de una fila se oculte en un agregado positivo."""


def consultar_disponibilidad(
    session: Session,
    *,
    capacidad_id: UUID | None = None,
    ong_id: UUID | None = None,
    ahora: datetime | None = None,
) -> DisponibilidadResponse:
    """Separa capacidades/unidades y suma exclusivamente compromisos activos."""
    consultado_en = ahora or datetime.now(UTC)
    compromisos = compromisos_activos_por_recurso()
    comprometida = func.coalesce(compromisos.c.cantidad, 0)
    consulta = (
        select(
            Capacidad,
            Ong,
            func.sum(Recurso.cantidad_total),
            func.sum(comprometida),
            func.bool_or(Recurso.cantidad_total < comprometida),
        )
        .select_from(Recurso)
        .join(Capacidad, Capacidad.id == Recurso.capacidad_id)
        .join(Ong, Ong.id == Recurso.ong_id)
        .outerjoin(compromisos, compromisos.c.recurso_id == Recurso.id)
        .where(Recurso.activo, Capacidad.activa, Ong.estado == EstadoOng.HABILITADA)
        .group_by(Capacidad.id, Ong.id)
        .order_by(Capacidad.codigo, Capacidad.id, Ong.nombre, Ong.id)
        .execution_options(populate_existing=True)
    )
    if capacidad_id is not None:
        consulta = consulta.where(Capacidad.id == capacidad_id)
    if ong_id is not None:
        consulta = consulta.where(Ong.id == ong_id)
    filas = session.execute(consulta).all()
    grupos: dict[UUID, DisponibilidadCapacidadResponse] = {}
    # Las sumas SQL pueden superar la precisión permitida a un recurso individual.
    precision = (
        max((len(total.as_tuple().digits) for _, _, total, _, _ in filas), default=1)
        + len(str(len(filas)))
        + 3
    )
    with localcontext() as contexto:
        contexto.prec = max(28, precision)
        for capacidad, ong, total, comprometido, inconsistente in filas:
            if inconsistente:
                raise InventarioInconsistenteError("El inventario no es consistente.")
            disponible = total - comprometido
            grupo = grupos.setdefault(
                capacidad.id,
                DisponibilidadCapacidadResponse(
                    capacidad_id=capacidad.id,
                    codigo=capacidad.codigo,
                    nombre=capacidad.nombre,
                    tipo=capacidad.tipo,
                    unidad=capacidad.unidad,
                    admite_fracciones=capacidad.admite_fracciones,
                    cantidad_total=Decimal(0),
                    cantidad_comprometida=Decimal(0),
                    cantidad_disponible=Decimal(0),
                    ongs=[],
                ),
            )
            grupo.cantidad_total += total
            grupo.cantidad_comprometida += comprometido
            grupo.cantidad_disponible += disponible
            grupo.ongs.append(
                DisponibilidadOngResponse(
                    ong_id=ong.id,
                    nombre=ong.nombre,
                    estado_ong=ong.estado,
                    cantidad_total=total,
                    cantidad_comprometida=comprometido,
                    cantidad_disponible=disponible,
                )
            )
    return DisponibilidadResponse(
        consultado_en=consultado_en, recursos=list(grupos.values())
    )
