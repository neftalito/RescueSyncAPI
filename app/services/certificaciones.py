"""Consulta de competencia vigente y administración atómica de acreditaciones."""

from datetime import UTC, datetime
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Capacidad,
    Certificacion,
    CertificacionCapacidad,
    Cuenta,
    EstadoAcreditacion,
    EstadoOng,
    NivelRiesgo,
    Ong,
    OngCertificacion,
    RolNacional,
)
from app.schemas.certificaciones import (
    AcreditacionCreate,
    AcreditacionResponse,
    AlcanceResponse,
    CapacidadHabilitadaResponse,
    CertificacionCreate,
    CertificacionesOngResponse,
    CertificacionResponse,
    CodigoMotivo,
    EstadoVigencia,
    MotivoResponse,
    RevocacionRequest,
)

RIESGOS = tuple(NivelRiesgo)
ORDEN_RIESGO = {nivel: indice for indice, nivel in enumerate(RIESGOS)}
MENSAJES = {
    CodigoMotivo.ACREDITACION_FUTURA: "La acreditación todavía no inició su vigencia.",
    CodigoMotivo.ACREDITACION_VENCIDA: "La acreditación venció.",
    CodigoMotivo.ACREDITACION_REVOCADA: "La acreditación fue revocada.",
    CodigoMotivo.CERTIFICACION_INACTIVA: "La revisión de certificación está inactiva.",
    CodigoMotivo.CAPACIDAD_INACTIVA: "La capacidad está inactiva.",
    CodigoMotivo.ONG_PENDIENTE: "La ONG tiene pendiente su habilitación institucional.",
    CodigoMotivo.ONG_SUSPENDIDA: "La ONG está suspendida.",
    CodigoMotivo.ONG_BAJA: "La ONG fue dada de baja.",
}


class CertificacionNoEncontradaError(LookupError):
    """Una referencia administrativa o institucional no existe."""


class CertificacionConflictivaError(ValueError):
    """La operación contradice el catálogo, una credencial o su historial."""


class AdministracionDenegadaError(PermissionError):
    """Sólo una cuenta administrativa nacional vigente puede acreditar."""


def _motivo(codigo: CodigoMotivo, capacidad_id: UUID | None = None) -> MotivoResponse:
    return MotivoResponse(
        codigo=codigo, mensaje=MENSAJES[codigo], capacidad_id=capacidad_id
    )


def _alcance(capacidad: Capacidad, alcance: CertificacionCapacidad) -> AlcanceResponse:
    return AlcanceResponse(
        capacidad_id=capacidad.id,
        codigo=capacidad.codigo,
        nombre=capacidad.nombre,
        tipo=capacidad.tipo,
        unidad=capacidad.unidad,
        admite_fracciones=capacidad.admite_fracciones,
        activa=capacidad.activa,
        riesgo_maximo=alcance.riesgo_maximo,
    )


def _certificacion(certificacion: Certificacion) -> CertificacionResponse:
    return CertificacionResponse(
        id=certificacion.id,
        codigo=certificacion.codigo,
        revision=certificacion.revision,
        nombre=certificacion.nombre,
        activa=certificacion.activa,
        alcances=[],
    )


