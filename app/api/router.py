from fastapi import APIRouter

from app.api.routes import (
    aprovisionamiento,
    catalogo,
    compromisos,
    health,
    inventario,
    mantenimiento,
    ongs,
    proyectos,
    validaciones,
)

api_router = APIRouter()
api_router.include_router(mantenimiento.router, tags=["mantenimiento de base de datos"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(catalogo.router, tags=["catálogo nacional"])
api_router.include_router(inventario.router, tags=["cuentas e inventario"])
api_router.include_router(ongs.router, tags=["ONGs y perfiles informativos"])
api_router.include_router(validaciones.router, tags=["consistencia e inventario"])
api_router.include_router(compromisos.router, tags=["compromisos nacionales"])
api_router.include_router(proyectos.router, tags=["proyectos nacionales"])

api_router.include_router(
    aprovisionamiento.router, tags=["aprovisionamiento institucional"]
)
