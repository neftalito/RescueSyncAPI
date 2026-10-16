"""Escenario de competencia demo; fechas e historia se conservan al repetirlo."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Capacidad,
    Certificacion,
    CertificacionCapacidad,
    EstadoAcreditacion,
    EstadoOng,
    NivelRiesgo,
    Ong,
    OngCertificacion,
)
from app.scripts.seed_admin import asegurar_admin_demo


def _id(referencia: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"rescuesync-demo:{referencia}")


def seed_certificaciones(session: Session, *, ahora: datetime | None = None) -> None:
    """Sólo desarrollo/test; no reemplaza cuentas, revisiones ni credenciales."""
    if get_settings().app_env not in {"development", "test"}:
        raise ValueError("El seed sólo está disponible en desarrollo y pruebas.")
    instante = ahora or datetime.now(UTC)
    admin, _ = asegurar_admin_demo(session)
    admin_id = admin.id
    revisiones: dict[str, UUID] = {}
    for codigo, alcances in (
        (
            "DEMO_SANITARIA",
            (("PARAMEDICOS", NivelRiesgo.ALTA), ("AMBULANCIAS", NivelRiesgo.MEDIA)),
        ),
        ("DEMO_SANITARIA_CRITICA", (("PARAMEDICOS", NivelRiesgo.CRITICA),)),
        ("DEMO_LOGISTICA", (("AGUA", NivelRiesgo.BAJA),)),
    ):
        revision_id = _id(f"certificacion:{codigo}:1")
        revision = session.scalar(
            select(Certificacion).where(
                Certificacion.codigo == codigo,
                Certificacion.revision == 1,
            )
        )
        capacidades: dict[UUID, NivelRiesgo] = {}
        for capacidad_codigo, riesgo in alcances:
            capacidad = session.scalar(
                select(Capacidad).where(Capacidad.codigo == capacidad_codigo)
            )
            if capacidad is None or not capacidad.activa:
                raise ValueError("El catálogo demo requiere capacidades activas.")
            capacidades[capacidad.id] = riesgo
        if revision is None:
            revision = Certificacion(
                id=revision_id, codigo=codigo, revision=1, nombre=codigo, activa=False
            )
            session.add(revision)
            session.flush()
            session.add_all(
                [
                    CertificacionCapacidad(
                        certificacion_id=revision_id,
                        capacidad_id=capacidad_id,
                        riesgo_maximo=riesgo,
                    )
                    for capacidad_id, riesgo in capacidades.items()
                ]
            )
            session.flush()
            revision.activa = True
            session.flush()
        existentes = dict(
            session.execute(
                select(
                    CertificacionCapacidad.capacidad_id,
                    CertificacionCapacidad.riesgo_maximo,
                ).where(CertificacionCapacidad.certificacion_id == revision.id)
            ).all()
        )
        if revision.id != revision_id or existentes != capacidades:
            raise ValueError("La revisión demo existe con otra identidad o alcances.")
        revisiones[codigo] = revision_id
    for referencia, codigo, numero, dias_desde, dias_hasta, revocada in (
        ("ayuda-sin-fronteras", "DEMO_SANITARIA", "DEMO-VIGENTE", -1, 365, False),
        (
            "ayuda-sin-fronteras",
            "DEMO_SANITARIA_CRITICA",
            "DEMO-VENCIDA",
            -365,
            -1,
            False,
        ),
        ("ayuda-sin-fronteras", "DEMO_LOGISTICA", "DEMO-FUTURA", 30, 365, False),
        ("ayuda-sin-fronteras", "DEMO_SANITARIA", "DEMO-REVOCADA", -1, 365, True),
        ("red-medica-solidaria", "DEMO_SANITARIA", "DEMO-PENDIENTE", -1, 365, False),
    ):
        ong_id = _id(f"ong:{referencia}")
        ong = session.get(Ong, ong_id)
        if ong is None or ong.identificador_institucional != f"demo:{referencia}":
            raise ValueError("La ONG demo nacional no coincide.")
        credencial_id = _id(f"acreditacion:{referencia}:{numero}")
        existente = session.scalar(
            select(OngCertificacion).where(
                OngCertificacion.ong_id == ong_id,
                OngCertificacion.emisor == "Autoridad demo",
                OngCertificacion.numero_credencial == numero,
            )
        )
        if existente is not None:
            if (
                existente.id != credencial_id
                or existente.certificacion_id != revisiones[codigo]
            ):
                raise ValueError("La credencial demo ya existe con otro contenido.")
            continue
        if referencia == "ayuda-sin-fronteras" and ong.estado == EstadoOng.PENDIENTE:
            ong.estado = EstadoOng.HABILITADA
            ong.habilitada_en = datetime.now(UTC)
            ong.habilitada_por_id = admin_id
            ong.actualizado_en = ong.habilitada_en
            session.flush()
        credencial = OngCertificacion(
            id=credencial_id,
            ong_id=ong_id,
            certificacion_id=revisiones[codigo],
            emisor="Autoridad demo",
            numero_credencial=numero,
            vigente_desde=instante + timedelta(days=dias_desde),
            vigente_hasta=instante + timedelta(days=dias_hasta),
            registrada_por_id=admin_id,
        )
        session.add(credencial)
        session.flush()
        if revocada:
            credencial.estado = EstadoAcreditacion.REVOCADA
            credencial.revocada_en = datetime.now(UTC)
            credencial.revocada_por_id = admin_id
            credencial.motivo_revocacion = "Escenario demo de revocación"
            session.flush()
