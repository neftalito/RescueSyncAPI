from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.cors import AplicacionConCORS

settings = get_settings()

app = AplicacionConCORS(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "API nacional para gestionar organizaciones, certificaciones y recursos "
        "de la red RescueSync.\n\n"
        "**Autenticación:** POST /api/v1/login recibe identificadorLogin y password; "
        "usar access_token como Authorization: Bearer <token>. Los roles vigentes "
        "son ONG, ADMIN_NACIONAL e INTEGRACION; cada operación explica su acceso. "
        "Los ejemplos son ficticios y sus UUID deben reemplazarse por mappings "
        "reales. IDs locales y nacionales no son intercambiables.\n\n"
        "**Flujo distribuido:** Bonita obtiene el snapshot cerrado del backend "
        "local y llama a validaciones. La evaluación es transitoria, no persiste "
        "ofertas y no reserva stock. Comprometer revalida permisos, competencias "
        "y disponibilidad bajo locks PostgreSQL, con confirmación atómica. "
        "Compromiso, edición de inventario y liberación comparten locking. "
        "No se mantienen locks durante llamadas HTTP.\n\n"
        "**Idempotencia y cierre:** conservar Idempotency-Key ante timeouts o 503; "
        "el commit puede haber ocurrido. Misma clave y contenido reproducen la "
        "confirmación; contenido distinto da 409. Liberar afecta sólo el compromiso "
        "de esa ONG y conserva historial. Cerrar exige cero compromisos activos "
        "y comparte el lock de proyecto con comprometer.\n\n"
        "**Contratos:** camelCase para DTO de integración; cantidades nacionales "
        "exactas como strings decimales. Errores JSON con detail seguro: 401 "
        "autenticación, 403 permisos, 404 referencia inexistente, 409 conflicto, "
        "422 entrada inválida, 500 inconsistencia, 503 fallo temporal. "
        "El frontend consume su backend local, no esta API directamente."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.origenes_cors = tuple(settings.cors_origins)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.exception_handler(RequestValidationError)
async def error_validacion(
    _request: Request, _error: RequestValidationError
) -> JSONResponse:
    """Evita exponer entradas sensibles en el detalle de errores Pydantic."""

    return JSONResponse(
        status_code=422,
        content={
            "detail": "Los datos enviados no son válidos. Revisá campos y cantidades."
        },
    )


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """Publica enlaces de descubrimiento sin exponer información sensible."""

    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": f"{settings.api_v1_prefix}/health",
    }
