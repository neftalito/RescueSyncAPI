"""Permisos, decimales y concurrencia del inventario nacional."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from test_database_models import (
    crear_compromiso,
    crear_datos,
)

from app.core.config import get_settings
from app.core.security import emitir_token, generar_password_hash
from app.db.models import Cuenta, Ong, Recurso, RolNacional
from app.db.session import get_db
from app.main import app
from app.schemas.inventario import RecursoUpdate
from app.scripts.seed import seed_development_data
from app.services.inventario import (
    InventarioConflictivoError,
    actualizar_recurso,
    listar_recursos,
)


@pytest.fixture
def inventory_client(session: Session) -> Iterator[TestClient]:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def cuenta(session: Session) -> Cuenta:
    seed_development_data(session)
    session.commit()
    cuenta = session.scalar(
        select(Cuenta).where(Cuenta.identificador_login == "ong@rescuesync.org")
    )
    assert cuenta is not None
    return cuenta


def auth(cuenta: Cuenta) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_token(cuenta.id)}"}


def test_login_me_y_stock_en_strings(
    inventory_client: TestClient, cuenta: Cuenta
) -> None:
    login = inventory_client.post(
        "/api/v1/login",
        json={
            "identificadorLogin": " ONG@RESCUESYNC.ORG ",
            "password": "ong-nacional123",
        },
    )
    assert login.status_code == 200
    assert login.headers["cache-control"] == "no-store"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert inventory_client.get("/api/v1/me", headers=headers).json()["ongId"] == str(
        cuenta.ong_id
    )
    listado = inventory_client.get(
        f"/api/v1/ongs/{cuenta.ong_id}/recursos", headers=headers
    )
    assert listado.status_code == 200 and len(listado.json()) == 2
    assert all(isinstance(r["cantidadTotal"], str) for r in listado.json())
    assert (
        inventory_client.post(
            "/api/v1/login",
            json={"identificadorLogin": "ong@rescuesync.org", "password": "incorrecta"},
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "alteracion", ["exp", "iss", "aud", "missing", "firma", "algoritmo"]
)
def test_jwt_invalido_rechazado(
    inventory_client: TestClient, cuenta: Cuenta, alteracion: str
) -> None:
    settings = get_settings()
    claims: dict[str, str | int] = {
        "sub": str(cuenta.id),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if alteracion == "exp":
        claims["exp"] = int((datetime.now(UTC) - timedelta(seconds=1)).timestamp())
    if alteracion in {"iss", "aud"}:
        claims[alteracion] = "otro-sistema"
    if alteracion == "missing":
        del claims["exp"]
    token = jwt.encode(
        claims,
        "x" * 48 if alteracion == "firma" else settings.clave_jwt,
        algorithm="HS384" if alteracion == "algoritmo" else "HS256",
    )
    assert (
        inventory_client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )


def test_permisos_se_cargan_nuevamente(
    inventory_client: TestClient, session: Session, cuenta: Cuenta
) -> None:
    headers = auth(cuenta)
    assert (
        inventory_client.get(
            f"/api/v1/ongs/{uuid4()}/recursos", headers=headers
        ).status_code
        == 403
    )
    cuenta.activa = False
    session.commit()
    assert inventory_client.get("/api/v1/me", headers=headers).status_code == 401


def test_onboarding_atomico_pendiente_y_sin_roles(
    inventory_client: TestClient, session: Session
) -> None:
    datos = {
        "identificadorLogin": "nueva@example.org",
        "password": "password-seguro123",
        "nombre": "ONG Nueva",
        "identificadorInstitucional": "REGISTRO:123",
        "emailContacto": "contacto@example.org",
    }
    assert (
        inventory_client.post(
            "/api/v1/ongs", json={**datos, "rol": "ADMIN_NACIONAL"}
        ).status_code
        == 422
    )
    response = inventory_client.post("/api/v1/ongs", json=datos)
    assert response.status_code == 201 and response.json()["estado"] == "PENDIENTE"
    assert (
        inventory_client.post(
            "/api/v1/ongs",
            json={**datos, "identificadorInstitucional": "otro:registro"},
        ).status_code
        == 409
    )
    assert session.scalar(select(func.count()).select_from(Ong)) == 1
    cuenta = session.scalar(select(Cuenta))
    assert cuenta is not None and cuenta.password_hash.startswith("$argon2id$")
    assert cuenta.rol == RolNacional.ONG


def test_alta_fracciones_duplicados_y_edicion_obsoleta(
    inventory_client: TestClient, cuenta: Cuenta
) -> None:
    headers = auth(cuenta)
    capacidad = next(
        c
        for c in inventory_client.get("/api/v1/capacidades", headers=headers).json()
        if c["codigo"] == "PARAMEDICOS"
    )
    ruta = f"/api/v1/ongs/{cuenta.ong_id}/recursos"
    datos = {
        "capacidadId": capacidad["id"],
        "codigoInterno": "EQUIPO-02",
        "nombre": "Equipo",
        "cantidadTotal": "2.5",
    }
    assert inventory_client.post(ruta, json=datos, headers=headers).status_code == 422
    creado = inventory_client.post(
        ruta, json={**datos, "cantidadTotal": "2"}, headers=headers
    )
    assert creado.status_code == 201
    assert (
        inventory_client.post(
            ruta, json={**datos, "cantidadTotal": "2"}, headers=headers
        ).status_code
        == 409
    )
    body = creado.json()
    patch = {"cantidadTotal": "5", "actualizadoEn": body["actualizadoEn"]}
    assert (
        inventory_client.patch(
            f"{ruta}/{body['id']}", json=patch, headers=headers
        ).status_code
        == 200
    )
    assert (
        inventory_client.patch(
            f"{ruta}/{body['id']}", json=patch, headers=headers
        ).status_code
        == 409
    )
    assert (
        inventory_client.patch(
            f"{ruta}/{uuid4()}", json=patch, headers=headers
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "cantidad", ["-1", "NaN", "Infinity", "1.0001", "100000000000"]
)
def test_cantidades_invalidas_no_exponen_entrada(
    inventory_client: TestClient, cuenta: Cuenta, cantidad: str
) -> None:
    datos = {
        "capacidadId": str(uuid4()),
        "codigoInterno": "INVALIDO",
        "nombre": "Inválido",
        "cantidadTotal": cantidad,
    }
    response = inventory_client.post(
        f"/api/v1/ongs/{cuenta.ong_id}/recursos", headers=auth(cuenta), json=datos
    )
    assert response.status_code == 422 and list(response.json()) == ["detail"]


def test_inventario_suma_compromisos_y_no_permite_reducirlos(session: Session) -> None:
    datos = crear_datos(session, "inventario-compromiso")
    crear_compromiso(session, datos, cantidad=Decimal(4))
    session.commit()
    response = listar_recursos(session, datos.ong.id)[0]
    assert response.cantidad_comprometida == Decimal(
        4
    ) and response.cantidad_disponible == Decimal(6)
    with pytest.raises(InventarioConflictivoError):
        actualizar_recurso(
            session,
            datos.ong.id,
            datos.recurso.id,
            RecursoUpdate(
                cantidad_total=Decimal(3), actualizado_en=response.actualizado_en
            ),
        )
    session.rollback()
    assert session.get(Recurso, datos.recurso.id).cantidad_total == Decimal(10)


def test_edicion_recalcula_despues_de_reserva_concurrente(
    engine_migrado: Engine,
) -> None:
    """Una conexión reserva mientras otra intenta reducir el mismo stock."""
    with Session(engine_migrado, expire_on_commit=False) as preparacion:
        datos = crear_datos(preparacion, "inventario-concurrente")
        preparacion.commit()
        ong_id, recurso_id, version = (
            datos.ong.id,
            datos.recurso.id,
            datos.recurso.actualizado_en,
        )
    iniciado = Event()

    def editar() -> str:
        with Session(engine_migrado) as db:
            iniciado.set()
            try:
                actualizar_recurso(
                    db,
                    ong_id,
                    recurso_id,
                    RecursoUpdate(cantidad_total=Decimal(3), actualizado_en=version),
                )
            except InventarioConflictivoError:
                db.rollback()
                return "conflicto"
            return "actualizado"

    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        Session(engine_migrado) as reserva,
    ):
        reserva.scalar(
            select(Recurso).where(Recurso.id == recurso_id).with_for_update()
        )
        future = executor.submit(editar)
        assert iniciado.wait(timeout=5)
        crear_compromiso(reserva, datos, cantidad=Decimal(4))
        reserva.commit()
        assert future.result(timeout=5) == "conflicto"
    with Session(engine_migrado) as db:
        actual = listar_recursos(db, ong_id)[0]
        assert actual.cantidad_total == Decimal(
            10
        ) and actual.cantidad_disponible == Decimal(6)


def test_seed_idempotente_preserva_stock_y_password(session: Session) -> None:
    seed_development_data(session)
    session.commit()
    recurso = session.scalar(select(Recurso))
    cuenta = session.scalar(select(Cuenta))
    assert recurso is not None and cuenta is not None
    recurso.cantidad_total = Decimal(777)
    hash_nuevo = generar_password_hash("clave-modificada123")
    cuenta.password_hash = hash_nuevo
    session.commit()
    seed_development_data(session)
    session.commit()
    assert (
        session.scalar(
            select(func.count())
            .select_from(Ong)
            .where(Ong.identificador_institucional.like("demo:%"))
        )
        == 2
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(Recurso)
            .where(
                Recurso.ong_id.in_(
                    select(Ong.id).where(Ong.identificador_institucional.like("demo:%"))
                )
            )
        )
        == 4
    )
    assert recurso.cantidad_total == Decimal(777) and cuenta.password_hash == hash_nuevo


def test_admin_inventario_y_cuenta_tecnica_tienen_permisos_distintos(
    inventory_client: TestClient,
    session: Session,
) -> None:
    datos = crear_datos(session, "permisos-inventario")
    session.commit()
    ruta = f"/api/v1/ongs/{datos.ong.id}/recursos"
    assert (
        inventory_client.get(ruta, headers=auth(datos.integracion)).status_code == 200
    )
    alta = {
        "capacidadId": str(datos.capacidad.id),
        "codigoInterno": "EQUIPO-03",
        "nombre": "Equipo extra",
        "cantidadTotal": "2",
    }
    assert (
        inventory_client.post(
            ruta, headers=auth(datos.integracion), json=alta
        ).status_code
        == 403
    )
    assert (
        inventory_client.post(ruta, headers=auth(datos.admin), json=alta).status_code
        == 201
    )
    otra = Ong(
        identificador_institucional="permisos:otra",
        nombre="Otra ONG",
        email_contacto="otra@example.org",
    )
    session.add(otra)
    session.flush()
    usuario = Cuenta(
        identificador_login="otra@example.org",
        password_hash=generar_password_hash("clave-segura123"),
        rol=RolNacional.ONG,
        ong_id=otra.id,
    )
    session.add(usuario)
    session.commit()
    assert inventory_client.get(ruta, headers=auth(usuario)).status_code == 403
    assert (
        inventory_client.patch(
            f"/api/v1/ongs/{otra.id}/recursos/{datos.recurso.id}",
            headers=auth(usuario),
            json={
                "cantidadTotal": "3",
                "actualizadoEn": datos.recurso.actualizado_en.isoformat(),
            },
        ).status_code
        == 404
    )
