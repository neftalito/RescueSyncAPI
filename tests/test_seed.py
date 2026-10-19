"""Las identidades técnicas demo coinciden con el seed local y son recuperables."""

from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_inventario import inventory_client as inventory_client_fixture

from app.core.config import get_settings
from app.core.security import generar_password_hash
from app.db.models import Capacidad, Cuenta, PropositoCuenta, RolNacional
from app.scripts.seed import seed_development_data

inventory_client = inventory_client_fixture


def test_seed_demo_reutiliza_catalogo_sin_modificarlo(session: Session) -> None:
    consulta = select(Capacidad.__table__).order_by(Capacidad.codigo)
    capacidades_antes = session.execute(consulta).all()

    seed_development_data(session)
    seed_development_data(session)

    assert session.execute(consulta).all() == capacidades_antes


def test_seed_demo_sigue_rechazando_produccion(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ValueError, match="desarrollo y pruebas"):
        seed_development_data(session)
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 0


@pytest.mark.parametrize("referencia", ["ayuda-sin-fronteras", "red-medica-solidaria"])
def test_seed_prepara_login_tecnico_y_recursos_propios(
    inventory_client: TestClient,
    session: Session,
    referencia: str,
) -> None:
    seed_development_data(session)
    seed_development_data(session)
    session.commit()
    ong_id = uuid5(NAMESPACE_URL, f"rescuesync-demo:ong:{referencia}")
    cuenta_id = uuid5(NAMESPACE_URL, f"rescuesync-demo:cuenta-tecnica:{referencia}")
    cuenta = session.get(Cuenta, cuenta_id)
    assert cuenta is not None and cuenta.proposito == PropositoCuenta.TECNICA_ONG
    assert cuenta.ong_id == ong_id and cuenta.rol == RolNacional.ONG
    login = inventory_client.post(
        "/api/v1/login",
        json={
            "identificadorLogin": f"demo-tecnica-{referencia}",
            "password": f"demo-only-rescuesync-tecnica:{referencia}:2026",
        },
    )
    assert login.status_code == 200 and login.json()["expires_in"] == 300
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = inventory_client.get("/api/v1/me", headers=headers)
    assert me.json()["id"] == str(cuenta_id)
    assert me.json()["proposito"] == "TECNICA_ONG"
    recursos = inventory_client.get(f"/api/v1/ongs/{ong_id}/recursos", headers=headers)
    assert recursos.status_code == 200 and len(recursos.json()) == 2
    assert (
        session.scalar(
            select(func.count())
            .select_from(Cuenta)
            .where(Cuenta.proposito == PropositoCuenta.TECNICA_ONG)
        )
        == 2
    )


def test_seed_no_rota_ni_reactiva_cuenta_tecnica_demo(session: Session) -> None:
    seed_development_data(session)
    cuenta = session.scalar(
        select(Cuenta).where(Cuenta.proposito == PropositoCuenta.TECNICA_ONG)
    )
    assert cuenta is not None
    cuenta.password_hash = generar_password_hash("credencial-rotada-123")
    cuenta.activa = False
    cuenta.version_credencial += 1
    original = (cuenta.id, cuenta.password_hash, cuenta.version_credencial)
    session.commit()
    seed_development_data(session)
    session.commit()
    session.refresh(cuenta)
    assert (cuenta.id, cuenta.password_hash, cuenta.version_credencial) == original
    assert cuenta.activa is False


def test_seed_no_reemplaza_login_tecnico_de_otra_identidad(session: Session) -> None:
    intrusa = Cuenta(
        identificador_login="demo-tecnica-ayuda-sin-fronteras",
        password_hash=generar_password_hash("administrativa-123"),
        rol=RolNacional.ADMIN_NACIONAL,
    )
    session.add(intrusa)
    session.commit()
    with pytest.raises(ValueError, match="otra cuenta nacional"):
        seed_development_data(session)
    session.refresh(intrusa)
    assert intrusa.rol == RolNacional.ADMIN_NACIONAL and intrusa.ong_id is None
