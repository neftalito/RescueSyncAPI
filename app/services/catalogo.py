"""Administra capacidades sin permitir altas o cambios de unidades por HTTP."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Capacidad, Unidad
from app.schemas.catalogo import CapacidadCreate, UnidadResponse
from app.schemas.inventario import CapacidadResponse


class CapacidadDuplicadaError(ValueError):
    """El código identifica una capacidad ya registrada."""


class UnidadNoDisponibleError(ValueError):
    """La unidad solicitada no pertenece al catálogo predefinido."""


def listar_unidades(session: Session) -> list[UnidadResponse]:
    """Devuelve las unidades instaladas por migraciones, ordenadas por nombre."""
    return [
        UnidadResponse(codigo=unidad.codigo, nombre=unidad.nombre)
        for unidad in session.scalars(select(Unidad).order_by(Unidad.nombre))
    ]


def crear_capacidad(session: Session, datos: CapacidadCreate) -> CapacidadResponse:
    """Crea una capacidad activa usando una unidad existente y un código único."""
    if session.get(Unidad, datos.unidad) is None:
        raise UnidadNoDisponibleError("Seleccioná una unidad existente del catálogo.")
    capacidad = Capacidad(**datos.model_dump())
    try:
        session.add(capacidad)
        session.flush()
        respuesta = CapacidadResponse(
            id=capacidad.id,
            codigo=capacidad.codigo,
            nombre=capacidad.nombre,
            tipo=capacidad.tipo,
            unidad=capacidad.unidad,
            admite_fracciones=capacidad.admite_fracciones,
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise CapacidadDuplicadaError(
            "Ya existe una capacidad con ese código."
        ) from error
    return respuesta
