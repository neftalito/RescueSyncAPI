"""CORS desde .env: preflight, credenciales, errores y orígenes exactos."""

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.cors import AplicacionConCORS
from app.main import app

ORIGENES = ["https://app.example.org", "https://admin.example.org"]


@pytest.fixture
def cliente_cors() -> TestClient:
    aplicacion = AplicacionConCORS()
    aplicacion.origenes_cors = tuple(ORIGENES)
    aplicacion.credenciales_cors = False

    @aplicacion.get("/estado/{codigo}")
    def respuesta(codigo: int) -> dict[str, str]:
        if codigo == 500:
            raise RuntimeError("error interno de prueba")
        if codigo != 200:
            raise HTTPException(status_code=codigo, detail="Error de prueba")
        return {"status": "ok"}

    return TestClient(aplicacion, raise_server_exceptions=False)


def test_aplicacion_real_usa_origenes_del_entorno() -> None:
    assert isinstance(app, AplicacionConCORS)
    assert app.origenes_cors == tuple(get_settings().cors_origins)
    assert app.credenciales_cors is False


def test_origenes_se_leen_desde_dotenv_y_variable_tiene_prioridad(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archivo = tmp_path / ".env"
    archivo.write_text(
        'CORS_ORIGINS=[" HTTPS://APP.EXAMPLE.ORG:443/ ","https://admin.example.org/","https://app.example.org"]\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=archivo).cors_origins == ORIGENES
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:4173"]')
    assert Settings(_env_file=archivo).cors_origins == ["http://localhost:4173"]


@pytest.mark.parametrize(
    "origen",
    [
        "*",
        "https://*.example.org",
        "example.org",
        "null",
        "file:///app",
        "https://user:pass@example.org",
        "https://example.org/api/v1",
        "https://example.org?x=1",
        "https://example.org#app",
        "https://example.org:99999",
        "https://exam ple.org",
        "https://example.org\\otra",
    ],
)
def test_rechaza_origenes_que_el_navegador_no_puede_autorizar(origen: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origen])


def test_lista_vacia_y_loopback_ipv6_son_configuraciones_validas() -> None:
    assert Settings(_env_file=None, cors_origins=[]).cors_origins == []
    assert Settings(
        _env_file=None, cors_origins=["http://[::1]:5173/"]
    ).cors_origins == ["http://[::1]:5173"]


@pytest.mark.parametrize("origen", ORIGENES)
@pytest.mark.parametrize("codigo", [200, 401, 403, 422, 500])
def test_respuestas_incluso_500_conservan_cors(
    cliente_cors: TestClient,
    origen: str,
    codigo: int,
) -> None:
    respuesta = cliente_cors.get(f"/estado/{codigo}", headers={"Origin": origen})
    assert respuesta.status_code == codigo
    assert respuesta.headers["Access-Control-Allow-Origin"] == origen
    assert "Access-Control-Allow-Credentials" not in respuesta.headers
    assert "Origin" in respuesta.headers["Vary"]


def test_preflight_admite_json_autorizacion_csrf_e_idempotencia(
    cliente_cors: TestClient,
) -> None:
    respuesta = cliente_cors.options(
        "/ruta-protegida",
        headers={
            "Origin": ORIGENES[0],
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                "authorization,content-type,x-csrf-token,idempotency-key"
                ",x-db-maintenance-password"
            ),
        },
    )
    assert respuesta.status_code == 200
    assert respuesta.headers["Access-Control-Allow-Origin"] == ORIGENES[0]
    assert "POST" in respuesta.headers["Access-Control-Allow-Methods"]


@pytest.mark.parametrize(
    "origen",
    [
        "https://app.example.org.evil.test",
        "http://app.example.org",
        "https://app.example.org:8443",
        "null",
    ],
)
def test_otro_origen_no_recibe_permiso(cliente_cors: TestClient, origen: str) -> None:
    headers = {"Origin": origen}
    assert (
        "Access-Control-Allow-Origin"
        not in cliente_cors.get("/estado/200", headers=headers).headers
    )
    headers["Access-Control-Request-Method"] = "POST"
    assert cliente_cors.options("/ruta-protegida", headers=headers).status_code == 400


def test_sin_origin_no_se_agregan_cabeceras_cors(cliente_cors: TestClient) -> None:
    assert "Access-Control-Allow-Origin" not in cliente_cors.get("/estado/200").headers
