"""Identidad administrativa común a los escenarios demo y masivo."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generar_password_hash
from app.db.models import Cuenta, RolNacional

ADMIN_DEMO_ID = uuid5(NAMESPACE_URL, "rescuesync-demo:admin:nacional")
ADMIN_DEMO_LOGIN = "admin.nacional.demo@rescuesync.org"
ADMIN_DEMO_PASSWORD = "admin-nacional-demo123"


def asegurar_admin_demo(session: Session) -> tuple[Cuenta, bool]:
    """Crea la cuenta faltante sin rotar ni reactivar una identidad existente."""
    if get_settings().app_env not in {"development", "test"}:
        raise ValueError("El seed sólo está disponible en desarrollo y pruebas.")
    # El administrador es compartido incluso entre cargas con distinto --seed.
    session.execute(select(func.pg_advisory_xact_lock(73843, -1)))
    admin = session.scalar(
        select(Cuenta).where(Cuenta.identificador_login == ADMIN_DEMO_LOGIN)
    )
    creado = admin is None
    if admin is None:
        if session.get(Cuenta, ADMIN_DEMO_ID) is not None:
            raise ValueError("La identidad administrativa demo tiene otro login.")
        admin = Cuenta(
            id=ADMIN_DEMO_ID,
            identificador_login=ADMIN_DEMO_LOGIN,
            password_hash=generar_password_hash(ADMIN_DEMO_PASSWORD),
            rol=RolNacional.ADMIN_NACIONAL,
        )
        session.add(admin)
        session.flush()
    if (
        admin.id != ADMIN_DEMO_ID
        or admin.rol != RolNacional.ADMIN_NACIONAL
        or not admin.activa
    ):
        raise ValueError(
            "La identidad administrativa demo no coincide o está inactiva."
        )
    return admin, creado