def listar_certificaciones(
    session: Session,
    *,
    capacidad_id: UUID | None = None,
    nivel_riesgo: NivelRiesgo | None = None,
    incluir_inactivas: bool = False,
) -> list[CertificacionResponse]:
    """Los filtros seleccionan revisiones y conservan todos sus alcances."""
    consulta = (
        select(Certificacion, CertificacionCapacidad, Capacidad)
        .outerjoin(
            CertificacionCapacidad,
            CertificacionCapacidad.certificacion_id == Certificacion.id,
        )
        .outerjoin(Capacidad, Capacidad.id == CertificacionCapacidad.capacidad_id)
        .order_by(
            Certificacion.codigo,
            Certificacion.revision,
            Certificacion.id,
            Capacidad.codigo,
            Capacidad.id,
        )
    )
    if not incluir_inactivas:
        consulta = consulta.where(Certificacion.activa)
    if capacidad_id is not None or nivel_riesgo is not None:
        compatible = (
            select(CertificacionCapacidad.certificacion_id)
            .join(Capacidad, Capacidad.id == CertificacionCapacidad.capacidad_id)
            .where(
                CertificacionCapacidad.certificacion_id == Certificacion.id,
                Capacidad.activa,
            )
            .correlate(Certificacion)
        )
        if capacidad_id is not None:
            compatible = compatible.where(
                CertificacionCapacidad.capacidad_id == capacidad_id
            )
        if nivel_riesgo is not None:
            compatible = compatible.where(
                CertificacionCapacidad.riesgo_maximo.in_(
                    RIESGOS[ORDEN_RIESGO[nivel_riesgo] :]
                )
            )
        consulta = consulta.where(compatible.exists())
    resultado: dict[UUID, CertificacionResponse] = {}
    for certificacion, alcance, capacidad in session.execute(consulta):
        respuesta = resultado.setdefault(
            certificacion.id, _certificacion(certificacion)
        )
        if alcance is not None and capacidad is not None:
            respuesta.alcances.append(_alcance(capacidad, alcance))
    return list(resultado.values())


def estado_vigencia(
    estado: EstadoAcreditacion, desde: datetime, hasta: datetime, ahora: datetime
) -> EstadoVigencia:
    """Evalúa [desde, hasta), dando prioridad a la revocación."""
    if estado == EstadoAcreditacion.REVOCADA:
        return EstadoVigencia.REVOCADA
    if ahora < desde:
        return EstadoVigencia.FUTURA
    return EstadoVigencia.VIGENTE if ahora < hasta else EstadoVigencia.VENCIDA


def consultar_certificaciones_ong(
    session: Session, ong_id: UUID, *, ahora: datetime | None = None
) -> CertificacionesOngResponse:
    """Carga institución e historia en un snapshot; nunca persiste el perfil."""
    perfiles = consultar_certificaciones_ongs(session, ong_id=ong_id, ahora=ahora)
    if not perfiles:
        raise CertificacionNoEncontradaError("La ONG nacional no existe.")
    return perfiles[0][1]


type FilaCertificaciones = tuple[
    Ong,
    OngCertificacion | None,
    Certificacion | None,
    CertificacionCapacidad | None,
    Capacidad | None,
]


def consultar_certificaciones_ongs(
    session: Session,
    *,
    ong_id: UUID | None = None,
    solo_habilitadas: bool = False,
    ahora: datetime | None = None,
) -> list[tuple[str, CertificacionesOngResponse]]:
    """Evalúa varias instituciones en un único snapshot y con el mismo reloj UTC."""
    evaluado_en = ahora or datetime.now(UTC)
    consulta = (
        select(Ong, OngCertificacion, Certificacion, CertificacionCapacidad, Capacidad)
        .outerjoin(OngCertificacion, OngCertificacion.ong_id == Ong.id)
        .outerjoin(Certificacion, Certificacion.id == OngCertificacion.certificacion_id)
        .outerjoin(
            CertificacionCapacidad,
            CertificacionCapacidad.certificacion_id == Certificacion.id,
        )
        .outerjoin(Capacidad, Capacidad.id == CertificacionCapacidad.capacidad_id)
        .order_by(
            Ong.nombre,
            Ong.id,
            OngCertificacion.vigente_desde,
            OngCertificacion.id,
            Capacidad.codigo,
            Capacidad.id,
        )
        .execution_options(populate_existing=True)
    )
    if ong_id is not None:
        consulta = consulta.where(Ong.id == ong_id)
    if solo_habilitadas:
        consulta = consulta.where(Ong.estado == EstadoOng.HABILITADA)
    grupos: dict[UUID, list[FilaCertificaciones]] = {}
    for ong, credencial, certificacion, alcance, capacidad in session.execute(consulta):
        grupos.setdefault(ong.id, []).append(
            (ong, credencial, certificacion, alcance, capacidad)
        )
    return [
        (filas[0][0].nombre, _construir_perfil(filas, evaluado_en))
        for filas in grupos.values()
    ]


