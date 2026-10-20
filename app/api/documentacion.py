"""Respuestas y ejemplos públicos compartidos por Swagger y la exportación T40."""

from app.schemas.inventario import ErrorResponse

ERRORES = {
    401: (
        "Login incorrecto o JWT ausente, inválido o expirado; autenticar nuevamente.",
        "La credencial nacional no es válida o expiró.",
    ),
    403: (
        "Cuenta, ONG o emisor sin permisos vigentes para la operación o el destino.",
        "No tenés permisos para acceder a ese inventario.",
    ),
    404: (
        "La referencia solicitada no existe en el sistema nacional.",
        "El recurso nacional no existe.",
    ),
    409: (
        "Conflicto de estado, stock, versión, unicidad o clave idempotente.",
        "La operación entra en conflicto con el estado actual.",
    ),
    422: (
        "Campos, referencias, unidades o cantidades inválidos. El detalle es seguro.",
        "Los datos enviados no son válidos. Revisá campos y cantidades.",
    ),
    500: (
        "Inconsistencia interna; no se exponen SQL ni detalles de infraestructura.",
        "El inventario nacional no es consistente.",
    ),
    503: (
        "Fallo temporal de base de datos. En escrituras idempotentes, reintentar "
        "con la misma Idempotency-Key: el resultado puede haberse confirmado.",
        "Operación temporalmente no disponible. Reintentá con la misma clave.",
    ),
}


def respuestas(
    *codigos: int,
    ejemplo: object,
    exito: int = 200,
    detalles: dict[int, str] | None = None,
) -> dict[int | str, dict[str, object]]:
    """Agrega ejemplos sin reemplazar el modelo de éxito declarado por la ruta."""
    resultado: dict[int | str, dict[str, object]] = {
        exito: {
            "description": "Operación confirmada correctamente.",
            "content": {"application/json": {"example": ejemplo}},
        }
    }
    for codigo in codigos:
        descripcion, detalle = ERRORES[codigo]
        detalle = (detalles or {}).get(codigo, detalle)
        resultado[codigo] = {
            "model": ErrorResponse,
            "description": descripcion,
            "content": {"application/json": {"example": {"detail": detalle}}},
        }
    return resultado
