"""Libera sólo una participante; conserva ítems, autor y primera fecha."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Compromiso,
    CompromisoItem,
    Cuenta,
    EstadoCompromiso,
    Proyecto,
    SistemaOrigen,
    TipoOperacion,
)
from app.schemas.proyectos import ConfirmacionLiberacion, FinalizacionRequest
from app.services.compromisos import bloquear_proyecto, bloquear_recursos
from app.services.emisores import autorizar_emisor
from app.services.operaciones import (
    ErrorOperacion,
    OperacionNoEncontradaError,
    bloquear_autor,
    confirmar_operacion,
    huella_operacion,
    reclamar_operacion,
    transaccion_operacion,
)


def liberar_compromiso(
    session: Session,
    cuenta: Cuenta,
    compromiso_id: UUID,
    datos: FinalizacionRequest,
    clave: str,
) -> ConfirmacionLiberacion:
    """Suspensión o falta de competencia no bloquean devolver una reserva existente."""
    with transaccion_operacion(session):
        fila = session.execute(
            select(Compromiso, Proyecto, SistemaOrigen)
            .join(Proyecto, Proyecto.id == Compromiso.proyecto_id)
            .join(SistemaOrigen, SistemaOrigen.id == Proyecto.sistema_origen_id)
            .where(Compromiso.id == compromiso_id)
        ).one_or_none()
        if fila is None:
            raise OperacionNoEncontradaError("El compromiso nacional no existe.")
        compromiso, proyecto, origen = fila
        autorizar_emisor(session, cuenta, origen.codigo)
        cuenta_id = cuenta.id
        operacion, nueva = reclamar_operacion(
            session,
            origen_id=origen.id,
            cuenta_id=cuenta_id,
            tipo=TipoOperacion.LIBERAR,
            clave=clave,
            huella=huella_operacion(TipoOperacion.LIBERAR, str(compromiso_id), datos),
        )
        bloquear_autor(session, cuenta_id, origen.id)
        if not nueva:
            return ConfirmacionLiberacion.model_validate(operacion.respuesta_minima)
        proyecto = bloquear_proyecto(session, proyecto.id)
        if proyecto.case_ref != datos.case_id:
            raise ErrorOperacion("El caso no coincide con el proyecto nacional.")
        recursos = set(
            session.scalars(
                select(CompromisoItem.recurso_id).where(
                    CompromisoItem.compromiso_id == compromiso_id
                )
            )
        )
        bloquear_recursos(session, recursos)
        compromiso = session.scalar(
            select(Compromiso)
            .where(Compromiso.id == compromiso_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert compromiso is not None
        if compromiso.estado == EstadoCompromiso.ACTIVO:
            ahora = datetime.now(UTC)
            compromiso.estado = EstadoCompromiso.LIBERADO
            compromiso.liberado_en = ahora
            compromiso.liberado_por_id = cuenta_id
            compromiso.actualizado_en = ahora
        assert compromiso.liberado_en is not None
        resultado = ConfirmacionLiberacion(
            operacion_id=operacion.id,
            proyecto_id=proyecto.id,
            compromiso_id=compromiso_id,
            ong_nacional_id=compromiso.ong_id,
            liberado_en=compromiso.liberado_en,
        )
        confirmar_operacion(
            operacion,
            proyecto.id,
            200,
            resultado.model_dump(mode="json", by_alias=True),
        )
        session.flush()
        return resultado
