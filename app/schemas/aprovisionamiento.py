"""Alta técnica de una institución desde un backend de confianza."""

from uuid import UUID

from pydantic import EmailStr, Field, SecretStr

from app.schemas.inventario import Contrato, Nombre, OngResponse


class AprovisionamientoRequest(Contrato):
    nombre: Nombre
    email_contacto: EmailStr | None = None
    password: SecretStr = Field(min_length=32, max_length=128)


class AprovisionamientoResponse(Contrato):
    ong: OngResponse
    cuenta_id: UUID
    identificador_login: str
