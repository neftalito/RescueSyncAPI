"""Escenario nacional reproducible vinculado al seed de RescueSync."""

from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generar_password_hash
from app.db.models import (
    Capacidad,
    Cuenta,
    Ong,
    PropositoCuenta,
    Recurso,
    RolNacional,
)
from app.db.session import SessionLocal


def _cuenta_tecnica_demo(session: Session, ong_id: UUID, referencia: str) -> None:
    """Agrega la identidad técnica demo sin rotar ni reactivar una existente."""
    cuenta_id = uuid5(NAMESPACE_URL, f"rescuesync-demo:cuenta-tecnica:{referencia}")
    login = f"demo-tecnica-{referencia}"
    cuenta = session.scalar(
        select(Cuenta).where(
            Cuenta.ong_id == ong_id,
            Cuenta.proposito == PropositoCuenta.TECNICA_ONG,
        )
    )
    if cuenta is not None:
        if (
            cuenta.id != cuenta_id
            or cuenta.identificador_login != login
            or cuenta.rol != RolNacional.ONG
        ):
            raise ValueError(
                "La ONG demo tiene otra cuenta técnica; no se reemplazó su acceso."
            )
        return
    if (
        session.get(Cuenta, cuenta_id) is not None
        or session.scalar(select(Cuenta.id).where(Cuenta.identificador_login == login))
        is not None
    ):
        raise ValueError(
            "La identidad técnica demo ya pertenece a otra cuenta nacional."
        )
    # Credencial pública exclusiva de development/test, coordinada con el seed local.
    secreto = f"demo-only-rescuesync-tecnica:{referencia}:2026"
    session.add(
        Cuenta(
            id=cuenta_id,
            identificador_login=login,
            ong_id=ong_id,
            password_hash=generar_password_hash(secreto),
            rol=RolNacional.ONG,
            proposito=PropositoCuenta.TECNICA_ONG,
        )
    )
    session.flush()


def seed_development_data(session: Session) -> None:
    """Agrega datos faltantes sin resetear contraseñas, stock ni compromisos."""

    if get_settings().app_env not in {"development", "test"}:
        raise ValueError("El seed sólo está disponible en desarrollo y pruebas.")
    # Las migraciones instalan el catálogo común también en producción.
    codigos_demo = {"AGUA", "PARAMEDICOS", "AMBULANCIAS"}
    capacidades = {
        capacidad.codigo: capacidad
        for capacidad in session.scalars(
            select(Capacidad).where(Capacidad.codigo.in_(codigos_demo))
        )
    }
    if capacidades.keys() != codigos_demo:
        raise ValueError("Falta el catálogo base; ejecutar alembic upgrade head.")

    for referencia, nombre, login, password, recursos in (
        (
            "ayuda-sin-fronteras",
            "Ayuda Sin Fronteras",
            "ong@rescuesync.org",
            "ong-nacional123",
            (
                ("AGUA", "AGUA-01", "Agua embotellada", "5000"),
                ("PARAMEDICOS", "PERSONAL-01", "Equipo sanitario", "12"),
            ),
        ),
        (
            "red-medica-solidaria",
            "Red Médica Solidaria",
            "redmedica@rescuesync.org",
            "redmedica123",
            (
                ("AMBULANCIAS", "AMB-01", "Ambulancias de rescate", "4"),
                ("PARAMEDICOS", "PERSONAL-01", "Equipo de paramédicos", "20"),
            ),
        ),
    ):
        ong_id = uuid5(NAMESPACE_URL, f"rescuesync-demo:ong:{referencia}")
        ong = session.get(Ong, ong_id)
        if ong is None:
            # Una identidad existente nunca se sustituye por la identidad del seed.
            if (
                session.scalar(
                    select(Ong.id).where(
                        Ong.identificador_institucional == f"demo:{referencia}"
                    )
                )
                is not None
            ):
                raise ValueError("La institución demo ya existe con otro UUID.")
            ong = Ong(
                id=ong_id,
                nombre=nombre,
                identificador_institucional=f"demo:{referencia}",
                email_contacto=login,
            )
            session.add(ong)
            session.flush()
        cuenta = session.scalar(
            select(Cuenta).where(Cuenta.identificador_login == login)
        )
        if cuenta is None:
            session.add(
                Cuenta(
                    identificador_login=login,
                    password_hash=generar_password_hash(password),
                    rol=RolNacional.ONG,
                    ong_id=ong_id,
                )
            )
        elif cuenta.ong_id != ong_id or cuenta.rol != RolNacional.ONG:
            raise ValueError("El login demo pertenece a otra identidad nacional.")
        _cuenta_tecnica_demo(session, ong_id, referencia)
        for codigo, codigo_interno, recurso_nombre, total in recursos:
            if (
                session.scalar(
                    select(Recurso.id).where(
                        Recurso.ong_id == ong_id,
                        Recurso.codigo_interno == codigo_interno,
                    )
                )
                is None
            ):
                session.add(
                    Recurso(
                        ong_id=ong_id,
                        capacidad_id=capacidades[codigo].id,
                        codigo_interno=codigo_interno,
                        nombre=recurso_nombre,
                        cantidad_total=Decimal(total),
                    )
                )
        session.flush()


def main() -> int:
    """Carga datos demo sin realizar llamadas a RescueSync ni publicar secretos."""

    if get_settings().app_env not in {"development", "test"}:
        print("El seed no puede ejecutarse en este entorno.")
        return 1
    with SessionLocal.begin() as session:
        seed_development_data(session)
    print("Seed nacional listo: dos ONGs, cuentas técnicas, e inventario demo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
