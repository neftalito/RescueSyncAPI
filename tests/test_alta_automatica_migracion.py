"""La actualización conserva historia y permite revertir sin inventar aprobadores."""

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text


def test_migracion_activa_pendientes_y_conserva_suspensiones_e_historia(
    engine_vacio: Engine,
) -> None:
    raiz = Path(__file__).resolve().parents[1]
    ids = {
        estado: uuid4() for estado in ["PENDIENTE", "HABILITADA", "SUSPENDIDA", "BAJA"]
    }
    admin = uuid4()
    with engine_vacio.begin() as connection:
        config = Config(str(raiz / "alembic.ini"))
        config.set_main_option("script_location", str(raiz / "alembic"))
        config.attributes["connection"] = connection
        command.upgrade(config, "20261015_0005")
        connection.execute(
            text(
                "INSERT INTO cuenta (id, identificador_login, password_hash, rol) "
                "VALUES (:id, 'admin-migracion', '$argon2id$prueba', 'ADMIN_NACIONAL')"
            ),
            {"id": admin},
        )
        for estado, identidad in ids.items():
            connection.execute(
                text(
                    "INSERT INTO ong (id, identificador_institucional, nombre, estado, "
                    "habilitada_en, habilitada_por_id) VALUES (:id, :ref, 'ONG', "
                    "CAST(:estado AS estado_ong), "
                    "CASE WHEN :estado = 'HABILITADA' THEN now() END, :autor)"
                ),
                {
                    "id": identidad,
                    "ref": estado.lower(),
                    "estado": estado,
                    "autor": admin if estado == "HABILITADA" else None,
                },
            )
        command.upgrade(config, "head")
        filas = {r.id: r for r in connection.execute(text("SELECT * FROM ong"))}
        assert filas[ids["PENDIENTE"]].estado == "HABILITADA"
        assert filas[ids["PENDIENTE"]].habilitada_por_id is None
        assert filas[ids["HABILITADA"]].habilitada_por_id == admin
        assert filas[ids["SUSPENDIDA"]].estado == "SUSPENDIDA"
        assert filas[ids["BAJA"]].estado == "BAJA"
        nueva = uuid4()
        connection.execute(
            text(
                "INSERT INTO ong (id, identificador_institucional, nombre) "
                "VALUES (:id, 'alta-automatica', 'Automática')"
            ),
            {"id": nueva},
        )
        assert (
            connection.scalar(
                text("SELECT estado FROM ong WHERE id = :id"), {"id": nueva}
            )
            == "HABILITADA"
        )
        command.downgrade(config, "20261015_0005")
        filas = {r.id: r for r in connection.execute(text("SELECT * FROM ong"))}
        assert filas[nueva].estado == filas[ids["PENDIENTE"]].estado == "PENDIENTE"
        assert filas[ids["HABILITADA"]].habilitada_por_id == admin
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT count(*) FROM ong")) == 5
