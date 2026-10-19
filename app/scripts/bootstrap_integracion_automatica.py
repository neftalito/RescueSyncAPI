"""Aprovisiona de forma idempotente la cuenta técnica nacional al iniciar."""

import os

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import verificar_password
from app.db.models import Cuenta, RolNacional, SistemaOrigen
from app.db.session import SessionLocal
from app.scripts.bootstrap_admin import CuentaAdminCreate
from app.scripts.bootstrap_integracion import crear_integracion


def configuracion_integracion() -> tuple[CuentaAdminCreate, str] | None:
    """Lee la opción explícita de aprovisionamiento sin exponer el secreto."""

    activado = os.getenv("INTEGRACION_AUTO_BOOTSTRAP", "false").strip().lower()
    if activado not in {"true", "false"}:
        raise ValueError("INTEGRACION_AUTO_BOOTSTRAP debe ser true o false.")
    if activado == "false":
        return None

    password = os.getenv("INTEGRACION_PASSWORD", "")
    if not password:
        raise ValueError(
            "INTEGRACION_PASSWORD es obligatoria cuando se activa el bootstrap."
        )
    datos = CuentaAdminCreate(
        login=os.getenv("INTEGRACION_LOGIN", "integracion-rescuesync"),
        password=password,
    )
    codigo = os.getenv("INTEGRACION_SISTEMA_ORIGEN", "rescuesync-local").strip()
    if not codigo or len(codigo) > 80:
        raise ValueError(
            "INTEGRACION_SISTEMA_ORIGEN debe tener entre 1 y 80 caracteres."
        )
    return datos, codigo


def asegurar_integracion(
    session: Session, datos: CuentaAdminCreate, codigo_origen: str
) -> bool:
    """Crea la identidad faltante; valida una existente sin modificarla.

    Devuelve True sólo cuando se crea una cuenta nueva.
    """

    login = datos.login.strip().lower()
    existente = session.scalar(
        select(Cuenta)
        .where(Cuenta.identificador_login == login)
        .with_for_update()
    )
    if existente is None:
        crear_integracion(session, datos, codigo_origen)
        return True

    origen = (
        session.get(SistemaOrigen, existente.sistema_origen_id)
        if existente.sistema_origen_id is not None
        else None
    )
    if (
        existente.rol != RolNacional.INTEGRACION
        or not existente.activa
        or origen is None
        or not origen.activo
        or origen.codigo != codigo_origen
        or not verificar_password(
            datos.password.get_secret_value(), existente.password_hash
        )
    ):
        raise ValueError(
            "La identidad INTEGRACION existente no coincide con la "
            "configuración o está inactiva; se requiere revisión manual."
        )
    return False


def main() -> int:
    """Ejecuta el bootstrap antes de iniciar la API, sin migrar ni rotar secretos."""

    try:
        configuracion = configuracion_integracion()
        if configuracion is None:
            print("Bootstrap INTEGRACION desactivado.")
            return 0

        datos, codigo_origen = configuracion
        with SessionLocal.begin() as session:
            # Serializa altas de varias réplicas en la misma base PostgreSQL.
            session.execute(text("SELECT pg_advisory_xact_lock(145824, 102026)"))
            creada = asegurar_integracion(session, datos, codigo_origen)
        print(
            "Cuenta INTEGRACION creada correctamente."
            if creada
            else "Cuenta INTEGRACION existente y validada."
        )
        return 0
    except (ValueError, ValidationError):
        print(
            "Bootstrap INTEGRACION fallido: configuración inválida, "
            "credenciales inconsistentes o cuenta inactiva."
        )
    except SQLAlchemyError:
        print(
            "Bootstrap INTEGRACION fallido: no fue posible validar "
            "la cuenta en PostgreSQL."
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
