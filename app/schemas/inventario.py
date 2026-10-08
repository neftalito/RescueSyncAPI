"""Contratos del inventario y la conexión nacional; cantidades sin floats."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)
from pydantic.alias_generators import to_camel

from app.db.models.enums import EstadoOng, RolNacional, TipoRecurso

type Nombre = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
type Codigo = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
type Cantidad = Annotated[
    Decimal, Field(ge=0, max_digits=14, decimal_places=3, allow_inf_nan=False)
]


class Contrato(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(Contrato):
    identificador_login: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("identificador_login")
    @classmethod
    def normalizar_login(cls, valor: str) -> str:
        return valor.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CuentaResponse(Contrato):
    id: UUID
    rol: RolNacional
    ong_id: UUID | None


class OngCreate(LoginRequest):
    nombre: Nombre
    identificador_institucional: Codigo
    email_contacto: EmailStr
    password: SecretStr = Field(min_length=8, max_length=128)

    @field_validator("identificador_institucional")
    @classmethod
    def normalizar_identificador(cls, valor: str) -> str:
        return valor.lower()


class OngResponse(Contrato):
    id: UUID
    nombre: str
    estado: EstadoOng


class CapacidadResponse(Contrato):
    id: UUID
    codigo: str
    nombre: str
    tipo: TipoRecurso
    unidad: str
    admite_fracciones: bool


class RecursoCreate(Contrato):
    capacidad_id: UUID
    codigo_interno: Codigo
    nombre: Nombre
    cantidad_total: Cantidad


class RecursoUpdate(Contrato):
    cantidad_total: Cantidad
    actualizado_en: AwareDatetime


class RecursoResponse(Contrato):
    id: UUID
    ong_id: UUID
    capacidad_id: UUID
    codigo_interno: str
    nombre: str
    capacidad: str
    unidad: str
    admite_fracciones: bool
    cantidad_total: Decimal
    cantidad_comprometida: Decimal
    cantidad_disponible: Decimal
    activo: bool
    actualizado_en: datetime
