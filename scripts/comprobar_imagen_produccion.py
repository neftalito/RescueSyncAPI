"""Verifica el contenedor de producción desde otro contenedor de la misma red."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.core.config import get_settings


def comprobar_mantenimiento() -> None:
    """Ejercita ambos seeds y flush por HTTP en la base efímera de producción."""
    password = get_settings().db_maintenance_password
    assert password is not None
    url = "http://api:9017/api/v1/mantenimiento"
    try:
        urlopen(Request(f"{url}/flush", method="POST"), timeout=5)
    except HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError("Flush debe rechazar peticiones sin contraseña")
    headers = {
        "X-DB-Maintenance-Password": password.get_secret_value(),
        "Content-Type": "application/json",
    }
    operaciones = (
        ("seed", None),
        ("seed-masivo", {"ongs": 2, "recursosPorOng": 4}),
        ("flush", None),
        # Verifica que el catálogo se recupera después de borrar todo.
        ("seed", None),
    )
    for operacion, datos in operaciones:
        solicitud = Request(
            f"{url}/{operacion}",
            method="POST",
            headers=headers,
            data=json.dumps(datos).encode() if datos is not None else None,
        )
        with urlopen(solicitud, timeout=30) as response:
            assert response.status == 200, operacion
            assert json.load(response)["operacion"] == operacion


def main() -> None:
    """Comprueba runtime, migraciones y HTTP sin dependencias de desarrollo."""
    assert sys.version_info[:2] == (3, 13), "Se requiere Python 3.13"
    assert os.getuid() != 0, "La imagen no debe ejecutar como root"
    for module in ("pytest", "ruff"):
        assert importlib.util.find_spec(module) is None, module
    for artifact in (
        ".git",
        ".env",
        ".env.production",
        "tests",
        "requirements-dev.txt",
    ):
        assert not (Path("/app") / artifact).exists(), artifact

    settings = get_settings()
    assert settings.app_env == "production"
    assert settings.port == 9017
    assert settings.sqlalchemy_database_uri.startswith("postgresql+psycopg://")

    engine = create_engine(settings.sqlalchemy_database_uri)
    try:
        with engine.connect() as connection:
            applied = MigrationContext.configure(connection).get_current_heads()
        expected = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
        assert set(applied) == set(expected), "La base debe estar migrada hasta head"
    finally:
        engine.dispose()

    for path in ("/api/v1/health", "/api/v1/health/database"):
        with urlopen(f"http://api:9017{path}", timeout=5) as response:
            assert response.status == 200, path
            assert json.load(response) == {"status": "ok", "service": "national-api"}
    for path in ("/", "/docs", "/redoc", "/openapi.json"):
        with urlopen(f"http://api:9017{path}", timeout=5) as response:
            assert response.status == 200, path

    comprobar_mantenimiento()

    print("Producción OK: Python 3.13, UID no root, PORT=9017, health y migraciones.")


if __name__ == "__main__":
    main()
