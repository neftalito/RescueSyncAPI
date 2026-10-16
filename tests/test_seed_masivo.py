"""Ejercita la carga aditiva y sus restricciones con migraciones reales."""

from dataclasses import asdict, replace
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_catalogo import catalogo_client as catalogo_client_fixture

from app.core.config import get_settings
from app.core.security import generar_password_hash, verificar_password
from app.db.models import (
    Capacidad,
    Cuenta,
    Ong,
    OngCertificacion,
    PropositoCuenta,
    Recurso,
    RolNacional,
)
from app.scripts.seed_masivo import ConfiguracionSeed, main, seed_mass_data

CONFIG = ConfiguracionSeed(seed=17041, ongs=5, recursos_por_ong=7, batch_size=3)
catalogo_client = catalogo_client_fixture


def test_repetir_no_duplica_ni_restaura_stock_o_credenciales(session: Session) -> None:
    catalogo = session.execute(
        select(Capacidad.__table__).order_by(Capacidad.codigo)
    ).all()
    primero = seed_mass_data(session, CONFIG)
    assert asdict(primero) == {
        "ongs": 5,
        "cuentas": 11,
        "recursos": 35,
        "acreditaciones": 5,
    }
    recurso = session.get(
        Recurso, uuid5(NAMESPACE_URL, f"rescuesync-masivo:{CONFIG.seed}:recurso:1:1")
    )
    cuenta = session.get(
        Cuenta,
        uuid5(NAMESPACE_URL, f"rescuesync-masivo:{CONFIG.seed}:cuenta-tecnica:1"),
    )
    assert recurso is not None and cuenta is not None
    recurso.cantidad_total = Decimal(17)
    cuenta.password_hash = generar_password_hash("credencial-rotada-123")
    cuenta.activa = False
    cuenta.version_credencial += 1
    credencial = (cuenta.password_hash, cuenta.version_credencial)
    acreditacion = session.scalar(
        select(OngCertificacion).where(OngCertificacion.ong_id == cuenta.ong_id)
    )
    assert acreditacion is not None
    fechas = (acreditacion.vigente_desde, acreditacion.vigente_hasta)
    session.flush()

    repetido = seed_mass_data(session, replace(CONFIG, batch_size=2))

    assert all(valor == 0 for valor in asdict(repetido).values())
    assert recurso.cantidad_total == 17
    assert (
        not cuenta.activa
        and (cuenta.password_hash, cuenta.version_credencial) == credencial
    )
    assert (acreditacion.vigente_desde, acreditacion.vigente_hasta) == fechas
    assert (
        session.execute(select(Capacidad.__table__).order_by(Capacidad.codigo)).all()
        == catalogo
    )


def test_ampliar_cantidad_de_ongs_y_recursos_agrega_solo_faltantes(
    session: Session,
) -> None:
    seed_mass_data(session, CONFIG)
    ampliado = seed_mass_data(session, replace(CONFIG, ongs=7, recursos_por_ong=9))
    assert asdict(ampliado) == {
        "ongs": 2,
        "cuentas": 4,
        "recursos": 28,
        "acreditaciones": 2,
    }
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert session.scalar(select(func.count()).select_from(Recurso)) == 63


def test_cuentas_y_recursos_coinciden_con_el_contrato_local(session: Session) -> None:
    seed_mass_data(session, CONFIG)
    ong_id = uuid5(NAMESPACE_URL, f"rescuesync-masivo:{CONFIG.seed}:ong:1")
    cuenta_id = uuid5(
        NAMESPACE_URL, f"rescuesync-masivo:{CONFIG.seed}:cuenta-tecnica:1"
    )
    cuenta = session.get(Cuenta, cuenta_id)
    assert cuenta is not None and cuenta.ong_id == ong_id
    assert cuenta.proposito == PropositoCuenta.TECNICA_ONG
    assert cuenta.identificador_login == f"masivo-{CONFIG.seed}-tecnica-1"
    assert verificar_password("CargaMasivaTecnica2026!", cuenta.password_hash)
    recurso = session.get(
        Recurso, uuid5(NAMESPACE_URL, f"rescuesync-masivo:{CONFIG.seed}:recurso:1:1")
    )
    assert recurso is not None and recurso.ong_id == ong_id
    assert recurso.capacidad_id == uuid5(NAMESPACE_URL, "rescuesync:capacidad:AGUA")
    assert recurso.cantidad_total > 0


