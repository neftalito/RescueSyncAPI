"""Prepara una cuenta de integración por instalación mediante acceso al entorno."""

import argparse
from collections.abc import Sequence
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import generar_password_hash
from app.db.models import Cuenta, RolNacional, SistemaOrigen
from app.db.session import SessionLocal
from app.scripts.bootstrap_admin import CuentaAdminCreate


def crear_integracion(
    session: Session,
    datos: CuentaAdminCreate,
    codigo_origen: str,
) -> Cuenta:
    """Crea una identidad nueva; no reemplaza contraseñas ni reactiva emisores."""
    codigo = codigo_origen.strip()
    if not codigo or len(codigo) > 80:
        raise ValueError(
            "El código del sistema de origen debe tener entre 1 y 80 caracteres."
        )
    login = datos.login.strip().lower()
    if not login or session.scalar(
        select(Cuenta.id).where(Cuenta.identificador_login == login)
    ):
        raise ValueError(
            "El login está vacío o ya existe; no se modificó ninguna cuenta."
        )
    origen = session.scalar(
        select(SistemaOrigen).where(SistemaOrigen.codigo == codigo).with_for_update()
    )
    if origen is None:
        origen = SistemaOrigen(codigo=codigo, nombre=codigo)
        session.add(origen)
        session.flush()
    if not origen.activo:
        raise ValueError(
            "El sistema de origen está inactivo; requiere revisión administrativa."
        )
    cuenta = Cuenta(
        identificador_login=login,
        password_hash=generar_password_hash(datos.password.get_secret_value()),
        rol=RolNacional.INTEGRACION,
        sistema_origen_id=origen.id,
    )
    session.add(cuenta)
    session.flush()
    return cuenta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", required=True)
    parser.add_argument("--sistema-origen", required=True)
    args = parser.parse_args(argv)
    try:
        datos = CuentaAdminCreate(
            login=args.login,
            password=getpass("Contraseña de integración (mínimo 12 caracteres): "),
        )
        with SessionLocal() as session:
            crear_integracion(session, datos, args.sistema_origen)
            session.commit()
        print(
            "Cuenta de integración creada. "
            "Configurá su login y contraseña en el backend local."
        )
        return 0
    except ValueError:
        print(
            "No se creó la cuenta. Revisá login, contraseña y sistema de origen; "
            "no se reemplazan identidades."
        )
    except SQLAlchemyError:
        print("No se creó la cuenta. Revisá la conexión y las identidades existentes.")
    except (EOFError, KeyboardInterrupt):
        print("Operación cancelada.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
