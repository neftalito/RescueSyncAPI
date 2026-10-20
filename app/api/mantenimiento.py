"""Autenticación independiente de las identidades que el flush puede eliminar."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader

from app.core.config import get_settings

_password = APIKeyHeader(
    name="X-DB-Maintenance-Password",
    scheme_name="DBMaintenancePassword",
    auto_error=False,
    description=(
        "Contraseña DB_MAINTENANCE_PASSWORD del entorno de la API. Autoriza seeds "
        "y flush incluso en producción. Independiente del JWT y de las cuentas "
        "de la base. Enviar sólo por HTTPS fuera del entorno local; nunca en URL. "
        "Sin configuración, los endpoints están deshabilitados (403)."
    ),
)


def autorizar_mantenimiento(
    password: Annotated[str | None, Depends(_password)],
) -> None:
    """Compara bytes en tiempo constante sin registrar ni devolver el secreto."""
    esperada = get_settings().db_maintenance_password
    if esperada is None:
        raise HTTPException(
            403, "El mantenimiento de base de datos está deshabilitado."
        )
    if password is None or not compare_digest(
        password.encode("utf-8"), esperada.get_secret_value().encode("utf-8")
    ):
        raise HTTPException(401, "La contraseña de mantenimiento no es válida.")
