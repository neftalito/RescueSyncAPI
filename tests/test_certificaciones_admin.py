"""Carga administrativa, historial, repetición y concurrencia en PostgreSQL real."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from test_database_models import crear_datos

from app.core.config import get_settings
from app.core.security import generar_password_hash
from app.db.models import (
    Certificacion,
    Cuenta,
    EstadoOng,
    OngCertificacion,
    RolNacional,
)
from app.schemas.certificaciones import (
    AcreditacionCreate,
    AlcanceCreate,
    CertificacionCreate,
    RevocacionRequest,
)
from app.scripts import certificaciones as cli
from app.scripts.bootstrap_admin import CuentaAdminCreate, crear_administrador
from app.scripts.seed import seed_development_data
from app.services.certificaciones import (
    AdministracionDenegadaError,
    CertificacionConflictivaError,
    CertificacionNoEncontradaError,
    consultar_certificaciones_ong,
    habilitar_ong,
    otorgar_acreditacion,
    publicar_certificacion,
    revocar_acreditacion,
)


def test_otorgar_renovar_revocar_preservan_historia(session: Session) -> None:
    datos = crear_datos(session, uuid4().hex)
    ahora = datetime.now(UTC)
    entrada = AcreditacionCreate(
        ong_id=datos.ong.id,
        certificacion_id=datos.certificacion.id,
        emisor="Autoridad",
        numero_credencial="renovacion-2",
        vigente_desde=ahora,
        vigente_hasta=ahora + timedelta(days=365),
    )
    id_nueva = otorgar_acreditacion(session, datos.admin.id, entrada)
    session.commit()
    assert otorgar_acreditacion(session, datos.admin.id, entrada) == id_nueva
    with pytest.raises(CertificacionConflictivaError):
        otorgar_acreditacion(
            session,
            datos.admin.id,
            entrada.model_copy(
                update={
                    "vigente_hasta": ahora + timedelta(days=366),
                }
            ),
        )
    anterior = datos.acreditacion.vigente_hasta
    revocacion = RevocacionRequest(
        ong_id=datos.ong.id, acreditacion_id=id_nueva, motivo="Verificación anulada"
    )
    revocar_acreditacion(session, datos.admin.id, revocacion)
    session.commit()
    nueva = session.get(OngCertificacion, id_nueva)
    assert nueva is not None
    fecha = nueva.revocada_en
    assert revocar_acreditacion(session, datos.admin.id, revocacion) == id_nueva
    session.commit()
    assert nueva.revocada_en == fecha and nueva.revocada_por_id == datos.admin.id
    assert nueva.registrada_por_id == datos.admin.id
    assert datos.acreditacion.vigente_hasta == anterior
    assert len(consultar_certificaciones_ong(session, datos.ong.id).acreditaciones) == 2
    with pytest.raises(CertificacionConflictivaError):
        revocar_acreditacion(
            session, datos.admin.id, revocacion.model_copy(update={"motivo": "Otro"})
        )


def test_ong_e_integracion_no_pueden_autoadministrarse(session: Session) -> None:
    datos = crear_datos(session, uuid4().hex)
    ong = Cuenta(
        identificador_login=f"ong-{uuid4()}",
        rol=RolNacional.ONG,
        ong_id=datos.ong.id,
        password_hash="$argon2id$hash-de-prueba",
    )
    session.add(ong)
    session.commit()
    entrada = AcreditacionCreate(
        ong_id=datos.ong.id,
        certificacion_id=datos.certificacion.id,
        emisor="Autoridad",
        numero_credencial="ilegitima",
        vigente_desde=datetime.now(UTC),
        vigente_hasta=datetime.now(UTC) + timedelta(days=1),
    )
    for cuenta in (ong, datos.integracion):
        with pytest.raises(AdministracionDenegadaError):
            otorgar_acreditacion(session, cuenta.id, entrada)
        with pytest.raises(AdministracionDenegadaError):
            habilitar_ong(session, cuenta.id, datos.ong.id)
        with pytest.raises(AdministracionDenegadaError):
            revocar_acreditacion(
                session,
                cuenta.id,
                RevocacionRequest(
                    ong_id=datos.ong.id,
                    acreditacion_id=datos.acreditacion.id,
                    motivo="Sin permiso",
                ),
            )
    datos.admin.activa = False
    session.commit()
    with pytest.raises(AdministracionDenegadaError):
        otorgar_acreditacion(session, datos.admin.id, entrada)


def test_publicacion_atomica_repeticion_y_referencias(session: Session) -> None:
    datos = crear_datos(session, uuid4().hex)
    entrada = CertificacionCreate(
        codigo="NUEVA",
        revision=1,
        nombre="Nueva",
        alcances=[
            AlcanceCreate(capacidad_id=datos.capacidad.id, riesgo_maximo="MEDIA")
        ],
    )
    referencia = publicar_certificacion(session, datos.admin.id, entrada)
    session.commit()
    assert publicar_certificacion(session, datos.admin.id, entrada) == referencia
    with pytest.raises(CertificacionConflictivaError):
        publicar_certificacion(
            session, datos.admin.id, entrada.model_copy(update={"nombre": "Otra"})
        )
    invalida = CertificacionCreate(
        codigo="INEXISTENTE",
        revision=1,
        nombre="Inválida",
        alcances=[AlcanceCreate(capacidad_id=uuid4(), riesgo_maximo="BAJA")],
    )
    with pytest.raises(CertificacionNoEncontradaError):
        publicar_certificacion(session, datos.admin.id, invalida)
    session.rollback()
    assert (
        session.scalar(
            select(Certificacion.id).where(Certificacion.codigo == "INEXISTENTE")
        )
        is None
    )
    for alcances in ([], [entrada.alcances[0], entrada.alcances[0]]):
        with pytest.raises(ValidationError):
            CertificacionCreate(
                codigo="MAL", revision=1, nombre="Inválida", alcances=alcances
            )


def test_habilitar_no_reactiva_suspensiones(session: Session) -> None:
    datos = crear_datos(session, uuid4().hex)
    datos.ong.estado = EstadoOng.PENDIENTE
    session.commit()
    habilitar_ong(session, datos.admin.id, datos.ong.id)
    session.commit()
    fecha = datos.ong.habilitada_en
    habilitar_ong(session, datos.admin.id, datos.ong.id)
    session.commit()
    assert datos.ong.habilitada_en == fecha
    datos.ong.estado = EstadoOng.SUSPENDIDA
    session.commit()
    with pytest.raises(CertificacionConflictivaError):
        habilitar_ong(session, datos.admin.id, datos.ong.id)


def test_bootstrap_no_eleva_cuentas_existentes(session: Session) -> None:
    datos = CuentaAdminCreate(
        login=" Admin@Example.org ", password=SecretStr("contraseña-larga123")
    )
    cuenta = crear_administrador(session, datos)
    session.commit()
    assert (
        cuenta.rol == RolNacional.ADMIN_NACIONAL
        and cuenta.identificador_login == "admin@example.org"
    )
    hash_anterior = cuenta.password_hash
    with pytest.raises(ValueError):
        crear_administrador(session, datos)
    assert cuenta.password_hash == hash_anterior
    with pytest.raises(ValidationError):
        CuentaAdminCreate(login="otro", password=SecretStr("corta"))


def test_cli_confirma_y_rechaza_password_y_campos_extra(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    datos = crear_datos(session, uuid4().hex)
    datos.admin.password_hash = generar_password_hash("password-admin123")
    session.commit()
    archivo = tmp_path / "habilitacion.json"
    archivo.write_text('{"ongId": "' + str(datos.ong.id) + '"}')

    def factory() -> Session:
        return Session(
            bind=session.connection(), join_transaction_mode="create_savepoint"
        )

    monkeypatch.setattr(cli, "SessionLocal", factory)
    monkeypatch.setattr(cli, "getpass", lambda _: "password-admin123")
    argumentos = [
        "--login",
        datos.admin.identificador_login,
        "habilitar-ong",
        "--archivo",
        str(archivo),
    ]
    assert cli.main(argumentos) == 0
    assert "Operación confirmada" in capsys.readouterr().out
    monkeypatch.setattr(cli, "getpass", lambda _: "password-incorrecto")
    assert cli.main(argumentos) == 1
    salida = capsys.readouterr().out
    assert "password-incorrecto" not in salida and "Credenciales" in salida
    archivo.write_text('{"ongId": "inválido", "habilitadaPorId": "inyección"}')
    assert cli.main(argumentos) == 1
    assert "inyección" not in capsys.readouterr().out


def test_seed_conserva_fechas_y_revocaciones_y_rechaza_produccion(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_development_data(session)
    session.commit()
    antes = session.execute(
        select(
            OngCertificacion.id,
            OngCertificacion.vigente_desde,
            OngCertificacion.vigente_hasta,
            OngCertificacion.revocada_en,
        )
    ).all()
    seed_development_data(session)
    session.commit()
    despues = session.execute(
        select(
            OngCertificacion.id,
            OngCertificacion.vigente_desde,
            OngCertificacion.vigente_hasta,
            OngCertificacion.revocada_en,
        )
    ).all()
    assert antes == despues and len(antes) == 5
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ValueError):
        seed_development_data(session)
    assert session.scalar(select(func.count()).select_from(OngCertificacion)) == 5


def test_otorgamiento_concurrente_reutiliza_una_credencial(
    engine_migrado: Engine,
) -> None:
    with Session(engine_migrado) as db:
        datos = crear_datos(db, uuid4().hex)
        db.commit()
        cuenta_id = datos.admin.id
        entrada = AcreditacionCreate(
            ong_id=datos.ong.id,
            certificacion_id=datos.certificacion.id,
            emisor="Concurrente",
            numero_credencial="misma-clave",
            vigente_desde=datetime.now(UTC),
            vigente_hasta=datetime.now(UTC) + timedelta(days=365),
        )
    barrera = Barrier(2)

    def otorgar() -> UUID:
        with Session(engine_migrado) as db:
            barrera.wait(timeout=5)
            referencia = otorgar_acreditacion(db, cuenta_id, entrada)
            db.commit()
            return referencia

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(lambda _: otorgar(), range(2)))
    assert resultados[0] == resultados[1]
    with Session(engine_migrado) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OngCertificacion)
                .where(
                    OngCertificacion.ong_id == entrada.ong_id,
                    OngCertificacion.numero_credencial == "misma-clave",
                )
            )
            == 1
        )


def test_publicacion_concurrente_reutiliza_revision_completa(
    engine_migrado: Engine,
) -> None:
    with Session(engine_migrado) as db:
        datos = crear_datos(db, uuid4().hex)
        db.commit()
        cuenta_id = datos.admin.id
        entrada = CertificacionCreate(
            codigo=f"CONCURRENTE-{uuid4().hex}",
            revision=1,
            nombre="Concurrente",
            alcances=[
                AlcanceCreate(capacidad_id=datos.capacidad.id, riesgo_maximo="ALTA")
            ],
        )
    barrera = Barrier(2)

    def publicar() -> UUID:
        with Session(engine_migrado) as db:
            barrera.wait(timeout=5)
            referencia = publicar_certificacion(db, cuenta_id, entrada)
            db.commit()
            return referencia

    with ThreadPoolExecutor(max_workers=2) as executor:
        resultados = list(executor.map(lambda _: publicar(), range(2)))
    assert resultados[0] == resultados[1]
    with Session(engine_migrado) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Certificacion)
                .where(
                    Certificacion.codigo == entrada.codigo,
                )
            )
            == 1
        )
