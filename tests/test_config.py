import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def aislar_configuracion_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita que las variables del host o de CI alteren pruebas de configuración."""

    for name, field in Settings.model_fields.items():
        variable = field.validation_alias or name
        if isinstance(variable, str):
            monkeypatch.delenv(variable.upper(), raising=False)
            monkeypatch.delenv(variable.lower(), raising=False)


def test_configuracion_por_defecto_construye_url_psycopg() -> None:
    settings = Settings(_env_file=None)

    assert settings.port == 8000
    assert settings.sqlalchemy_database_uri == (
        "postgresql+psycopg://rescuesync_nacional:"
        "rescuesync_nacional_dev@db:5432/rescuesync_nacional"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgres://user:secret@host:5432/database",
            "postgresql+psycopg://user:secret@host:5432/database",
        ),
        (
            "postgresql://user:secret@host:5432/database",
            "postgresql+psycopg://user:secret@host:5432/database",
        ),
        (
            "postgresql+psycopg://user:secret@host:5432/database",
            "postgresql+psycopg://user:secret@host:5432/database",
        ),
    ],
)
def test_database_url_de_proveedor_se_normaliza(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    expected: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", source)

    settings = Settings(_env_file=None)

    assert settings.sqlalchemy_database_uri == expected


def test_variables_de_entorno_tienen_prioridad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["https://app.example.org/", "https://app.example.org"]',
    )

    settings = Settings(_env_file=None)

    assert settings.port == 9123
    assert settings.cors_origins == ["https://app.example.org"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATABASE_URL", "sqlite:///database.db"),
        ("PORT", "70000"),
        ("CORS_ORIGINS", '["*"]'),
    ],
)
def test_configuracion_invalida_es_rechazada(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_jwt_exige_clave_propia_en_produccion() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="production")
    with pytest.raises(ValidationError, match="32 caracteres"):
        Settings(_env_file=None, jwt_secret="corta")
    settings = Settings(_env_file=None, app_env="production", jwt_secret="x" * 48)
    assert settings.clave_jwt == "x" * 48
