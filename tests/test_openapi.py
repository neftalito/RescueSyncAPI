"""Comprueba el contrato publicado y sus ejemplos contra los DTO ejecutables."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter

from app.api import ejemplos
from app.main import app
from app.schemas.aprovisionamiento import AprovisionamientoRequest
from app.schemas.catalogo import CapacidadCreate
from app.schemas.compromisos import CompromisoRequest
from app.schemas.inventario import LoginRequest, OngCreate, RecursoCreate, RecursoUpdate
from app.schemas.proyectos import FinalizacionRequest
from app.schemas.validaciones import ValidacionRequest

ROOT = Path(__file__).resolve().parents[1]
OPERACIONES = [
    (ruta, metodo)
    for ruta, metodos in app.openapi()["paths"].items()
    for metodo in metodos
    if metodo in {"get", "post", "put", "patch", "delete"}
]
CUERPOS = {
    ("/api/v1/login", "post"): LoginRequest,
    ("/api/v1/ongs", "post"): OngCreate,
    ("/api/v1/capacidades", "post"): CapacidadCreate,
    ("/api/v1/ongs/{ong_id}/recursos", "post"): RecursoCreate,
    ("/api/v1/ongs/{ong_id}/recursos/{recurso_id}", "patch"): RecursoUpdate,
    ("/api/v1/validaciones", "post"): ValidacionRequest,
    ("/api/v1/compromisos", "post"): CompromisoRequest,
    ("/api/v1/compromisos/{compromiso_id}/liberacion", "post"): FinalizacionRequest,
    ("/api/v1/proyectos/{proyecto_id}/cierre", "post"): FinalizacionRequest,
    ("/api/v1/integraciones/ongs/{referencia_local}", "put"): AprovisionamientoRequest,
}
PUBLICAS = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/database"),
    ("POST", "/api/v1/login"),
    ("POST", "/api/v1/ongs"),
}


@pytest.mark.parametrize(("ruta", "metodo"), OPERACIONES)
def test_operaciones_documentan_acceso_errores_y_ejemplos(
    ruta: str, metodo: str
) -> None:
    esquema = app.openapi()
    operacion = esquema["paths"][ruta][metodo]
    assert operacion["summary"]
    assert "Acceso" in operacion["description"]
    publica = (metodo.upper(), ruta) in PUBLICAS
    assert operacion.get("security", []) == ([] if publica else [{"HTTPBearer": []}])
    if not publica:
        assert {"401", "403"} <= operacion["responses"].keys()
    for codigo, respuesta in operacion["responses"].items():
        assert respuesta["description"]
        contenido = respuesta["content"]["application/json"]
        assert "example" in contenido, (ruta, codigo)
        # Se valida el formato de transporte, incluidas cantidades como strings,
        # alias camelCase, UUID, timestamps y propiedades adicionales prohibidas.
        contrato = {**contenido["schema"], "components": esquema["components"]}
        Draft202012Validator(contrato, format_checker=FormatChecker()).validate(
            contenido["example"]
        )
        if int(codigo) >= 400:
            assert contenido["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}
    for parametro in operacion.get("parameters", []):
        assert parametro["description"]
        assert parametro["schema"]["examples"]
    if "requestBody" in operacion:
        contenido = operacion["requestBody"]["content"]["application/json"]
        entradas = contenido["schema"]["examples"]
        assert entradas
        for entrada in entradas:
            # Además del JSON Schema, se ejecutan los validadores de negocio del DTO.
            TypeAdapter(CUERPOS[ruta, metodo]).validate_python(entrada)
            contrato = {**contenido["schema"], "components": esquema["components"]}
            Draft202012Validator(contrato, format_checker=FormatChecker()).validate(
                entrada
            )


def test_exportacion_json_coincide_con_openapi_publicado(client: TestClient) -> None:
    publicado = client.get("/openapi.json")
    assert publicado.status_code == 200
    exportado = json.loads((ROOT / "docs/generated/openapi.json").read_text())
    assert exportado == publicado.json()
    seguridad = exportado["components"]["securitySchemes"]["HTTPBearer"]
    assert seguridad["scheme"] == "bearer"
    assert seguridad["bearerFormat"] == "JWT"
    assert "POST /api/v1/login" in seguridad["description"]


def test_ejemplos_integracion_conservan_snapshot_y_referencias_t34() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/snapshot_t34.json").read_text())
    assert ejemplos.SNAPSHOT_CERRADO == fixture
    item = fixture["ofertas"][0]["items"][0]
    aporte = item["aportes"][0]
    adjudicado = ejemplos.ADJUDICACION["aportes"][0]
    for campo in (
        "ongNacionalId",
        "recursoNacionalId",
        "capacidadNacionalId",
        "cantidad",
        "unidad",
    ):
        assert adjudicado[campo] == aporte[campo]
    assert adjudicado["aporteId"] == str(aporte["aporteId"])
    assert ejemplos.VALIDACION["aportes"][0]["itemId"] == item["itemId"]
    assert ejemplos.CONFIRMACION["compromisoIds"] == [ejemplos.COMPROMISO["id"]]
    assert ejemplos.LIBERACION["compromisoId"] == ejemplos.COMPROMISO["id"]
    assert ejemplos.CIERRE["proyectoId"] == ejemplos.CONFIRMACION["proyectoId"]


def test_error_503_health_coincide_con_contrato(client: TestClient) -> None:
    from collections.abc import Iterator
    from unittest.mock import Mock

    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    from app.db.session import get_db

    sesion = Mock(spec=Session)
    sesion.execute.side_effect = SQLAlchemyError("fallo controlado")

    def reemplazar() -> Iterator[Session]:
        yield sesion

    app.dependency_overrides[get_db] = reemplazar
    respuesta = client.get("/api/v1/health/database")
    documentado = app.openapi()["paths"]["/api/v1/health/database"]["get"]["responses"][
        "503"
    ]
    assert respuesta.status_code == 503
    assert respuesta.json() == documentado["content"]["application/json"]["example"]


def test_compromiso_declara_error_de_inventario_inconsistente() -> None:
    respuesta = app.openapi()["paths"]["/api/v1/compromisos"]["post"]["responses"][
        "500"
    ]
    assert respuesta["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
