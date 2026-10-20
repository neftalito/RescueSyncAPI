"""Analiza inventario activo sin certificar a las ONG ni autorizar operaciones."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Capacidad, EstadoOng, Ong, Recurso
from app.schemas.perfiles import CapacidadDeclarada, PerfilCompetencia
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.inventario import compromisos_activos_por_recurso


def consultar_perfiles(
    session: Session,
    *,
    ong_ids: set[UUID] | None = None,
    solo_activas: bool = False,
    ahora: datetime | None = None,
) -> dict[UUID, PerfilCompetencia]:
    """Incluye ONG sin inventario; agrupa sin multiplicar compromisos en joins."""
    evaluado_en = ahora or datetime.now(UTC)
    consulta = select(Ong).order_by(Ong.nombre, Ong.id)
    if ong_ids is not None:
        consulta = consulta.where(Ong.id.in_(ong_ids))
    if solo_activas:
        consulta = consulta.where(Ong.estado == EstadoOng.HABILITADA)
    perfiles = {
        ong.id: PerfilCompetencia(
            ong_id=ong.id,
            nombre=ong.nombre,
            estado_ong=ong.estado,
            evaluado_en=evaluado_en,
            capacidades_declaradas=[],
        )
        for ong in session.scalars(consulta.execution_options(populate_existing=True))
    }
    if not perfiles:
        return perfiles
    compromisos = compromisos_activos_por_recurso()
    comprometida = func.coalesce(compromisos.c.cantidad, 0)
    filas = session.execute(
        select(
            Recurso.ong_id,
            Capacidad,
            func.sum(Recurso.cantidad_total),
            func.sum(comprometida),
            func.bool_or(Recurso.cantidad_total < comprometida),
        )
        .join(Capacidad, Capacidad.id == Recurso.capacidad_id)
        .outerjoin(compromisos, compromisos.c.recurso_id == Recurso.id)
        .where(Recurso.ong_id.in_(perfiles), Recurso.activo, Capacidad.activa)
        .group_by(Recurso.ong_id, Capacidad.id)
        .order_by(Recurso.ong_id, Capacidad.codigo, Capacidad.id)
    ).all()
    precision = (
        max((len(total.as_tuple().digits) for _, _, total, _, _ in filas), default=1)
        + 3
    )
    with localcontext() as contexto:
        contexto.prec = max(28, precision)
        for ong_id, capacidad, total, comprometido, inconsistente in filas:
            if inconsistente:
                raise InventarioInconsistenteError("El inventario no es consistente.")
            perfiles[ong_id].capacidades_declaradas.append(
                CapacidadDeclarada(
                    capacidad_id=capacidad.id,
                    codigo=capacidad.codigo,
                    nombre=capacidad.nombre,
                    tipo=capacidad.tipo,
                    unidad=capacidad.unidad,
                    admite_fracciones=capacidad.admite_fracciones,
                    cantidad_total=total,
                    cantidad_comprometida=comprometido or Decimal(0),
                    cantidad_disponible=total - comprometido,
                )
            )
    return perfiles
