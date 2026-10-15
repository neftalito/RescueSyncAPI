"""Credenciales nacionales separadas de las sesiones locales y de Bonita."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings

password_hash = PasswordHash.recommended()
_dummy_hash = password_hash.hash("cuenta-nacional-inexistente")


def generar_password_hash(password: str) -> str:
    """Genera un hash Argon2id sin conservar la contraseña."""

    return password_hash.hash(password)


def verificar_password(password: str, hash_guardado: str | None) -> bool:
    """Mantiene el costo de verificación para cuentas inexistentes."""

    try:
        return password_hash.verify(password, hash_guardado or _dummy_hash)
    except UnknownHashError:
        return False


def emitir_token(cuenta_id: UUID, *, version_credencial: int | None = None) -> str:
    """Emite un token limitado que sólo identifica la cuenta nacional."""

    settings = get_settings()
    ahora = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(cuenta_id),
            "iat": ahora,
            "exp": ahora
            + timedelta(
                seconds=300
                if version_credencial is not None
                else settings.jwt_access_seconds
            ),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            **({"ver": version_credencial} if version_credencial is not None else {}),
        },
        settings.clave_jwt,
        algorithm="HS256",
    )


@dataclass(frozen=True)
class IdentidadToken:
    cuenta_id: UUID
    version_credencial: int | None


def leer_token(token: str) -> IdentidadToken:
    """Verifica algoritmo fijo, firma, emisor, audiencia y claims obligatorios."""

    settings = get_settings()
    claims = jwt.decode(
        token,
        settings.clave_jwt,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "iat", "exp", "iss", "aud"]},
    )
    version = claims.get("ver")
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError("Versión de credencial inválida")
    return IdentidadToken(UUID(claims["sub"]), version)
