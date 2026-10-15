from functools import lru_cache
from secrets import token_urlsafe
from typing import Literal, Self

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from app.core.cors import normalizar_origenes


class Settings(BaseSettings):
    """Carga y valida la configuración del proceso desde el entorno."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "RescueSync API Nacional"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    port: int = Field(default=8000, ge=1, le=65_535)
    cors_origins: list[str] = ["http://localhost:5173"]

    database_url_override: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
    )
    postgres_host: str = "db"
    postgres_port: int = Field(default=5432, ge=1, le=65_535)
    postgres_db: str = "rescuesync_nacional"
    postgres_user: str = "rescuesync_nacional"
    postgres_password: SecretStr = SecretStr("rescuesync_nacional_dev")
    jwt_secret: SecretStr | None = None
    jwt_issuer: str = "rescuesync-nacional"
    jwt_audience: str = "rescuesync"
    jwt_access_seconds: int = Field(default=1800, ge=60, le=3600)
    operacion_lock_timeout_ms: int = Field(default=5000, ge=1, le=60_000)
    operacion_statement_timeout_ms: int = Field(default=15000, ge=1, le=120_000)
    _jwt_secret_desarrollo: str = PrivateAttr(default_factory=lambda: token_urlsafe(48))

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def normalizar_jwt_secret(cls, valor: object) -> object:
        return None if valor == "" else valor

    @model_validator(mode="after")
    def validar_jwt_secret(self) -> Self:
        """Exige una clave propia en producción y suficiente entropía configurada."""

        if self.app_env == "production" and self.jwt_secret is None:
            raise ValueError("JWT_SECRET es obligatorio en producción")
        if self.jwt_secret is not None and len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres")
        return self

    @property
    def clave_jwt(self) -> str:
        """Usa una clave efímera sólo fuera de producción si no se configura."""

        return (
            self.jwt_secret.get_secret_value()
            if self.jwt_secret is not None
            else self._jwt_secret_desarrollo
        )

    @field_validator("database_url_override", mode="before")
    @classmethod
    def normalizar_database_url(cls, value: object) -> object:
        """Selecciona explícitamente el driver Psycopg para URLs de proveedores."""

        if value in {None, ""}:
            return None
        if not isinstance(value, str):
            return value
        if value.startswith("postgresql+psycopg://"):
            return value
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        raise ValueError("DATABASE_URL debe utilizar PostgreSQL")

    @field_validator("cors_origins")
    @classmethod
    def validar_cors_origins(cls, values: list[str]) -> list[str]:
        """Valida la lista explícita recibida desde CORS_ORIGINS."""
        return normalizar_origenes(values)

    @property
    def sqlalchemy_database_uri(self) -> str:
        """Devuelve la URL de SQLAlchemy sin registrar la contraseña."""

        if self.database_url_override is not None:
            return self.database_url_override

        url = URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    """Comparte una configuración validada durante la vida del proceso."""

    return Settings()
