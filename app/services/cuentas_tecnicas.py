"""Aprovisiona accesos institucionales independientes de las cuentas personales."""

from secrets import token_urlsafe
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generar_password_hash
from app.db.models import Cuenta, Ong, PropositoCuenta, RolNacional
from app.schemas.cuentas_tecnicas import CredencialTecnica


def administrar_cuenta_tecnica(
    session: Session, administrador_id: UUID, ong_id: UUID, operacion: str
) -> CredencialTecnica | None:
    """Serializa crear/rotar/revocar; el llamador confirma la transacción."""
    admin = session.scalar(
        select(Cuenta)
        .where(Cuenta.id == administrador_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if admin is None or not admin.activa or admin.rol != RolNacional.ADMIN_NACIONAL:
        raise ValueError("Se requiere una cuenta administrativa nacional activa.")
    if operacion not in {"crear", "rotar", "revocar"}:
        raise ValueError("Operación desconocida.")
    ong = session.scalar(select(Ong).where(Ong.id == ong_id).with_for_update())
    if ong is None:
        raise ValueError("La ONG nacional no existe.")
    cuenta = session.scalar(
        select(Cuenta)
        .where(Cuenta.ong_id == ong_id, Cuenta.proposito == PropositoCuenta.TECNICA_ONG)
        .with_for_update()
    )
    if operacion == "crear" and cuenta is not None:
        raise ValueError(
            "La ONG ya tiene cuenta técnica; usá rotar para reemplazar su secreto."
        )
    if operacion != "crear" and cuenta is None:
        raise ValueError("La ONG no tiene cuenta técnica.")
    if cuenta is None:
        cuenta = Cuenta(
            id=uuid4(),
            identificador_login=f"tecnica-ong-{ong_id}",
            ong_id=ong_id,
            rol=RolNacional.ONG,
            proposito=PropositoCuenta.TECNICA_ONG,
            version_credencial=1,
        )
        session.add(cuenta)
    else:
        cuenta.version_credencial += 1
    if operacion == "revocar":
        cuenta.activa = False
        session.flush()
        return None
    secreto = token_urlsafe(32)
    cuenta.password_hash = generar_password_hash(secreto)
    cuenta.activa = True
    session.flush()
    return CredencialTecnica(
        cuenta_id=cuenta.id,
        ong_id=ong_id,
        identificador_login=cuenta.identificador_login,
        password=SecretStr(secreto),
    )
