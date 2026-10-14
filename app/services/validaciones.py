"""Evalúa referencias, competencia y stock sin guardar ofertas ni reservar."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Capacidad, EstadoOng, NivelRiesgo, Recurso
from app.schemas.certificaciones import CertificacionesOngResponse
from app.schemas.validaciones import (
    AporteEvaluado,
    Clasificacion,
    CodigoMotivoValidacion,
    MotivoValidacion,
    PerfilAporte,
    RecursoConsultado,
    ValidacionRequest,
    ValidacionResponse,
)
from app.services.certificaciones import ORDEN_RIESGO, consultar_certificaciones_ongs
from app.services.disponibilidad import InventarioInconsistenteError
from app.services.inventario import compromisos_activos_por_recurso


@dataclass(frozen=True, slots=True)
class RequerimientoAporte:
    """Referencias nacionales que también se revalidan al comprometer en T32."""

    ong_id: UUID | None
    capacidad_id: UUID | None
    capacidad_declarada_id: UUID | None
    riesgo: NivelRiesgo | None
    unidad: str
    cantidad: Decimal


def motivo(codigo: CodigoMotivoValidacion) -> MotivoValidacion:
    """Explica un código estable sin incluir payloads ni detalles de SQL."""
    mensajes = {
        CodigoMotivoValidacion.ONG_NO_ENCONTRADA: "La ONG nacional no existe.",
        CodigoMotivoValidacion.ONG_NO_HABILITADA: "La ONG no está habilitada.",
        CodigoMotivoValidacion.REFERENCIAS_INCOMPLETAS: "Faltan referencias.",
        CodigoMotivoValidacion.DESGLOSE_NACIONAL_AUSENTE: "Falta el desglose nacional.",
        CodigoMotivoValidacion.RECURSO_NO_ENCONTRADO: "El recurso nacional no existe.",
        CodigoMotivoValidacion.RECURSO_INACTIVO: "El recurso está inactivo.",
        CodigoMotivoValidacion.RECURSO_AJENO: "El recurso pertenece a otra ONG.",
        CodigoMotivoValidacion.CAPACIDAD_NO_ENCONTRADA: "La capacidad no existe.",
        CodigoMotivoValidacion.CAPACIDAD_INACTIVA: "La capacidad está inactiva.",
        CodigoMotivoValidacion.CAPACIDAD_INCOMPATIBLE: "La capacidad no coincide.",
        CodigoMotivoValidacion.UNIDAD_INCOMPATIBLE: "La unidad no coincide.",
        CodigoMotivoValidacion.CANTIDAD_NO_DISCRETA: "La capacidad requiere enteros.",
        CodigoMotivoValidacion.SIN_ACREDITACION_VIGENTE: "No hay acreditación vigente.",
        CodigoMotivoValidacion.ACREDITACION_VENCIDA: "La acreditación venció.",
        CodigoMotivoValidacion.ACREDITACION_REVOCADA: "La acreditación fue revocada.",
        CodigoMotivoValidacion.ACREDITACION_FUTURA: "La acreditación no inició.",
        CodigoMotivoValidacion.CERTIFICACION_INACTIVA: "Certificación inactiva.",
        CodigoMotivoValidacion.RIESGO_NO_PERMITIDO: "Riesgo fuera de alcance.",
        CodigoMotivoValidacion.DISPONIBILIDAD_INSUFICIENTE: "Stock insuficiente.",
    }
    return MotivoValidacion(codigo=codigo, mensaje=mensajes[codigo])


def evaluar_aporte(
    requerimiento: RequerimientoAporte,
    *,
    perfil: CertificacionesOngResponse | None,
    recurso: Recurso | None,
    capacidad: Capacidad | None,
    disponible: Decimal | None,
    gravedad: NivelRiesgo | None,
) -> PerfilAporte:
    """La competencia no desaparece por falta de stock; nunca reserva cantidades."""
    req = requerimiento
    codigos: list[CodigoMotivoValidacion] = []
    if req.ong_id is None or req.capacidad_id is None or req.riesgo is None:
        codigos.append(CodigoMotivoValidacion.REFERENCIAS_INCOMPLETAS)
    if perfil is None:
        codigos.append(CodigoMotivoValidacion.ONG_NO_ENCONTRADA)
    elif perfil.estado_ong != EstadoOng.HABILITADA:
        codigos.append(CodigoMotivoValidacion.ONG_NO_HABILITADA)
    if recurso is None:
        codigos.append(CodigoMotivoValidacion.RECURSO_NO_ENCONTRADO)
    else:
        if not recurso.activo:
            codigos.append(CodigoMotivoValidacion.RECURSO_INACTIVO)
        if recurso.ong_id != req.ong_id:
            codigos.append(CodigoMotivoValidacion.RECURSO_AJENO)
        if (
            recurso.capacidad_id != req.capacidad_id
            or recurso.capacidad_id != req.capacidad_declarada_id
        ):
            codigos.append(CodigoMotivoValidacion.CAPACIDAD_INCOMPATIBLE)
    if capacidad is None:
        codigos.append(CodigoMotivoValidacion.CAPACIDAD_NO_ENCONTRADA)
    else:
        if not capacidad.activa:
            codigos.append(CodigoMotivoValidacion.CAPACIDAD_INACTIVA)
        if capacidad.unidad != req.unidad:
            codigos.append(CodigoMotivoValidacion.UNIDAD_INCOMPATIBLE)
        if (
            not capacidad.admite_fracciones
            and req.cantidad != req.cantidad.to_integral()
        ):
            codigos.append(CodigoMotivoValidacion.CANTIDAD_NO_DISCRETA)
    capacidades = perfil.capacidades_habilitadas if perfil else []
    habilitada = next(
        (c for c in capacidades if c.capacidad_id == req.capacidad_id), None
    )
    niveles = habilitada.niveles_riesgo_permitidos if habilitada else []
    if habilitada is None:
        codigos.append(CodigoMotivoValidacion.SIN_ACREDITACION_VIGENTE)
        if perfil is not None:
            for credencial in perfil.acreditaciones:
                if any(
                    a.capacidad_id == req.capacidad_id
                    for a in credencial.certificacion.alcances
                ):
                    for razon in credencial.motivos:
                        if razon.codigo.value in CodigoMotivoValidacion:
                            codigos.append(CodigoMotivoValidacion(razon.codigo.value))
    elif req.riesgo not in niveles:
        codigos.append(CodigoMotivoValidacion.RIESGO_NO_PERMITIDO)
    if gravedad is None:
        codigos.append(CodigoMotivoValidacion.REFERENCIAS_INCOMPLETAS)
    clasificacion = Clasificacion.SIN_HABILITACION
    if not codigos and habilitada is not None and gravedad is not None:
        clasificacion = (
            Clasificacion.PRINCIPAL
            if ORDEN_RIESGO[habilitada.riesgo_maximo] >= ORDEN_RIESGO[gravedad]
            else Clasificacion.APOYO
        )
    if disponible is not None and disponible < req.cantidad:
        codigos.append(CodigoMotivoValidacion.DISPONIBILIDAD_INSUFICIENTE)
    return PerfilAporte(
        clasificacion=clasificacion,
        capacidades_habilitadas=capacidades,
        niveles_riesgo_permitidos=niveles,
        cantidad_disponible_consultada=disponible,
        motivos=[motivo(c) for c in dict.fromkeys(codigos)],
    )


def consultar_recursos(
    session: Session, ids: set[UUID]
) -> dict[UUID, tuple[Recurso, Capacidad, Decimal]]:
    """Carga filas concretas y suma compromisos una sola vez por recurso."""
    compromisos = compromisos_activos_por_recurso()
    filas = session.execute(
        select(Recurso, Capacidad, func.coalesce(compromisos.c.cantidad, 0))
        .join(Capacidad, Capacidad.id == Recurso.capacidad_id)
        .outerjoin(compromisos, compromisos.c.recurso_id == Recurso.id)
        .where(Recurso.id.in_(ids))
        .order_by(Recurso.id)
        .execution_options(populate_existing=True)
    )
    resultado: dict[UUID, tuple[Recurso, Capacidad, Decimal]] = {}
    for recurso, capacidad, comprometida in filas:
        disponible = recurso.cantidad_total - comprometida
        if disponible < 0:
            raise InventarioInconsistenteError("El inventario no es consistente.")
        resultado[recurso.id] = (recurso, capacidad, disponible)
    return resultado


def validar_snapshot(
    session: Session, snapshot: ValidacionRequest, *, ahora: datetime | None = None
) -> ValidacionResponse:
    """Evalúa un snapshot cerrado con perfiles locales transitorios y reloj único."""
    evaluado_en = ahora or datetime.now(UTC)
    ong_ids = {
        p.ong_nacional_id
        for o in snapshot.ofertas
        for p in o.participantes
        if p.ong_nacional_id is not None
    }
    perfiles = {
        p.ong_id: p
        for _, p in consultar_certificaciones_ongs(
            session, ong_ids=ong_ids, ahora=evaluado_en
        )
    }
    aportes = [a for o in snapshot.ofertas for i in o.items for a in i.aportes]
    recursos = consultar_recursos(session, {a.recurso_nacional_id for a in aportes})
    capacidad_ids = {
        lote.capacidad_nacional_id
        for lote in snapshot.lotes
        if lote.capacidad_nacional_id is not None
    }
    capacidades = {
        c.id: c
        for c in session.scalars(
            select(Capacidad).where(Capacidad.id.in_(capacidad_ids))
        )
    }
    lotes = {lote.lote_id: lote for lote in snapshot.lotes}
    resultados: list[AporteEvaluado] = []
    demanda: dict[UUID, Decimal] = {}
    with localcontext() as contexto:
        contexto.prec = max(28, 14 + len(str(len(aportes))) + 3)
        for oferta in snapshot.ofertas:
            for item in oferta.items:
                lote = lotes[item.lote_id]
                if not item.aportes:
                    resultados.append(
                        AporteEvaluado(
                            oferta_id=oferta.oferta_id,
                            version=oferta.version,
                            item_id=item.item_id,
                            lote_id=item.lote_id,
                            aporte_id=None,
                            ong_id=oferta.ong_id,
                            ong_nacional_id=oferta.ong_nacional_id,
                            recurso_nacional_id=None,
                            cantidad_ofrecida=item.cantidad_ofrecida_exacta,
                            unidad=item.unidad,
                            clasificacion=Clasificacion.SIN_HABILITACION,
                            capacidades_habilitadas=[],
                            niveles_riesgo_permitidos=[],
                            cantidad_disponible_consultada=None,
                            motivos=[
                                motivo(CodigoMotivoValidacion.DESGLOSE_NACIONAL_AUSENTE)
                            ],
                        )
                    )
                for aporte in item.aportes:
                    datos = recursos.get(aporte.recurso_nacional_id)
                    capacidad = capacidades.get(lote.capacidad_nacional_id)
                    perfil = evaluar_aporte(
                        RequerimientoAporte(
                            aporte.ong_nacional_id,
                            lote.capacidad_nacional_id,
                            aporte.capacidad_nacional_id,
                            lote.riesgo_requerido,
                            aporte.unidad,
                            aporte.cantidad,
                        ),
                        perfil=perfiles.get(aporte.ong_nacional_id),
                        recurso=datos[0] if datos else None,
                        capacidad=capacidad,
                        disponible=datos[2] if datos else None,
                        gravedad=snapshot.gravedad,
                    )
                    if item.unidad != lote.unidad or aporte.unidad != lote.unidad:
                        perfil.clasificacion = Clasificacion.SIN_HABILITACION
                        perfil.motivos.append(
                            motivo(CodigoMotivoValidacion.UNIDAD_INCOMPATIBLE)
                        )
                    if capacidad and lote.codigo_capacidad != capacidad.codigo:
                        perfil.clasificacion = Clasificacion.SIN_HABILITACION
                        perfil.motivos.append(
                            motivo(CodigoMotivoValidacion.CAPACIDAD_INCOMPATIBLE)
                        )
                    resultados.append(
                        AporteEvaluado(
                            **perfil.model_dump(),
                            oferta_id=oferta.oferta_id,
                            version=oferta.version,
                            item_id=item.item_id,
                            lote_id=item.lote_id,
                            aporte_id=aporte.aporte_id,
                            ong_id=aporte.ong_id,
                            ong_nacional_id=aporte.ong_nacional_id,
                            recurso_nacional_id=aporte.recurso_nacional_id,
                            cantidad_ofrecida=aporte.cantidad,
                            unidad=aporte.unidad,
                        )
                    )
                    rid = aporte.recurso_nacional_id
                    demanda[rid] = demanda.get(rid, Decimal(0)) + aporte.cantidad
        resumen = [
            RecursoConsultado(
                recurso_nacional_id=rid,
                ong_nacional_id=recurso.ong_id,
                capacidad_nacional_id=capacidad.id,
                unidad=capacidad.unidad,
                cantidad_disponible=disponible,
                cantidad_solicitada_snapshot=demanda[rid],
            )
            for rid, (recurso, capacidad, disponible) in recursos.items()
        ]
    return ValidacionResponse(
        sistema_origen=snapshot.sistema_origen,
        id_emergencia=snapshot.id_emergencia,
        case_id=snapshot.case_id,
        convocatoria_id=snapshot.convocatoria_id,
        numero=snapshot.numero,
        evaluado_en=evaluado_en,
        aportes=resultados,
        recursos_consultados=resumen,
    )
