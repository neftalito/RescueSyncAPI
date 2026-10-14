from fastapi import APIRouter

from app.api.routes import (
    certificaciones,
    compromisos,
    health,
    inventario,
    ongs,
    validaciones,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(inventario.router, tags=["cuentas e inventario"])
api_router.include_router(certificaciones.router, tags=["certificaciones"])
api_router.include_router(ongs.router, tags=["ONGs habilitadas"])
api_router.include_router(validaciones.router, tags=["validación de competencias"])
api_router.include_router(compromisos.router, tags=["compromisos nacionales"])
