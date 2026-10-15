"""Permisos administrativos, unidades de referencia y altas concurrentes."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import get_settings
from app.core.security import emitir_token
from app.db.models import Capacidad, Cuenta, Ong, RolNacional, SistemaOrigen, Unidad
from app.db.session import get_db
from app.main import app
from app.schemas.catalogo import CapacidadCreate
from app.services.catalogo import CapacidadDuplicadaError, crear_capacidad

DATOS = {
    "codigo": "ALIMENTOS",
    "nombre": "Alimentos no perecederos",
    "tipo": "SUMINISTRO",
    "unidad": "kg",
    "admiteFracciones": True,
}


@pytest.fixture
def catalogo_client(session: Session) -> Iterator[TestClient]:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def cuentas(session: Session) -> dict[RolNacional, Cuenta]:
    origen = SistemaOrigen(codigo="catalogo", nombre="Emisor del catálogo")
    ong = Ong(
        nombre="ONG catálogo",
        identificador_institucional="catalogo",
        email_contacto="ong@example.org",
    )
    session.add_all([origen, ong])
    session.flush()
    resultado = {
        rol: Cuenta(
            identificador_login=f"catalogo-{rol.lower()}@example.org",
            password_hash="$argon2id$hash-de-prueba",
            rol=rol,
            ong_id=ong.id if rol == RolNacional.ONG else None,
            sistema_origen_id=origen.id if rol == RolNacional.INTEGRACION else None,
        )
        for rol in RolNacional
    }
    session.add_all(resultado.values())
    session.flush()
    return resultado


def auth(cuenta: Cuenta) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_token(cuenta.id)}"}


def test_administrador_crea_capacidad_y_el_catalogo_la_devuelve(
    catalogo_client: TestClient, session: Session, cuentas: dict[RolNacional, Cuenta]
) -> None:
    headers = auth(cuentas[RolNacional.ADMIN_NACIONAL])
    unidades_antes = session.scalar(select(func.count()).select_from(Unidad))

    respuesta = catalogo_client.post("/api/v1/capacidades", headers=headers, json=DATOS)

    assert respuesta.status_code == 201
    assert respuesta.headers["cache-control"] == "no-store"
    payload = respuesta.json()
    assert {key: payload[key] for key in DATOS} == DATOS
    capacidad = session.scalar(
        select(Capacidad).where(Capacidad.codigo == DATOS["codigo"])
    )
    assert capacidad is not None and capacidad.activa
    for cuenta in cuentas.values():
        listado = catalogo_client.get("/api/v1/capacidades", headers=auth(cuenta))
        assert listado.status_code == 200 and listado.json() == [payload]
    assert session.scalar(select(func.count()).select_from(Unidad)) == unidades_antes


@pytest.mark.parametrize("rol", [RolNacional.ONG, RolNacional.INTEGRACION, None])
def test_solo_admin_nacional_puede_crear(
    catalogo_client: TestClient,
    session: Session,
    cuentas: dict[RolNacional, Cuenta],
    rol: RolNacional | None,
) -> None:
    respuesta = catalogo_client.post(
        "/api/v1/capacidades",
        json=DATOS,
        headers=auth(cuentas[rol]) if rol else {},
    )
    assert respuesta.status_code == (403 if rol else 401)
    assert session.scalar(select(func.count()).select_from(Capacidad)) == 0


def test_cuenta_desactivada_pierde_el_permiso_con_el_mismo_jwt(
    catalogo_client: TestClient, session: Session, cuentas: dict[RolNacional, Cuenta]
) -> None:
    cuenta = cuentas[RolNacional.ADMIN_NACIONAL]
    headers = auth(cuenta)
    cuenta.activa = False
    session.flush()
    assert (
        catalogo_client.post(
            "/api/v1/capacidades", headers=headers, json=DATOS
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "cambio",
    [
        {"unidad": "unidad-inventada"},
        {"unidad": {"codigo": "nueva", "nombre": "Nueva unidad"}},
        {"nombre": " "},
        {"codigo": "codigo con espacios"},
        {"codigo": "X" * 81},
        {"tipo": "OTRO"},
        {"tipo": "PERSONAL"},
        {"tipo": "VEHICULO"},
        {"activa": False},
        {"admiteFracciones": "true"},
    ],
)
def test_rechaza_datos_invalidos_sin_crear_capacidad_ni_unidad(
    catalogo_client: TestClient,
    session: Session,
    cuentas: dict[RolNacional, Cuenta],
    cambio: dict[str, object],
) -> None:
    total = session.scalar(select(func.count()).select_from(Unidad))
    respuesta = catalogo_client.post(
        "/api/v1/capacidades",
        headers=auth(cuentas[RolNacional.ADMIN_NACIONAL]),
        json={**DATOS, **cambio},
    )
    assert respuesta.status_code == 422
    assert session.scalar(select(func.count()).select_from(Capacidad)) == 0
    assert session.scalar(select(func.count()).select_from(Unidad)) == total


def test_codigo_duplicado_devuelve_conflicto_y_conserva_primera_capacidad(
    catalogo_client: TestClient, session: Session, cuentas: dict[RolNacional, Cuenta]
) -> None:
    headers = auth(cuentas[RolNacional.ADMIN_NACIONAL])
    primera = catalogo_client.post("/api/v1/capacidades", headers=headers, json=DATOS)
    segunda = catalogo_client.post(
        "/api/v1/capacidades", headers=headers, json={**DATOS, "nombre": "Otro nombre"}
    )
    assert primera.status_code == 201 and segunda.status_code == 409
    assert catalogo_client.get("/api/v1/capacidades", headers=headers).json() == [
        primera.json()
    ]


def test_unidades_son_consultables_y_no_tienen_operaciones_de_escritura(
    catalogo_client: TestClient, session: Session, cuentas: dict[RolNacional, Cuenta]
) -> None:
    for cuenta in cuentas.values():
        response = catalogo_client.get("/api/v1/unidades", headers=auth(cuenta))
        assert response.status_code == 200 and len(response.json()) == 31
        assert {"litros", "personas", "vehículos", "kg", "raciones", "horas"} <= {
            unidad["codigo"] for unidad in response.json()
        }
    headers = auth(cuentas[RolNacional.ADMIN_NACIONAL])
    for metodo, url in (
        ("POST", "/api/v1/unidades"),
        ("PATCH", "/api/v1/unidades/litros"),
        ("DELETE", "/api/v1/unidades/litros"),
    ):
        assert catalogo_client.request(
            metodo, url, headers=headers, json={"codigo": "nueva"}
        ).status_code in {404, 405}
    assert session.scalar(select(func.count()).select_from(Unidad)) == 31
    assert catalogo_client.get("/api/v1/unidades").status_code == 401


def test_base_rechaza_capacidad_con_unidad_inexistente(session: Session) -> None:
    session.add(
        Capacidad(
            codigo="INVALIDA",
            nombre="Inválida",
            tipo="SUMINISTRO",
            unidad="inexistente",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_codigos_concurrentes_crean_una_sola_capacidad(engine_migrado: Engine) -> None:
    def crear() -> str:
        with Session(engine_migrado) as session:
            try:
                crear_capacidad(
                    session,
                    CapacidadCreate.model_validate({**DATOS, "codigo": "CONCURRENTE"}),
                )
                return "creada"
            except CapacidadDuplicadaError:
                return "duplicada"

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: crear(), range(2)))
    assert sorted(resultados) == ["creada", "duplicada"]
    with engine_migrado.begin() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM capacidad WHERE codigo='CONCURRENTE'")
            )
            == 1
        )
        connection.execute(text("DELETE FROM capacidad WHERE codigo='CONCURRENTE'"))


def test_migracion_carga_unidades_en_produccion_y_preserva_unidades_historicas(
    engine_migrado: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production")
    schema = f"test_unidades_{uuid4().hex}"
    with engine_migrado.begin() as connection:
        connection.execute(CreateSchema(schema))
        connection.execute(text(f"SET LOCAL search_path={schema}"))
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "20261004_0001")
        connection.execute(
            text(
                "INSERT INTO capacidad (id, codigo, nombre, tipo, unidad) "
                "VALUES (:id, 'HISTORICA', 'Histórica', 'SUMINISTRO', "
                "'envases de 5 litros')"
            ),
            {"id": uuid4()},
        )

        command.upgrade(config, "head")

        assert connection.scalar(text("SELECT count(*) FROM unidad")) == 32
        assert (
            connection.scalar(
                text("SELECT unidad FROM capacidad WHERE codigo='HISTORICA'")
            )
            == "envases de 5 litros"
        )
        command.downgrade(config, "20261004_0001")
        assert "unidad" not in inspect(connection).get_table_names()
        assert connection.scalar(text("SELECT count(*) FROM capacidad")) == 1
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT count(*) FROM unidad")) == 32
        connection.execute(DropSchema(schema, cascade=True))
