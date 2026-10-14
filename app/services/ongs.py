"""Selección institucional y filtros sobre competencias, independientes del stock."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import NivelRiesgo
from app.schemas.ongs import (
    CodigoMotivoPerfil,
    MotivoPerfilResponse,
    OngHabilitadaResponse,
    OngsHabilitadasResponse,
)
from app.services.certificaciones import consultar_certificaciones_ongs


def listar_ongs_habilitadas(
    session: Session,
    *,
    capacidad_id: UUID | None = None,
    nivel_riesgo: NivelRiesgo | None = None,
    ahora: datetime | None = None,
) -> OngsHabilitadasResponse:
    """Ambos filtros coinciden en una capacidad; se conserva el perfil completo."""
    evaluado_en = ahora or datetime.now(UTC)
    perfiles = consultar_certificaciones_ongs(
        session, solo_habilitadas=True, ahora=evaluado_en
    )
    ongs: list[OngHabilitadaResponse] = []
    for nombre, perfil in perfiles:
        if (capacidad_id is not None or nivel_riesgo is not None) and not any(
            (capacidad_id is None or capacidad.capacidad_id == capacidad_id)
            and (
                nivel_riesgo is None
                or nivel_riesgo in capacidad.niveles_riesgo_permitidos
            )
            for capacidad in perfil.capacidades_habilitadas
        ):
            continue
        ongs.append(
            OngHabilitadaResponse(
                ong_id=perfil.ong_id,
                nombre=nombre,
                estado_ong=perfil.estado_ong,
                capacidades_habilitadas=perfil.capacidades_habilitadas,
                motivos_perfil=(
                    []
                    if perfil.capacidades_habilitadas
                    else [
                        MotivoPerfilResponse(
                            codigo=CodigoMotivoPerfil.SIN_COMPETENCIAS_VIGENTES,
                            mensaje=(
                                "La habilitación institucional no acredita "
                                "capacidades operativas vigentes."
                            ),
                        )
                    ]
                ),
            )
        )
    return OngsHabilitadasResponse(evaluado_en=evaluado_en, ongs=ongs)
