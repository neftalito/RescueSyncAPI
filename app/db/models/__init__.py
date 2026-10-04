"""Registra toda la metadata nacional al importarse desde aplicación o Alembic."""

from app.db.models.catalogos import (
    Capacidad,
    Certificacion,
    CertificacionCapacidad,
    OngCertificacion,
)
from app.db.models.compromisos import (
    Compromiso,
    CompromisoItem,
    OperacionIdempotente,
    Proyecto,
)
from app.db.models.enums import (
    EstadoAcreditacion,
    EstadoCompromiso,
    EstadoOng,
    EstadoProyecto,
    NivelRiesgo,
    RolNacional,
    TipoOperacion,
    TipoRecurso,
)
from app.db.models.identidad import Cuenta, Ong, SistemaOrigen
from app.db.models.recursos import Recurso

__all__ = [
    "Capacidad",
    "Certificacion",
    "CertificacionCapacidad",
    "Compromiso",
    "CompromisoItem",
    "Cuenta",
    "EstadoAcreditacion",
    "EstadoCompromiso",
    "EstadoOng",
    "EstadoProyecto",
    "NivelRiesgo",
    "Ong",
    "OngCertificacion",
    "OperacionIdempotente",
    "Proyecto",
    "Recurso",
    "RolNacional",
    "SistemaOrigen",
    "TipoOperacion",
    "TipoRecurso",
]
