from fastapi import APIRouter

from app.api.routes import health, inventario

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(inventario.router, tags=["cuentas e inventario"])
