"""Directorio operativo y análisis de recursos declarados con autorización JWT."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response

from app.api import ejemplos
from app.api.dependencies import CuentaEvaluacion, DbEvaluacion, autorizar_inventario
from app.api.documentacion import respuestas
from app.schemas.perfiles import DirectorioOngs, PerfilCompetencia
from app.services.perfiles import consultar_perfiles

router = APIRouter()


@router.get(
    "/ongs",
    response_model=DirectorioOngs,
    summary="Consultar ONG activas y sus recursos declarados",
    description=(
        "Acceso: ONG, administración o integración. Incluye ONG sin "
        "inventario. El filtro por capacidad no reserva recursos."
    ),
    responses=respuestas(401, 403, 422, ejemplo=ejemplos.DIRECTORIO_ONGS),
)
def directorio(
    session: DbEvaluacion,
    cuenta: CuentaEvaluacion,
    response: Response,
    capacidad_id: Annotated[
        UUID | None,
        Query(
            alias="capacidadId",
            description="Capacidad declarada para filtrar el directorio.",
            examples=[ejemplos.CAPACIDAD_ID],
        ),
    ] = None,
) -> DirectorioOngs:
    response.headers["Cache-Control"] = "no-store"
    ahora = datetime.now(UTC)
    perfiles = consultar_perfiles(session, solo_activas=True, ahora=ahora)
    return DirectorioOngs(
        evaluado_en=ahora,
        ongs=[
            p
            for p in perfiles.values()
            if capacidad_id is None
            or any(c.capacidad_id == capacidad_id for c in p.capacidades_declaradas)
        ],
    )


@router.get(
    "/ongs/{ong_id}/perfil-competencia",
    response_model=PerfilCompetencia,
    summary="Analizar los recursos declarados de una ONG",
    description=(
        "Acceso: ONG propia, administración o integración. "
        "Perfil informativo sin límites por riesgo."
    ),
    responses=respuestas(401, 403, 404, 422, ejemplo=ejemplos.PERFIL_COMPETENCIA),
)
def perfil_competencia(
    ong_id: Annotated[
        UUID,
        Path(
            description="Identificador nacional de la ONG.", examples=[ejemplos.ONG_ID]
        ),
    ],
    session: DbEvaluacion,
    cuenta: CuentaEvaluacion,
    response: Response,
) -> PerfilCompetencia:
    autorizar_inventario(cuenta, ong_id, escritura=False)
    response.headers["Cache-Control"] = "no-store"
    perfil = consultar_perfiles(session, ong_ids={ong_id}).get(ong_id)
    if perfil is None:
        raise HTTPException(404, "La ONG nacional no existe.")
    return perfil
