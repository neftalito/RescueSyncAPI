"""Aprovisiona una cuenta administrativa faltante por acceso explícito al entorno."""

import argparse
from collections.abc import Sequence
from getpass import getpass

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import generar_password_hash
from app.db.models import Cuenta, RolNacional
from app.db.session import SessionLocal


class CuentaAdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=12, max_length=128)


def crear_administrador(session: Session, datos: CuentaAdminCreate) -> Cuenta:
    """No reemplaza identidades, no cambia roles ni resetea contraseñas existentes."""
    login = datos.login.strip().lower()
    if not login:
        raise ValueError("El identificador administrativo no puede estar vacío.")
    if session.scalar(select(Cuenta.id).where(Cuenta.identificador_login == login)):
        raise ValueError("Ese identificador ya existe; no se modificó ninguna cuenta.")
    cuenta = Cuenta(
        identificador_login=login,
        password_hash=generar_password_hash(datos.password.get_secret_value()),
        rol=RolNacional.ADMIN_NACIONAL,
    )
    session.add(cuenta)
    session.flush()
    return cuenta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", required=True)
    args = parser.parse_args(argv)
    try:
        password = getpass("Nueva contraseña administrativa (mínimo 12 caracteres): ")
        if password != getpass("Repetir contraseña: "):
            print("Las contraseñas no coinciden.")
            return 1
        datos = CuentaAdminCreate(login=args.login, password=SecretStr(password))
        with SessionLocal() as session:
            cuenta = crear_administrador(session, datos)
            session.commit()
            print(f"Cuenta administrativa creada: {cuenta.id}")
        return 0
    except ValidationError:
        print("Revisá el identificador y la longitud de la contraseña.")
    except ValueError as error:
        print(str(error))
    except (EOFError, KeyboardInterrupt):
        print("Operación cancelada.")
    except SQLAlchemyError:
        print(
            "No se confirmó el alta administrativa. "
            "Verificá la base y el identificador."
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
