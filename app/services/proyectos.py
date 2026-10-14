"""Cierre terminal serializado con nuevas reservas y liberaciones de participantes."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Compromiso,
    Cuenta,
    EstadoCompromiso,
    EstadoProyecto,
    Proyecto,
    SistemaOrigen,
    TipoOperacion,
)
from app.schemas.proyectos import ConfirmacionCierre, FinalizacionRequest
from app.services.compromisos import bloquear_proyecto
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


def cerrar_proyecto(
    session: Session,
    cuenta: Cuenta,
    proyecto_id: UUID,
    datos: FinalizacionRequest,
    clave: str,
) -> ConfirmacionCierre:
    """Nunca libera reservas al cerrar; exige cero compromisos activos tras el lock."""
    with transaccion_operacion(session):
        proyecto = session.get(Proyecto, proyecto_id)
        if proyecto is None:
            raise OperacionNoEncontradaError("El proyecto nacional no existe.")
        origen = session.get(SistemaOrigen, proyecto.sistema_origen_id)
        assert origen is not None
        autorizar_emisor(session, cuenta, origen.codigo)
        cuenta_id = cuenta.id
        operacion, nueva = reclamar_operacion(
            session,
            origen_id=origen.id,
            cuenta_id=cuenta_id,
            tipo=TipoOperacion.CERRAR_PROYECTO,
            clave=clave,
            huella=huella_operacion(
                TipoOperacion.CERRAR_PROYECTO, str(proyecto_id), datos
            ),
        )
        bloquear_autor(session, cuenta_id, origen.id)
        if not nueva:
            return ConfirmacionCierre.model_validate(operacion.respuesta_minima)
        proyecto = bloquear_proyecto(session, proyecto_id)
        if proyecto.case_ref != datos.case_id:
            raise ErrorOperacion("El caso no coincide con el proyecto nacional.")
        activo = session.scalar(
            select(Compromiso.id)
            .where(
                Compromiso.proyecto_id == proyecto_id,
                Compromiso.estado == EstadoCompromiso.ACTIVO,
            )
            .limit(1)
        )
        if activo is not None:
            raise ErrorOperacion("El proyecto todavía tiene compromisos activos.")
        if proyecto.estado == EstadoProyecto.ABIERTO:
            ahora = datetime.now(UTC)
            proyecto.estado = EstadoProyecto.TERMINADO
            proyecto.cerrado_en = ahora
            proyecto.cerrado_por_id = cuenta_id
            proyecto.actualizado_en = ahora
        assert proyecto.cerrado_en is not None
        resultado = ConfirmacionCierre(
            operacion_id=operacion.id,
            proyecto_id=proyecto_id,
            cerrado_en=proyecto.cerrado_en,
        )
        confirmar_operacion(
            operacion,
            proyecto_id,
            200,
            resultado.model_dump(mode="json", by_alias=True),
        )
        session.flush()
        return resultado
