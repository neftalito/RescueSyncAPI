"""Autoriza una instalación registrada sin confiar en el emisor del payload."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Cuenta, RolNacional, SistemaOrigen


class EmisorDenegadoError(PermissionError):
    """La cuenta no representa una instalación autorizada para esta operación."""


class EmisorNoEncontradoError(LookupError):
    """La administración solicitó una instalación nacional inexistente."""


def autorizar_emisor(session: Session, cuenta: Cuenta, codigo: str) -> SistemaOrigen:
    """Integración opera su emisor; administración debe seleccionarlo explícitamente."""
    if cuenta.rol not in {RolNacional.ADMIN_NACIONAL, RolNacional.INTEGRACION}:
        raise EmisorDenegadoError("Necesitás una cuenta técnica o administrativa.")
    origen = session.scalar(select(SistemaOrigen).where(SistemaOrigen.codigo == codigo))
    if cuenta.rol == RolNacional.INTEGRACION and (
        origen is None or origen.id != cuenta.sistema_origen_id
    ):
        raise EmisorDenegadoError("La cuenta no representa ese sistema de origen.")
    if origen is None:
        raise EmisorNoEncontradoError("El sistema de origen no existe.")
    if not origen.activo:
        raise EmisorDenegadoError("El sistema de origen no está activo.")
    return origen
