from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "API nacional para gestionar organizaciones, certificaciones y recursos "
        "de la red RescueSync."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
