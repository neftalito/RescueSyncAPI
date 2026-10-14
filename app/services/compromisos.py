"""Reservas efectivas atómicas, stock recalculado tras locks y consulta por emisor."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    Capacidad,
    Certificacion,
    Compromiso,
    CompromisoItem,
    Cuenta,
    EstadoProyecto,
    Ong,
    OngCertificacion,
    Proyecto,
    Recurso,
    SistemaOrigen,
    TipoOperacion,
)
from app.schemas.compromisos import (
    CompromisoRequest,
    CompromisoResponse,
    ConfirmacionCompromisos,
    ItemCompromisoResponse,
)
from app.schemas.validaciones import Clasificacion
from app.services.certificaciones import consultar_certificaciones_ongs
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
from app.services.validaciones import (
    RequerimientoAporte,
    consultar_recursos,
    evaluar_aporte,
)


def bloquear_proyecto(session: Session, proyecto_id: UUID) -> Proyecto:
    """Compromiso y cierre comparten este lock antes de tocar recursos."""
    proyecto = session.scalar(
        select(Proyecto)
        .where(Proyecto.id == proyecto_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if proyecto is None:
        raise OperacionNoEncontradaError("El proyecto nacional no existe.")
    return proyecto


def _proyecto_adjudicacion(
    session: Session, origen_id: UUID, datos: CompromisoRequest
) -> Proyecto:
    session.execute(
        insert(Proyecto)
        .values(
            id=uuid4(),
            sistema_origen_id=origen_id,
            emergencia_ref=datos.id_emergencia,
            case_ref=datos.case_id,
        )
        .on_conflict_do_nothing(constraint="uq_proyecto_emergencia")
    )
    proyecto_id = session.scalar(
        select(Proyecto.id).where(
            Proyecto.sistema_origen_id == origen_id,
            Proyecto.emergencia_ref == datos.id_emergencia,
        )
    )
    assert proyecto_id is not None
    proyecto = bloquear_proyecto(session, proyecto_id)
    if proyecto.case_ref != datos.case_id:
        raise ErrorOperacion("La emergencia ya está correlacionada con otro caso.")
    if proyecto.estado != EstadoProyecto.ABIERTO:
        raise ErrorOperacion("El proyecto nacional está terminado.")
    anterior = session.scalar(
        select(Compromiso.id)
        .where(
            Compromiso.proyecto_id == proyecto.id,
            Compromiso.adjudicacion_ref == datos.adjudicacion_id,
        )
        .limit(1)
    )
    if anterior is not None:
        raise ErrorOperacion(
            "La adjudicación ya fue confirmada; reutilizá su clave original."
        )
    return proyecto


def bloquear_recursos(session: Session, ids: set[UUID]) -> list[Recurso]:
    """Orden único compartido por reservas y liberaciones de varios recursos."""
    return list(
        session.scalars(
            select(Recurso)
            .where(Recurso.id.in_(ids))
            .order_by(Recurso.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def _bloquear_competencias(session: Session, datos: CompromisoRequest) -> None:
    ongs = {a.ong_nacional_id for a in datos.aportes}
    instituciones = session.scalars(
        select(Ong)
        .where(Ong.id.in_(ongs))
        .order_by(Ong.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()
    if len(instituciones) != len(ongs):
        raise OperacionNoEncontradaError("Una ONG nacional no existe.")
    capacidad_ids = {a.capacidad_nacional_id for a in datos.aportes}
    capacidades = session.scalars(
        select(Capacidad)
        .where(Capacidad.id.in_(capacidad_ids))
        .order_by(Capacidad.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()
    if len(capacidades) != len(capacidad_ids):
        raise OperacionNoEncontradaError("Una capacidad nacional no existe.")
    revision_ids = select(OngCertificacion.certificacion_id).where(
        OngCertificacion.ong_id.in_(ongs)
    )
    session.scalars(
        select(Certificacion)
        .where(Certificacion.id.in_(revision_ids))
        .order_by(Certificacion.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()


def registrar_compromisos(
    session: Session, cuenta: Cuenta, datos: CompromisoRequest, clave: str
) -> ConfirmacionCompromisos:
    """Revalida y confirma una selección completa; no persiste la oferta original."""
    normalizado = datos.model_copy(
        update={
            "aportes": sorted(
                datos.aportes,
                key=lambda a: (
                    a.oferta_id,
                    a.version,
                    a.lote_id,
                    a.aporte_id,
                    str(a.recurso_nacional_id),
                ),
            )
        }
    )
    with transaccion_operacion(session):
        origen = autorizar_emisor(session, cuenta, datos.sistema_origen)
        operacion, nueva = reclamar_operacion(
            session,
            origen_id=origen.id,
            cuenta_id=cuenta.id,
            tipo=TipoOperacion.COMPROMETER,
            clave=clave,
            huella=huella_operacion(
                TipoOperacion.COMPROMETER, datos.id_emergencia, normalizado
            ),
        )
        bloquear_autor(session, cuenta.id, origen.id)
        if not nueva:
            return ConfirmacionCompromisos.model_validate(operacion.respuesta_minima)
        proyecto = _proyecto_adjudicacion(session, origen.id, datos)
        _bloquear_competencias(session, datos)
        recurso_ids = {a.recurso_nacional_id for a in datos.aportes}
        recursos_bloqueados = bloquear_recursos(session, recurso_ids)
        if len(recursos_bloqueados) != len(recurso_ids):
            raise OperacionNoEncontradaError("Un recurso nacional no existe.")
        # Nueva sentencia y reloj después de todas las esperas de locks.
        ahora = datetime.now(UTC)
        recursos = consultar_recursos(session, recurso_ids)
        perfiles = {
            p.ong_id: p
            for _, p in consultar_certificaciones_ongs(
                session, ong_ids={a.ong_nacional_id for a in datos.aportes}, ahora=ahora
            )
        }
        demanda: dict[UUID, Decimal] = {}
        with localcontext() as contexto:
            contexto.prec = max(28, 14 + len(str(len(datos.aportes))) + 3)
            for aporte in datos.aportes:
                recurso, capacidad, disponible = recursos[aporte.recurso_nacional_id]
                perfil = evaluar_aporte(
                    RequerimientoAporte(
                        aporte.ong_nacional_id,
                        aporte.capacidad_nacional_id,
                        aporte.capacidad_nacional_id,
                        aporte.riesgo_requerido,
                        aporte.unidad,
                        aporte.cantidad,
                    ),
                    perfil=perfiles.get(aporte.ong_nacional_id),
                    recurso=recurso,
                    capacidad=capacidad,
                    disponible=disponible,
                    gravedad=aporte.riesgo_requerido,
                )
                if (
                    perfil.clasificacion == Clasificacion.SIN_HABILITACION
                    or perfil.motivos
                ):
                    codigos = ", ".join(m.codigo for m in perfil.motivos)
                    raise ErrorOperacion(
                        f"Un aporte no cumple la validación nacional: {codigos}."
                    )
                rid = aporte.recurso_nacional_id
                demanda[rid] = demanda.get(rid, Decimal(0)) + aporte.cantidad
            if any(cantidad > recursos[rid][2] for rid, cantidad in demanda.items()):
                raise ErrorOperacion(
                    "La suma adjudicada excede la disponibilidad de un recurso."
                )
        compromisos: dict[UUID, Compromiso] = {}
        for ong_id in sorted(perfiles):
            compromiso = Compromiso(
                id=uuid4(),
                proyecto_id=proyecto.id,
                ong_id=ong_id,
                operacion_creacion_id=operacion.id,
                adjudicacion_ref=datos.adjudicacion_id,
            )
            session.add(compromiso)
            compromisos[ong_id] = compromiso
        session.flush()
        for aporte in normalizado.aportes:
            session.add(
                CompromisoItem(
                    compromiso_id=compromisos[aporte.ong_nacional_id].id,
                    recurso_id=aporte.recurso_nacional_id,
                    ong_id=aporte.ong_nacional_id,
                    convocatoria_ref=datos.convocatoria_id,
                    oferta_ref=aporte.oferta_id,
                    oferta_version=aporte.version,
                    lote_ref=aporte.lote_id,
                    aporte_ref=aporte.aporte_id,
                    riesgo_requerido=aporte.riesgo_requerido,
                    cantidad=aporte.cantidad,
                )
            )
        resultado = ConfirmacionCompromisos(
            operacion_id=operacion.id,
            proyecto_id=proyecto.id,
            compromiso_ids=[c.id for c in compromisos.values()],
            registrado_en=ahora,
        )
        confirmar_operacion(
            operacion,
            proyecto.id,
            201,
            resultado.model_dump(mode="json", by_alias=True),
        )
        session.flush()
        return resultado


def consultar_compromiso(
    session: Session, cuenta: Cuenta, compromiso_id: UUID
) -> CompromisoResponse:
    """El GET muestra el estado actual; el POST reproduce su confirmación original."""
    fila = session.execute(
        select(Compromiso, Proyecto, SistemaOrigen)
        .join(Proyecto, Proyecto.id == Compromiso.proyecto_id)
        .join(SistemaOrigen, SistemaOrigen.id == Proyecto.sistema_origen_id)
        .where(Compromiso.id == compromiso_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if fila is None:
        raise OperacionNoEncontradaError("El compromiso nacional no existe.")
    compromiso, proyecto, origen = fila
    autorizar_emisor(session, cuenta, origen.codigo)
    filas = session.execute(
        select(CompromisoItem, Capacidad)
        .join(Recurso, Recurso.id == CompromisoItem.recurso_id)
        .join(Capacidad, Capacidad.id == Recurso.capacidad_id)
        .where(CompromisoItem.compromiso_id == compromiso_id)
        .order_by(CompromisoItem.id)
    )
    items = [
        ItemCompromisoResponse(
            id=item.id,
            convocatoria_id=item.convocatoria_ref,
            oferta_id=item.oferta_ref,
            version=item.oferta_version,
            lote_id=item.lote_ref,
            aporte_id=item.aporte_ref,
            ong_nacional_id=item.ong_id,
            recurso_nacional_id=item.recurso_id,
            capacidad_nacional_id=capacidad.id,
            riesgo_requerido=item.riesgo_requerido,
            cantidad=item.cantidad,
            unidad=capacidad.unidad,
        )
        for item, capacidad in filas
    ]
    return CompromisoResponse(
        id=compromiso.id,
        proyecto_id=proyecto.id,
        sistema_origen=origen.codigo,
        id_emergencia=proyecto.emergencia_ref,
        case_id=proyecto.case_ref,
        adjudicacion_id=compromiso.adjudicacion_ref,
        ong_nacional_id=compromiso.ong_id,
        estado=compromiso.estado,
        creado_en=compromiso.creado_en,
        liberado_en=compromiso.liberado_en,
        liberado_por_id=compromiso.liberado_por_id,
        items=items,
    )
