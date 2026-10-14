from fastapi import APIRouter

from app.api.routes import certificaciones, health, inventario
from app.api.routes.disponibilidad import router as disponibilidad_router

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(disponibilidad_router, tags=["disponibilidad global"])
api_router.include_router(inventario.router, tags=["cuentas e inventario"])
api_router.include_router(certificaciones.router, tags=["certificaciones"])
