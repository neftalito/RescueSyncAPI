"""Contratos para cargas de demostración y vaciado de la base nacional."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from app.schemas.inventario import Codigo, Contrato, LoginRequest

LOGINS_YAAK = {
    "admin": "admin.yaak@example.org",
    "ong_a": "ong-a.yaak@example.org",
    "ong_b": "ong-b.yaak@example.org",
    "tecnica": "tecnica.yaak@example.org",
    "suspendida": "suspendida.yaak@example.org",
    "baja": "baja.yaak@example.org",
    "inactiva": "inactiva.yaak@example.org",
}


class IntegracionSeedYaak(LoginRequest):
    sistema_origen: Codigo
    password: SecretStr = Field(min_length=12, max_length=128)


class SeedYaakRequest(Contrato):
    confirmacion: Literal["BORRAR_Y_PREPARAR_YAAK"]
    run_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]*$")
    integracion: IntegracionSeedYaak

    @model_validator(mode="after")
    def integrar_login_distinto(self) -> Self:
        """Rechaza colisiones conocidas antes de vaciar cualquier tabla."""
        if self.integracion.identificador_login in LOGINS_YAAK.values():
            raise ValueError(
                "El login de integración debe ser distinto de los de Yaak."
            )
        return self


class ReferenciasSeedYaak(Contrato):
    admin_id: UUID
    integracion_id: UUID
    ong_a_id: UUID
    ong_b_id: UUID
    ong_tecnica_id: UUID
    ong_suspendida_id: UUID
    ong_baja_id: UUID
    capacidad_personal_id: UUID
    capacidad_agua_id: UUID
    capacidad_inactiva_id: UUID
    personal_a_id: UUID
    personal_b_id: UUID
    agua_a_id: UUID
    recurso_inactivo_id: UUID
    recurso_capacidad_inactiva_id: UUID
    personal_suspendida_id: UUID
    personal_baja_id: UUID


class SeedMasivoRequest(Contrato):
    seed: int = Field(default=2026, ge=0, le=2_147_483_647, strict=True)
    ongs: int = Field(default=1000, ge=1, le=10_000, strict=True)
    recursos_por_ong: int = Field(default=20, ge=4, le=1000, strict=True)
    batch_size: int = Field(default=250, ge=1, le=1000, strict=True)

    @model_validator(mode="after")
    def limitar_volumen(self) -> Self:
        """Acota el trabajo sincrónico de una petición a 200.000 recursos."""
        if self.ongs * self.recursos_por_ong > 200_000:
            raise ValueError("La carga HTTP admite hasta 200.000 recursos.")
        return self


class MantenimientoResponse(Contrato):
    operacion: Literal["seed", "seed-masivo", "seed-yaak", "flush"]
    mensaje: str


class SeedMasivoResponse(MantenimientoResponse):
    ongs: int
    cuentas: int
    recursos: int


class SeedYaakResponse(MantenimientoResponse):
    run_id: str
    unidades: int
    capacidades: int
    ongs: int
    cuentas: int
    recursos: int
    proyectos: int
    compromisos: int
    sistema_origen: str
    identificadores_login: dict[str, str]
    referencias: ReferenciasSeedYaak
