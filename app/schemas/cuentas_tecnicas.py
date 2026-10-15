"""Archivo de intercambio administrativo; nunca se devuelve por HTTP."""

from uuid import UUID

from app.schemas.inventario import LoginRequest


class CredencialTecnica(LoginRequest):
    cuenta_id: UUID
    ong_id: UUID
