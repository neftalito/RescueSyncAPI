"""Crea, rota o revoca la cuenta técnica de una ONG sin imprimir secretos."""

import argparse
import json
import os
from collections.abc import Sequence
from getpass import getpass
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.services.cuentas import autenticar
from app.services.cuentas_tecnicas import administrar_cuenta_tecnica


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", required=True)
    parser.add_argument("operacion", choices=("crear", "rotar", "revocar"))
    parser.add_argument("--ong", type=UUID, required=True)
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args(argv)
    if args.operacion != "revocar" and args.salida is None:
        parser.error("crear y rotar requieren --salida en una carpeta segura")
    creado = False
    try:
        password = getpass("Contraseña administrativa nacional: ")
        with SessionLocal() as session:
            admin = autenticar(session, args.login.strip().lower(), password)
            if admin is None:
                raise ValueError("Credenciales administrativas inválidas.")
            credencial = administrar_cuenta_tecnica(
                session, admin.id, args.ong, args.operacion
            )
            if credencial is not None:
                fd = os.open(args.salida, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                creado = True
                with os.fdopen(fd, "w") as archivo:
                    datos = credencial.model_dump(mode="json", by_alias=True)
                    datos["password"] = credencial.password.get_secret_value()
                    json.dump(datos, archivo)
                    archivo.flush()
                    os.fsync(archivo.fileno())
            session.commit()
        print(
            "Operación confirmada. Transferí el archivo protegido al backend local "
            "y eliminá las copias."
        )
        return 0
    except ValueError as error:
        print(str(error))
    except (OSError, SQLAlchemyError):
        print(
            "No se confirmó la operación. Revisá la base y el archivo de salida; "
            "no se sobrescriben archivos."
        )
    except (EOFError, KeyboardInterrupt):
        print("Operación cancelada.")
    if creado:
        args.salida.unlink(missing_ok=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
