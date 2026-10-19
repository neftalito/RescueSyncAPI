"""Estados y roles persistidos por el sistema nacional."""

from enum import StrEnum


class RolNacional(StrEnum):
    ADMIN_NACIONAL = "ADMIN_NACIONAL"
    ONG = "ONG"
    INTEGRACION = "INTEGRACION"


class PropositoCuenta(StrEnum):
    PERSONAL = "PERSONAL"
    TECNICA_ONG = "TECNICA_ONG"


class EstadoOng(StrEnum):
    PENDIENTE = "PENDIENTE"
    HABILITADA = "HABILITADA"
    SUSPENDIDA = "SUSPENDIDA"
    BAJA = "BAJA"


class TipoRecurso(StrEnum):
    PERSONAL = "PERSONAL"
    VEHICULO = "VEHICULO"
    EQUIPAMIENTO = "EQUIPAMIENTO"
    SUMINISTRO = "SUMINISTRO"


class NivelRiesgo(StrEnum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class EstadoAcreditacion(StrEnum):
    OTORGADA = "OTORGADA"
    REVOCADA = "REVOCADA"


class EstadoProyecto(StrEnum):
    ABIERTO = "ABIERTO"
    TERMINADO = "TERMINADO"


class EstadoCompromiso(StrEnum):
    ACTIVO = "ACTIVO"
    LIBERADO = "LIBERADO"


class TipoOperacion(StrEnum):
    COMPROMETER = "COMPROMETER"
    LIBERAR = "LIBERAR"
    CERRAR_PROYECTO = "CERRAR_PROYECTO"