def _construir_perfil(
    filas: list[FilaCertificaciones], evaluado_en: datetime
) -> CertificacionesOngResponse:
    """Comparte reglas de competencia entre historia individual y directorio."""
    ong = filas[0][0]
    institucionales = (
        []
        if ong.estado == EstadoOng.HABILITADA
        else [_motivo(CodigoMotivo(f"ONG_{ong.estado.value}"))]
    )
    acreditaciones: dict[UUID, AcreditacionResponse] = {}
    for _, credencial, certificacion, alcance, capacidad in filas:
        if credencial is None or certificacion is None:
            continue
        if credencial.id not in acreditaciones:
            temporal = estado_vigencia(
                credencial.estado,
                credencial.vigente_desde,
                credencial.vigente_hasta,
                evaluado_en,
            )
            motivos = list(institucionales)
            if temporal != EstadoVigencia.VIGENTE:
                motivos.append(_motivo(CodigoMotivo(f"ACREDITACION_{temporal.value}")))
            if not certificacion.activa:
                motivos.append(_motivo(CodigoMotivo.CERTIFICACION_INACTIVA))
            acreditaciones[credencial.id] = AcreditacionResponse(
                id=credencial.id,
                certificacion=_certificacion(certificacion),
                emisor=credencial.emisor,
                numero_credencial=credencial.numero_credencial,
                vigente_desde=credencial.vigente_desde,
                vigente_hasta=credencial.vigente_hasta,
                estado=credencial.estado,
                estado_vigencia=temporal,
                revocada_en=credencial.revocada_en,
                motivo_revocacion=credencial.motivo_revocacion,
                motivos=motivos,
            )
        respuesta = acreditaciones[credencial.id]
        if alcance is not None and capacidad is not None:
            respuesta.certificacion.alcances.append(_alcance(capacidad, alcance))
            if not capacidad.activa:
                respuesta.motivos.append(
                    _motivo(CodigoMotivo.CAPACIDAD_INACTIVA, capacidad.id)
                )
    habilitadas: dict[UUID, CapacidadHabilitadaResponse] = {}
    for credencial in acreditaciones.values():
        if (
            institucionales
            or credencial.estado_vigencia != EstadoVigencia.VIGENTE
            or not credencial.certificacion.activa
        ):
            continue
        for alcance in credencial.certificacion.alcances:
            if not alcance.activa:
                continue
            perfil = habilitadas.setdefault(
                alcance.capacidad_id,
                CapacidadHabilitadaResponse(
                    capacidad_id=alcance.capacidad_id,
                    codigo=alcance.codigo,
                    nombre=alcance.nombre,
                    unidad=alcance.unidad,
                    riesgo_maximo=alcance.riesgo_maximo,
                    niveles_riesgo_permitidos=[],
                    acreditacion_ids=[],
                ),
            )
            if ORDEN_RIESGO[alcance.riesgo_maximo] > ORDEN_RIESGO[perfil.riesgo_maximo]:
                perfil.riesgo_maximo = alcance.riesgo_maximo
            perfil.niveles_riesgo_permitidos = list(
                RIESGOS[: ORDEN_RIESGO[perfil.riesgo_maximo] + 1]
            )
            perfil.acreditacion_ids.append(credencial.id)
    return CertificacionesOngResponse(
        ong_id=ong.id,
        estado_ong=ong.estado,
        evaluado_en=evaluado_en,
        acreditaciones=list(acreditaciones.values()),
        capacidades_habilitadas=sorted(
            habilitadas.values(), key=lambda p: (p.codigo, p.capacidad_id)
        ),
        motivos_institucionales=institucionales,
    )


