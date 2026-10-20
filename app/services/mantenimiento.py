"""Ejecuta mantenimiento nacional atómico y serializado entre réplicas."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import Base
from app.db.catalogo_base import restaurar_catalogo_base
from app.scripts.seed import seed_development_data
from app.scripts.seed_admin import asegurar_admin_demo
from app.scripts.seed_masivo import ConfiguracionSeed, ResultadoSeed, seed_mass_data


@contextmanager
def transaccion_mantenimiento(session: Session) -> Iterator[None]:
    """Serializa los tres endpoints y revierte toda escritura ante un fallo."""
    settings = get_settings()
    try:
        session.execute(
            text("SELECT set_config('lock_timeout', :valor, true)"),
            {"valor": f"{settings.operacion_lock_timeout_ms}ms"},
        )
        session.execute(
            text("SELECT set_config('statement_timeout', :valor, true)"),
            {"valor": f"{settings.operacion_statement_timeout_ms}ms"},
        )
        session.execute(select(func.pg_advisory_xact_lock(73844, 0)))
        yield
        session.commit()
    except (ValueError, SQLAlchemyError):
        session.rollback()
        raise


def cargar_seed(session: Session) -> None:
    """Restaura referencias faltantes y carga el escenario pequeño y su admin."""
    with transaccion_mantenimiento(session):
        restaurar_catalogo_base(session)
        asegurar_admin_demo(session, permitir_produccion=True)
        seed_development_data(session, permitir_produccion=True)


def cargar_seed_masivo(session: Session, config: ConfiguracionSeed) -> ResultadoSeed:
    """Confirma el escenario masivo completo antes de devolver filas agregadas."""
    with transaccion_mantenimiento(session):
        restaurar_catalogo_base(session)
        resultado = seed_mass_data(session, config, permitir_produccion=True)
    return resultado


def vaciar_base(session: Session) -> None:
    """Vacía todas las tablas de la aplicación; conserva esquema y Alembic."""
    with transaccion_mantenimiento(session):
        preparador = session.get_bind().dialect.identifier_preparer
        tablas = ", ".join(
            preparador.format_table(tabla)
            for tabla in sorted(Base.metadata.tables.values(), key=lambda t: t.name)
        )
        # Lista exclusiva de metadata: no acepta identificadores del cliente ni
        # CASCADE que pudiera alcanzar tablas de otro sistema por una FK externa.
        session.execute(text(f"TRUNCATE TABLE {tablas} RESTART IDENTITY"))
