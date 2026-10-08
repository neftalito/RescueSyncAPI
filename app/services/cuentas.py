"""Autenticación y alta atómica de cuenta e institución nacional."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import generar_password_hash, verificar_password
from app.db.models import Cuenta, Ong, RolNacional
from app.schemas.inventario import OngCreate


class CuentaDuplicadaError(ValueError):
    """El login o identificador institucional ya está registrado."""


def autenticar(session: Session, login: str, password: str) -> Cuenta | None:
    """Verifica las credenciales sin revelar qué identificadores existen."""

    cuenta = session.scalar(select(Cuenta).where(Cuenta.identificador_login == login))
    verificada = verificar_password(password, cuenta.password_hash if cuenta else None)
    return cuenta if cuenta is not None and cuenta.activa and verificada else None


def registrar_ong(session: Session, datos: OngCreate) -> Ong:
    """Crea una ONG pendiente y una cuenta sin habilitarla ni certificarla."""

    ong = Ong(
        nombre=datos.nombre,
        identificador_institucional=datos.identificador_institucional,
        email_contacto=str(datos.email_contacto),
    )
    try:
        session.add(ong)
        session.flush()
        session.add(
            Cuenta(
                identificador_login=datos.identificador_login,
                password_hash=generar_password_hash(datos.password.get_secret_value()),
                rol=RolNacional.ONG,
                ong_id=ong.id,
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise CuentaDuplicadaError from error
    session.refresh(ong)
    return ong
