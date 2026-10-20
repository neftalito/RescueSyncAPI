"""Recuperación tras timeout de locks y rotación de cuentas del mismo emisor."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from soporte_nacional import auth, client, datos
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from test_compromisos import headers, peticion
from test_compromisos_concurrencia import preparar
from test_database_models import DatosNacionales

from app.core.config import get_settings
from app.core.security import emitir_token
from app.db.models import Compromiso, Cuenta, OperacionIdempotente, Recurso, RolNacional
from app.db.session import get_db
from app.main import app

__all__ = ["client", "datos"]


def test_timeout_revierte_y_reintento_recupera_confirmacion(
    engine_migrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = preparar(engine_migrado)
    monkeypatch.setattr(get_settings(), "operacion_lock_timeout_ms", 100)

    def database() -> Iterator[Session]:
        with Session(engine_migrado) as db:
            yield db

    app.dependency_overrides[get_db] = database
    try:
        with TestClient(app) as cliente, Session(engine_migrado) as holder:
            holder.scalar(
                select(Recurso).where(Recurso.id == e.recurso_id).with_for_update()
            )
            cabeceras = {
                "Authorization": f"Bearer {emitir_token(e.cuenta_id)}",
                "Idempotency-Key": "timeout",
            }
            body = e.solicitud.model_dump(mode="json", by_alias=True)
            respuesta = cliente.post(
                "/api/v1/compromisos", headers=cabeceras, json=body
            )
            assert respuesta.status_code == 503
            assert "misma clave" in respuesta.json()["detail"]
            assert "SELECT" not in respuesta.text and "psycopg" not in respuesta.text
            with Session(engine_migrado) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(OperacionIdempotente)
                        .where(OperacionIdempotente.cuenta_id == e.cuenta_id)
                    )
                    == 0
                )
            holder.rollback()
            respuesta = cliente.post(
                "/api/v1/compromisos", headers=cabeceras, json=body
            )
            assert respuesta.status_code == 201, respuesta.text
    finally:
        app.dependency_overrides.clear()


def test_otra_cuenta_del_mismo_emisor_reproduce_resultado(
    client: TestClient, session: Session, datos: DatosNacionales
) -> None:
    solicitud = peticion(datos).model_dump(mode="json", by_alias=True)
    original = client.post(
        "/api/v1/compromisos", headers=headers(datos), json=solicitud
    )
    assert original.status_code == 201
    cuenta = Cuenta(
        identificador_login=f"rotada-{uuid4()}",
        rol=RolNacional.INTEGRACION,
        sistema_origen_id=datos.origen.id,
        password_hash="$argon2id$hash-tecnico-de-prueba",
    )
    session.add(cuenta)
    session.commit()
    repetida = client.post(
        "/api/v1/compromisos",
        headers={**auth(cuenta), "Idempotency-Key": "adjudicacion-1"},
        json=solicitud,
    )
    assert repetida.status_code == 201 and repetida.json() == original.json()
    assert (
        session.scalar(
            select(func.count())
            .select_from(Compromiso)
            .where(Compromiso.ong_id == datos.ong.id)
        )
        == 1
    )