def _admin(session: Session, cuenta_id: UUID) -> Cuenta:
    cuenta = session.scalar(
        select(Cuenta)
        .where(Cuenta.id == cuenta_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if cuenta is None or not cuenta.activa or cuenta.rol != RolNacional.ADMIN_NACIONAL:
        raise AdministracionDenegadaError("Necesitás una cuenta administrativa activa.")
    return cuenta


def _ong_bloqueada(session: Session, ong_id: UUID) -> Ong:
    ong = session.scalar(
        select(Ong)
        .where(Ong.id == ong_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if ong is None:
        raise CertificacionNoEncontradaError("La ONG nacional no existe.")
    return ong


def _reutilizar_revision(
    session: Session, revision: Certificacion, datos: CertificacionCreate
) -> UUID:
    alcances = session.execute(
        select(
            CertificacionCapacidad.capacidad_id,
            CertificacionCapacidad.riesgo_maximo,
        ).where(CertificacionCapacidad.certificacion_id == revision.id)
    ).all()
    if (
        revision.activa
        and revision.nombre == datos.nombre
        and dict(alcances) == {a.capacidad_id: a.riesgo_maximo for a in datos.alcances}
    ):
        return revision.id
    raise CertificacionConflictivaError("La revisión existe con otro contenido.")


def publicar_certificacion(
    session: Session, cuenta_id: UUID, datos: CertificacionCreate
) -> UUID:
    """El caller confirma la transacción; capacidades antes de revisión."""
    _admin(session, cuenta_id)
    ids = {a.capacidad_id for a in datos.alcances}
    capacidades = session.scalars(
        select(Capacidad)
        .where(Capacidad.id.in_(ids))
        .order_by(Capacidad.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    ).all()
    if len(capacidades) != len(ids):
        raise CertificacionNoEncontradaError("Una capacidad nacional no existe.")
    if any(not c.activa for c in capacidades):
        raise CertificacionConflictivaError("No se publican alcances inactivos.")
    revision = session.scalar(
        select(Certificacion)
        .where(
            Certificacion.codigo == datos.codigo,
            Certificacion.revision == datos.revision,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if revision is not None:
        return _reutilizar_revision(session, revision, datos)
    try:
        # La unicidad resuelve el caso donde aún no existe una fila para bloquear.
        with session.begin_nested():
            revision = Certificacion(
                codigo=datos.codigo,
                revision=datos.revision,
                nombre=datos.nombre,
                activa=False,
            )
            session.add(revision)
            session.flush()
            session.add_all(
                [
                    CertificacionCapacidad(
                        certificacion_id=revision.id,
                        capacidad_id=a.capacidad_id,
                        riesgo_maximo=a.riesgo_maximo,
                    )
                    for a in datos.alcances
                ]
            )
            session.flush()
            revision.activa = True
            revision.actualizado_en = datetime.now(UTC)
            session.flush()
        return revision.id
    except IntegrityError as error:
        if (
            not isinstance(error.orig, UniqueViolation)
            or error.orig.diag.constraint_name != "uq_certificacion_revision"
        ):
            raise
        revision = session.scalar(
            select(Certificacion)
            .where(
                Certificacion.codigo == datos.codigo,
                Certificacion.revision == datos.revision,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if revision is None:
            raise
        return _reutilizar_revision(session, revision, datos)


def otorgar_acreditacion(
    session: Session, cuenta_id: UUID, datos: AcreditacionCreate
) -> UUID:
    """Renovar requiere otra credencial; no habilita institucionalmente a la ONG."""
    _admin(session, cuenta_id)
    _ong_bloqueada(session, datos.ong_id)
    # El lock de ONG serializa registros con la misma clave de credencial.
    existente = session.scalar(
        select(OngCertificacion)
        .where(
            OngCertificacion.ong_id == datos.ong_id,
            OngCertificacion.emisor == datos.emisor,
            OngCertificacion.numero_credencial == datos.numero_credencial,
        )
        .execution_options(populate_existing=True)
    )
    if existente is not None:
        if (
            existente.certificacion_id == datos.certificacion_id
            and existente.vigente_desde == datos.vigente_desde
            and existente.vigente_hasta == datos.vigente_hasta
        ):
            return existente.id
        raise CertificacionConflictivaError("La credencial existe con otro contenido.")
    capacidades = session.scalars(
        select(Capacidad)
        .join(
            CertificacionCapacidad, CertificacionCapacidad.capacidad_id == Capacidad.id
        )
        .where(CertificacionCapacidad.certificacion_id == datos.certificacion_id)
        .order_by(Capacidad.id)
        .with_for_update(read=True, of=Capacidad)
        .execution_options(populate_existing=True)
    ).all()
    revision = session.scalar(
        select(Certificacion)
        .where(Certificacion.id == datos.certificacion_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if revision is None:
        raise CertificacionNoEncontradaError("La certificación nacional no existe.")
    if not revision.activa or not capacidades or any(not c.activa for c in capacidades):
        raise CertificacionConflictivaError(
            "La revisión o sus alcances no están activos."
        )
    ids_actuales = set(
        session.scalars(
            select(CertificacionCapacidad.capacidad_id).where(
                CertificacionCapacidad.certificacion_id == datos.certificacion_id
            )
        )
    )
    if ids_actuales != {c.id for c in capacidades}:
        raise CertificacionConflictivaError(
            "Los alcances cambiaron durante la carga. Reintentá la operación."
        )
    credencial = OngCertificacion(
        ong_id=datos.ong_id,
        certificacion_id=datos.certificacion_id,
        emisor=datos.emisor,
        numero_credencial=datos.numero_credencial,
        vigente_desde=datos.vigente_desde.astimezone(UTC),
        vigente_hasta=datos.vigente_hasta.astimezone(UTC),
        registrada_por_id=cuenta_id,
    )
    session.add(credencial)
    session.flush()
    return credencial.id


def revocar_acreditacion(
    session: Session, cuenta_id: UUID, datos: RevocacionRequest
) -> UUID:
    """Una repetición no altera autor, fecha ni motivo de la revocación."""
    _admin(session, cuenta_id)
    _ong_bloqueada(session, datos.ong_id)
    credencial = session.scalar(
        select(OngCertificacion)
        .where(
            OngCertificacion.id == datos.acreditacion_id,
            OngCertificacion.ong_id == datos.ong_id,
        )
        .execution_options(populate_existing=True)
    )
    if credencial is None:
        raise CertificacionNoEncontradaError("La acreditación de esa ONG no existe.")
    session.scalar(
        select(Certificacion)
        .where(Certificacion.id == credencial.certificacion_id)
        .with_for_update()
    )
    session.refresh(credencial, with_for_update=True)
    if credencial.estado == EstadoAcreditacion.REVOCADA:
        if credencial.motivo_revocacion == datos.motivo:
            return credencial.id
        raise CertificacionConflictivaError("La acreditación ya fue revocada.")
    credencial.estado = EstadoAcreditacion.REVOCADA
    credencial.revocada_por_id = cuenta_id
    credencial.revocada_en = datetime.now(UTC)
    credencial.motivo_revocacion = datos.motivo
    session.flush()
    return credencial.id


def habilitar_ong(session: Session, cuenta_id: UUID, ong_id: UUID) -> UUID:
    """Habilita sólo una institución pendiente, sin otorgar competencias."""
    _admin(session, cuenta_id)
    ong = _ong_bloqueada(session, ong_id)
    if ong.estado == EstadoOng.HABILITADA:
        return ong.id
    if ong.estado != EstadoOng.PENDIENTE:
        raise CertificacionConflictivaError("La ONG no está pendiente de habilitación.")
    ong.estado = EstadoOng.HABILITADA
    ong.habilitada_en = datetime.now(UTC)
    ong.habilitada_por_id = cuenta_id
    ong.actualizado_en = ong.habilitada_en
    session.flush()
    return ong.id
