"""El catálogo de referencia se instala sin datos demo y preserva datos operativos."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

from app.core.config import get_settings


@pytest.fixture
def conexion_catalogo(engine_vacio: Engine) -> Iterator[Connection]:
    """Revierte también el DDL para probar instalaciones independientes."""
    with engine_vacio.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def configuracion(connection: Connection) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.mark.parametrize("entorno", ["development", "production"])
def test_migraciones_instalan_capacidades_sin_cuentas_stock_ni_certificaciones_demo(
    conexion_catalogo: Connection,
    monkeypatch: pytest.MonkeyPatch,
    entorno: str,
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", entorno)
    connection = conexion_catalogo
    config = configuracion(connection)

    command.upgrade(config, "head")

    capacidades = connection.execute(
        text("SELECT * FROM capacidad ORDER BY codigo")
    ).all()
    assert len(capacidades) == 56
    assert {c.tipo for c in capacidades} == {
        "PERSONAL",
        "VEHICULO",
        "EQUIPAMIENTO",
        "SUMINISTRO",
    }
    assert {
        "AGUA",
        "PARAMEDICOS",
        "AMBULANCIAS",
        "MEDICOS",
        "RESCATISTAS_ACUATICOS",
        "CAMIONES_CARGA",
        "GENERADORES",
        "CARPAS",
        "POTABILIZADORES",
        "RADIOS",
        "ALIMENTOS",
        "RACIONES",
        "KITS_HIGIENE",
        "MANTAS",
    } <= {c.codigo for c in capacidades}
    unidades = set(connection.scalars(text("SELECT codigo FROM unidad")))
    assert len(unidades) == 31
    assert all(c.activa and c.unidad in unidades for c in capacidades)
    assert all(
        not c.admite_fracciones
        for c in capacidades
        if c.tipo in {"PERSONAL", "VEHICULO"}
    )
    agua = next(c for c in capacidades if c.codigo == "AGUA")
    assert agua.unidad == "litros" and agua.admite_fracciones
    raciones = next(c for c in capacidades if c.codigo == "RACIONES")
    assert raciones.unidad == "raciones" and not raciones.admite_fracciones
    assert connection.scalar(text("SELECT count(*) FROM cuenta")) == 0
    assert connection.scalar(text("SELECT count(*) FROM ong")) == 0
    assert connection.scalar(text("SELECT count(*) FROM recurso")) == 0
    assert connection.scalar(text("SELECT count(*) FROM certificacion")) == 0
    assert connection.scalar(text("SELECT count(*) FROM certificacion_capacidad")) == 0
    command.upgrade(config, "head")
    assert (
        connection.execute(text("SELECT * FROM capacidad ORDER BY codigo")).all()
        == capacidades
    )


def test_migracion_y_reversion_conservan_identidad_semantica_y_referencias_existentes(
    conexion_catalogo: Connection,
) -> None:
    connection = conexion_catalogo
    config = configuracion(connection)
    command.upgrade(config, "20261015_0004")
    capacidad_id, ong_id = uuid4(), uuid4()
    connection.execute(
        text(
            "INSERT INTO capacidad "
            "(id, codigo, nombre, tipo, unidad, admite_fracciones, activa) "
            "VALUES (:id, 'AGUA', 'Agua en bidones', 'SUMINISTRO', "
            "'bidones', false, false)"
        ),
        {"id": capacidad_id},
    )
    connection.execute(
        text(
            "INSERT INTO ong (id, nombre, identificador_institucional) "
            "VALUES (:id, 'ONG existente', 'prueba:existente')"
        ),
        {"id": ong_id},
    )
    connection.execute(
        text(
            "INSERT INTO recurso "
            "(id, ong_id, capacidad_id, codigo_interno, nombre, cantidad_total) "
            "VALUES (:id, :ong_id, :capacidad_id, 'AGUA-01', 'Bidones de 5 litros', 20)"
        ),
        {"id": uuid4(), "ong_id": ong_id, "capacidad_id": capacidad_id},
    )
    agua_original = connection.execute(
        text("SELECT * FROM capacidad WHERE codigo='AGUA'")
    ).one()

    command.upgrade(config, "head")

    assert (
        connection.execute(text("SELECT * FROM capacidad WHERE codigo='AGUA'")).one()
        == agua_original
    )
    assert connection.scalar(text("SELECT count(*) FROM capacidad")) == 56
    assert connection.scalar(text("SELECT cantidad_total FROM recurso")) == 20
    # Una capacidad instalada por la migración también puede tener stock al revertir.
    connection.execute(
        text(
            "INSERT INTO recurso "
            "(id, ong_id, capacidad_id, codigo_interno, nombre, cantidad_total) "
            "SELECT :id, :ong_id, id, 'CARPAS-01', 'Carpas de campaña', 5 "
            "FROM capacidad WHERE codigo='CARPAS'"
        ),
        {"id": uuid4(), "ong_id": ong_id},
    )
    capacidades = connection.execute(
        text("SELECT * FROM capacidad ORDER BY codigo")
    ).all()
    recursos = connection.execute(text("SELECT * FROM recurso ORDER BY id")).all()

    command.downgrade(config, "20261015_0004")
    assert (
        connection.execute(text("SELECT * FROM capacidad ORDER BY codigo")).all()
        == capacidades
    )
    assert (
        connection.execute(text("SELECT * FROM recurso ORDER BY id")).all() == recursos
    )
    command.upgrade(config, "head")
    assert (
        connection.execute(text("SELECT * FROM capacidad ORDER BY codigo")).all()
        == capacidades
    )
    assert (
        connection.execute(text("SELECT * FROM recurso ORDER BY id")).all() == recursos
    )
