"""Carga oficial por operador autenticado; nunca acepta autores del archivo JSON."""

import argparse
from collections.abc import Sequence
from getpass import getpass
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import RolNacional
from app.db.session import SessionLocal
from app.schemas.certificaciones import (
    AcreditacionCreate,
    CertificacionCreate,
    HabilitacionRequest,
    RevocacionRequest,
)
from app.services.certificaciones import (
    AdministracionDenegadaError,
    CertificacionConflictivaError,
    CertificacionNoEncontradaError,
    habilitar_ong,
    otorgar_acreditacion,
    publicar_certificacion,
    revocar_acreditacion,
)
from app.services.cuentas import autenticar


def ejecutar_operacion(session: Session, cuenta_id: UUID, datos: BaseModel) -> UUID:
    """Despacha DTO validados; cada servicio revalida la cuenta bajo lock."""
    match datos:
        case CertificacionCreate():
            return publicar_certificacion(session, cuenta_id, datos)
        case AcreditacionCreate():
            return otorgar_acreditacion(session, cuenta_id, datos)
        case RevocacionRequest():
            return revocar_acreditacion(session, cuenta_id, datos)
        case HabilitacionRequest():
            return habilitar_ong(session, cuenta_id, datos.ong_id)
        case _:
            raise ValueError("Operación administrativa desconocida.")


def main(argv: Sequence[str] | None = None) -> int:
    """Confirma antes de informar éxito y oculta entradas y errores de la base."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", required=True)
    parser.add_argument(
        "operacion", choices=("publicar", "otorgar", "revocar", "habilitar-ong")
    )
    parser.add_argument("--archivo", type=Path, required=True)
    args = parser.parse_args(argv)
    modelos = {
        "publicar": CertificacionCreate,
        "otorgar": AcreditacionCreate,
        "revocar": RevocacionRequest,
        "habilitar-ong": HabilitacionRequest,
    }
    try:
        datos = modelos[args.operacion].model_validate_json(args.archivo.read_bytes())
        password = getpass("Contraseña administrativa nacional: ")
        with SessionLocal() as session:
            cuenta = autenticar(session, args.login.strip().lower(), password)
            if cuenta is None or cuenta.rol != RolNacional.ADMIN_NACIONAL:
                raise AdministracionDenegadaError(
                    "Credenciales administrativas inválidas."
                )
            resultado = ejecutar_operacion(session, cuenta.id, datos)
            session.commit()
        print(f"Operación confirmada. Referencia: {resultado}")
        return 0
    except (
        AdministracionDenegadaError,
        CertificacionConflictivaError,
        CertificacionNoEncontradaError,
    ) as error:
        print(str(error))
    except (OSError, ValidationError):
        print("El archivo no es válido. Revisá campos, referencias y fechas con zona.")
    except (EOFError, KeyboardInterrupt):
        print("Operación cancelada.")
    except SQLAlchemyError:
        print(
            "No se confirmó la operación. "
            "Verificá las referencias y el estado de la base."
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
