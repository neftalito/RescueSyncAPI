from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.sqlalchemy_database_uri,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session]:
    """Entrega una sesión aislada y garantiza su cierre al terminar la petición."""

    with SessionLocal() as session:
        yield session


def get_db_evaluacion() -> Generator[Session]:
    """Fija un snapshot de sólo lectura antes de autenticar y evaluar ofertas."""
    lectura = engine.execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True
    )
    with Session(bind=lectura, autoflush=False, expire_on_commit=False) as session:
        yield session
