"""Crea institución y cuenta técnica en una transacción repetible por emisor."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import generar_password_hash, verificar_password
from app.db.models import (
    Cuenta,
    EstadoOng,
    Ong,
    PropositoCuenta,
    RolNacional,
    SistemaOrigen,
)
from app.db.models.aprovisionamiento import AprovisionamientoOng
from app.schemas.aprovisionamiento import (
    AprovisionamientoRequest,
    AprovisionamientoResponse,
)
from app.schemas.inventario import OngResponse


class AprovisionamientoDenegadoError(ValueError):
    """El emisor o la identidad institucional ya no pueden operar."""


class AprovisionamientoConflictivoError(ValueError):
    """La referencia o el identificador pertenecen a otra operación."""


def aprovisionar_ong(
    session: Session, cuenta_id: UUID, referencia: UUID, datos: AprovisionamientoRequest
) -> AprovisionamientoResponse:
    """Serializa por emisor; un reintento nunca rota ni recupera secretos."""
    cuenta_emisora = session.scalar(
        select(Cuenta)
        .where(Cuenta.id == cuenta_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        cuenta_emisora is None
        or not cuenta_emisora.activa
        or cuenta_emisora.rol != RolNacional.INTEGRACION
        or cuenta_emisora.sistema_origen_id is None
    ):
        raise AprovisionamientoDenegadoError(
            "Se requiere una cuenta de integración activa."
        )
    origen = session.scalar(
        select(SistemaOrigen)
        .where(SistemaOrigen.id == cuenta_emisora.sistema_origen_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if origen is None or not origen.activo:
        raise AprovisionamientoDenegadoError("El sistema de origen no está activo.")
    payload = datos.model_dump(mode="json", by_alias=True)
    payload["password"] = datos.password.get_secret_value()
    huella = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    registro = session.get(AprovisionamientoOng, (origen.id, referencia))
    try:
        if registro is None:
            ong = Ong(
                nombre=datos.nombre,
                identificador_institucional=f"rs:{origen.id.hex}:{referencia.hex}",
                email_contacto=str(datos.email_contacto)
                if datos.email_contacto
                else None,
            )
            session.add(ong)
            session.flush()
            cuenta = Cuenta(
                identificador_login=f"tecnica-ong-{ong.id}",
                password_hash=generar_password_hash(datos.password.get_secret_value()),
                rol=RolNacional.ONG,
                proposito=PropositoCuenta.TECNICA_ONG,
                ong_id=ong.id,
                version_credencial=1,
            )
            session.add(cuenta)
            session.add(
                AprovisionamientoOng(
                    sistema_origen_id=origen.id,
                    referencia_local=referencia,
                    ong_id=ong.id,
                    huella=huella,
                )
            )
            session.flush()
        else:
            if registro.huella != huella:
                raise AprovisionamientoConflictivoError(
                    "La referencia ya se usó con otros datos."
                )
            ong = session.get(Ong, registro.ong_id)
            cuenta = session.scalar(
                select(Cuenta).where(
                    Cuenta.ong_id == registro.ong_id,
                    Cuenta.proposito == PropositoCuenta.TECNICA_ONG,
                )
            )
            if (
                ong is None
                or ong.estado in {EstadoOng.BAJA, EstadoOng.SUSPENDIDA}
                or cuenta is None
                or not cuenta.activa
                or not verificar_password(
                    datos.password.get_secret_value(), cuenta.password_hash
                )
            ):
                raise AprovisionamientoDenegadoError(
                    "El acceso institucional requiere revisión."
                )
        respuesta = AprovisionamientoResponse(
            ong=OngResponse(id=ong.id, nombre=ong.nombre, estado=ong.estado),
            cuenta_id=cuenta.id,
            identificador_login=cuenta.identificador_login,
        )
        session.commit()
        return respuesta
    except IntegrityError as error:
        session.rollback()
        raise AprovisionamientoConflictivoError(
            "El identificador institucional ya está registrado; "
            "requiere vinculación verificada."
        ) from error