def test_no_reemplaza_una_cuenta_que_ocupa_el_login(session: Session) -> None:
    intrusa = Cuenta(
        id=uuid4(),
        identificador_login=f"masivo-{CONFIG.seed}-tecnica-1",
        rol=RolNacional.ADMIN_NACIONAL,
        password_hash=generar_password_hash("intrusa123"),
    )
    session.add(intrusa)
    session.flush()
    with pytest.raises(ValueError, match="otra identidad"):
        with session.begin_nested():
            seed_mass_data(session, CONFIG)
    assert intrusa.rol == RolNacional.ADMIN_NACIONAL and intrusa.ong_id is None
    assert session.scalar(select(func.count()).select_from(Ong)) == 0


def test_error_revierte_la_carga_entera(session: Session) -> None:
    with pytest.raises(RuntimeError, match="fallo de prueba"):
        with session.begin_nested():
            seed_mass_data(session, CONFIG)
            raise RuntimeError("fallo de prueba")
    assert session.scalar(select(func.count()).select_from(Ong)) == 0
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 0
    assert session.scalar(select(func.count()).select_from(Recurso)) == 0


def test_produccion_se_rechaza_antes_de_escribir(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ValueError, match="desarrollo y pruebas"):
        seed_mass_data(session, CONFIG)
    assert main(["--dry-run"]) == 1
    assert session.scalar(select(func.count()).select_from(Cuenta)) == 0


@pytest.mark.parametrize(
    "opciones",
    [
        {"ongs": 0},
        {"recursos_por_ong": 3},
        {"batch_size": 0},
        {"batch_size": 1001},
        {"seed": -1},
    ],
)
def test_configuracion_invalida_se_rechaza(opciones: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        replace(CONFIG, **opciones)


def test_simulacion_no_necesita_base(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run", "--ongs", "2000", "--recursos-por-ong", "10"]) == 0
    assert "20000 recursos" in capsys.readouterr().out


def test_masivo_solo_permite_administrar_catalogo_con_credenciales_demo(
    catalogo_client: TestClient,
    session: Session,
) -> None:
    seed_mass_data(session, CONFIG)
    session.flush()
    admin_id = uuid5(NAMESPACE_URL, "rescuesync-demo:admin:nacional")
    admin = session.get(Cuenta, admin_id)
    assert admin is not None
    assert admin.identificador_login == "admin.nacional.demo@rescuesync.org"
    assert admin.rol == RolNacional.ADMIN_NACIONAL
    assert (
        session.scalar(
            select(func.count())
            .select_from(Cuenta)
            .where(Cuenta.rol == RolNacional.ADMIN_NACIONAL)
        )
        == 1
    )
    assert (
        session.scalar(
            select(Cuenta.id).where(
                Cuenta.identificador_login == f"masivo-{CONFIG.seed}-admin@example.test"
            )
        )
        is None
    )
    assert set(session.scalars(select(Ong.habilitada_por_id))) == {admin_id}
    assert set(session.scalars(select(OngCertificacion.registrada_por_id))) == {
        admin_id
    }

    login = catalogo_client.post(
        "/api/v1/login",
        json={
            "identificadorLogin": "admin.nacional.demo@rescuesync.org",
            "password": "admin-nacional-demo123",
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (
        catalogo_client.get("/api/v1/capacidades", headers=headers).status_code == 200
    )
    alta = catalogo_client.post(
        "/api/v1/capacidades",
        headers=headers,
        json={
            "codigo": "PRUEBA_ADMIN_SEED",
            "nombre": "Capacidad de prueba",
            "tipo": "SUMINISTRO",
            "unidad": "litros",
            "admiteFracciones": True,
        },
    )
    assert alta.status_code == 201


def test_repetir_o_cambiar_seed_no_rota_admin_demo(session: Session) -> None:
    seed_mass_data(session, CONFIG)
    admin = session.get(Cuenta, uuid5(NAMESPACE_URL, "rescuesync-demo:admin:nacional"))
    assert admin is not None
    admin.password_hash = generar_password_hash("Clave-rotada-2026")
    admin.version_credencial += 1
    original = (admin.id, admin.password_hash, admin.version_credencial)
    session.flush()

    seed_mass_data(session, CONFIG)
    seed_mass_data(session, replace(CONFIG, seed=CONFIG.seed + 1))

    assert (admin.id, admin.password_hash, admin.version_credencial) == original
    assert (
        session.scalar(
            select(func.count())
            .select_from(Cuenta)
            .where(Cuenta.rol == RolNacional.ADMIN_NACIONAL)
        )
        == 1
    )


def test_admin_demo_inactivo_no_se_reactiva(session: Session) -> None:
    seed_mass_data(session, CONFIG)
    admin = session.get(Cuenta, uuid5(NAMESPACE_URL, "rescuesync-demo:admin:nacional"))
    assert admin is not None
    admin.activa = False
    session.flush()
    with pytest.raises(ValueError, match="inactiva"):
        seed_mass_data(session, CONFIG)
    assert not admin.activa
