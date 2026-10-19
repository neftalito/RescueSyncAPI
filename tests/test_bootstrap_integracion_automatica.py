"""Pruebas de aprovisionamiento idempotente antes del arranque cloud."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generar_password_hash
from app.db.models import Cuenta, RolNacional, SistemaOrigen
from app.scripts.bootstrap_admin import CuentaAdminCreate
from app.scripts.bootstrap_integracion_automatica import (
    asegurar_integracion,
    configuracion_integracion,
    main,
)

LOGIN = "integracion-rescuesync"
PASSWORD = "clave-segura-render-mvp-2026"
ORIGEN = "rescuesync-local"


def _datos(password: str = PASSWORD) -> CuentaAdminCreate:
    return CuentaAdminCreate(login=LOGIN, password=password)


def test_no_habilita_bootstrap_automatico_sin_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INTEGRACION_AUTO_BOOTSTRAP", raising=False)
    assert configuracion_integracion() is None


def test_bootstrap_activo_exige_contrasena(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTEGRACION_AUTO_BOOTSTRAP", "true")
    monkeypatch.delenv("INTEGRACION_PASSWORD", raising=False)
    assert main() == 1


def test_configuracion_usa_login_y_origen_por_defecto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INTEGRACION_AUTO_BOOTSTRAP", "true")
    monkeypatch.setenv("INTEGRACION_PASSWORD", PASSWORD)
    monkeypatch.delenv("INTEGRACION_LOGIN", raising=False)
    monkeypatch.delenv("INTEGRACION_SISTEMA_ORIGEN", raising=False)
    configuracion = configuracion_integracion()
    assert configuracion is not None
    datos, origen = configuracion
    assert datos.login == LOGIN
    assert origen == ORIGEN


def test_aprovisionamiento_es_idempotente(session: Session) -> None:
    assert asegurar_integracion(session, _datos(), ORIGEN)
    cuenta = session.scalar(
        select(Cuenta).where(Cuenta.identificador_login == LOGIN)
    )
    assert cuenta is not None and cuenta.rol == RolNacional.INTEGRACION
    origen = session.get(SistemaOrigen, cuenta.sistema_origen_id)
    assert origen is not None and origen.codigo == ORIGEN
    estado = (cuenta.id, cuenta.password_hash, cuenta.version_credencial)
    assert not asegurar_integracion(session, _datos(), ORIGEN)
    session.refresh(cuenta)
    assert (cuenta.id, cuenta.password_hash, cuenta.version_credencial) == estado


def test_no_rota_contrasena_que_no_coincide(session: Session) -> None:
    asegurar_integracion(session, _datos(), ORIGEN)
    cuenta = session.scalar(
        select(Cuenta).where(Cuenta.identificador_login == LOGIN)
    )
    assert cuenta is not None
    hash_anterior = cuenta.password_hash
    with pytest.raises(ValueError, match="no coincide"):
        asegurar_integracion(session, _datos("otra-clave-distinta-2026"), ORIGEN)
    assert cuenta.password_hash == hash_anterior


def test_rechaza_cuenta_inactiva(session: Session) -> None:
    asegurar_integracion(session, _datos(), ORIGEN)
    cuenta = session.scalar(
        select(Cuenta).where(Cuenta.identificador_login == LOGIN)
    )
    assert cuenta is not None
    cuenta.activa = False
    session.flush()
    with pytest.raises(ValueError, match="inactiva"):
        asegurar_integracion(session, _datos(), ORIGEN)


def test_rechaza_sistema_origen_diferente(session: Session) -> None:
    asegurar_integracion(session, _datos(), ORIGEN)
    with pytest.raises(ValueError, match="no coincide"):
        asegurar_integracion(session, _datos(), "otro-emisor")


def test_no_sobrescribe_identidad_de_otro_rol(session: Session) -> None:
    session.add(
        Cuenta(
            identificador_login=LOGIN,
            password_hash=generar_password_hash(PASSWORD),
            rol=RolNacional.ADMIN_NACIONAL,
        )
    )
    session.flush()
    with pytest.raises(ValueError, match="no coincide"):
        asegurar_integracion(session, _datos(), ORIGEN)
