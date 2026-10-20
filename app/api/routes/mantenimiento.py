"""Endpoints operativos autorizados por la contraseña de mantenimiento."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import Db
from app.api.documentacion import respuestas
from app.api.mantenimiento import autorizar_mantenimiento
from app.schemas.mantenimiento import (
    MantenimientoResponse,
    SeedMasivoRequest,
    SeedMasivoResponse,
    SeedYaakRequest,
    SeedYaakResponse,
)
from app.scripts.seed_masivo import ConfiguracionSeed
from app.scripts.seed_yaak import respuesta_seed_yaak
from app.services import mantenimiento

router = APIRouter(
    prefix="/mantenimiento",
    dependencies=[Depends(autorizar_mantenimiento)],
)

_ERRORES = {
    401: "La contraseña de mantenimiento no es válida.",
    403: "El mantenimiento de base de datos está deshabilitado.",
    409: "El seed entra en conflicto con las identidades o el catálogo existentes.",
    503: "No se pudo confirmar el mantenimiento. Revisá el estado antes de reintentar.",
}
_ACCESO = (
    "Acceso: contraseña DB_MAINTENANCE_PASSWORD en X-DB-Maintenance-Password, "
    "independiente del JWT; admite producción. Sin contraseña configurada: 403; "
    "ausente o incorrecta: 401. Operación sincrónica, transaccional y serializada "
    "con los otros endpoints de mantenimiento. Responde sólo después del commit. "
)
_SEED_MASIVO_PREDETERMINADO = SeedMasivoRequest()
_EJEMPLO_YAAK = {
    "confirmacion": "BORRAR_Y_PREPARAR_YAAK",
    "runId": "YAAK2026",
    "integracion": {
        "identificadorLogin": "integracion-rescuesync",
        "password": "demo-integracion-yaak-2026-123456",
        "sistemaOrigen": "rescuesync-local",
    },
}


@router.post(
    "/seed-yaak",
    response_model=SeedYaakResponse,
    summary="Vaciar la base y preparar el escenario de pruebas de Yaak",
    description=_ACCESO
    + (
        "DESTRUCTIVO: hace flush de TODAS las tablas nacionales y carga sólo el "
        "escenario Yaak, en una transacción. Requiere confirmación literal y "
        "credenciales de integración de 12–128 caracteres para recrear el emisor. "
        "Prepara catálogo, cinco ONGs, ocho cuentas y siete recursos; cero "
        "proyectos o compromisos. Datos deterministas, sin Faker. Los UUID "
        "dependen de runId. Nunca devuelve contraseñas. Repetir reinicia todo "
        "el escenario, incluso con el mismo runId. Ejecutar sin tráfico de "
        "negocio. Si falla la carga, el flush también se revierte. Ante timeout "
        "verificar el resultado antes de repetir."
    ),
    responses=respuestas(
        401,
        403,
        422,
        503,
        ejemplo=respuesta_seed_yaak(
            SeedYaakRequest.model_validate(_EJEMPLO_YAAK)
        ).model_dump(mode="json", by_alias=True),
        detalles=_ERRORES,
    ),
)
def seed_yaak(
    datos: Annotated[SeedYaakRequest, Body(examples=[_EJEMPLO_YAAK])],
    session: Db,
) -> SeedYaakResponse:
    try:
        return mantenimiento.preparar_yaak(session, datos)
    except SQLAlchemyError as error:
        raise HTTPException(503, _ERRORES[503]) from error


@router.post(
    "/seed",
    response_model=MantenimientoResponse,
    summary="Cargar el seed normal nacional",
    description=_ACCESO
    + (
        "Agrega dos ONGs, sus cuentas personales y técnicas, cuatro recursos y el "
        "administrador demo. Restaura el catálogo base faltante, incluso tras "
        "flush. Repetir agrega sólo faltantes; no rota credenciales ni restaura stock."
    ),
    responses=respuestas(
        401,
        403,
        409,
        503,
        ejemplo={"operacion": "seed", "mensaje": "Seed nacional confirmado."},
        detalles=_ERRORES,
    ),
)
def seed(session: Db) -> MantenimientoResponse:
    try:
        mantenimiento.cargar_seed(session)
    except ValueError as error:
        raise HTTPException(409, _ERRORES[409]) from error
    except SQLAlchemyError as error:
        raise HTTPException(503, _ERRORES[503]) from error
    return MantenimientoResponse(operacion="seed", mensaje="Seed nacional confirmado.")


@router.post(
    "/seed-masivo",
    response_model=SeedMasivoResponse,
    summary="Cargar el seed masivo nacional",
    description=_ACCESO
    + (
        "Cuerpo opcional: por defecto 1.000 ONGs, 2.001 cuentas y 20.000 recursos "
        "(seed=2026). Hasta 200.000 recursos por petición. Restaura el catálogo "
        "base faltante; devuelve conteos nuevos, sin contar ese catálogo. Repetir "
        "con el mismo seed agrega sólo faltantes, sin rotar credenciales ni stock."
    ),
    responses=respuestas(
        401,
        403,
        409,
        422,
        503,
        ejemplo={
            "operacion": "seed-masivo",
            "mensaje": "Seed masivo confirmado.",
            "ongs": 1000,
            "cuentas": 2001,
            "recursos": 20000,
        },
        detalles=_ERRORES,
    ),
)
def seed_masivo(
    session: Db,
    datos: Annotated[
        SeedMasivoRequest,
        Body(
            examples=[
                {"seed": 2026, "ongs": 1000, "recursosPorOng": 20, "batchSize": 250}
            ]
        ),
    ] = _SEED_MASIVO_PREDETERMINADO,
) -> SeedMasivoResponse:
    try:
        resultado = mantenimiento.cargar_seed_masivo(
            session, ConfiguracionSeed(**datos.model_dump())
        )
    except ValueError as error:
        raise HTTPException(409, _ERRORES[409]) from error
    except SQLAlchemyError as error:
        raise HTTPException(503, _ERRORES[503]) from error
    return SeedMasivoResponse(
        operacion="seed-masivo",
        mensaje="Seed masivo confirmado.",
        ongs=resultado.ongs,
        cuentas=resultado.cuentas,
        recursos=resultado.recursos,
    )


@router.post(
    "/flush",
    response_model=MantenimientoResponse,
    summary="Borrar todos los datos de la base nacional",
    description=_ACCESO
    + (
        "Elimina TODAS las filas de las tablas nacionales: cuentas, ONGs, "
        "integraciones, inventario, proyectos, compromisos, historial y catálogos. "
        "Conserva tablas, restricciones y alembic_version. No repuebla datos; "
        "un seed posterior restaura el catálogo y su escenario. No modifica "
        "RescueSync ni Bonita. Ejecutar sin tráfico de negocio. Ante timeout, "
        "verificar el resultado antes de repetir: el commit puede haber ocurrido."
    ),
    responses=respuestas(
        401,
        403,
        503,
        ejemplo={"operacion": "flush", "mensaje": "Base nacional vaciada."},
        detalles=_ERRORES,
    ),
)
def flush(session: Db) -> MantenimientoResponse:
    try:
        mantenimiento.vaciar_base(session)
    except SQLAlchemyError as error:
        raise HTTPException(503, _ERRORES[503]) from error
    return MantenimientoResponse(operacion="flush", mensaje="Base nacional vaciada.")
