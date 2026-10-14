"""Escenario nacional reproducible vinculado al seed de RescueSync."""

from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generar_password_hash
from app.db.models import Capacidad, Cuenta, Ong, Recurso, RolNacional, TipoRecurso
from app.db.session import SessionLocal
from app.scripts.seed_certificaciones import seed_certificaciones


def seed_development_data(session: Session) -> None:
    """Agrega datos faltantes sin resetear contraseñas, stock ni compromisos."""

    if get_settings().app_env not in {"development", "test"}:
        raise ValueError("El seed sólo está disponible en desarrollo y pruebas.")
    capacidades: dict[str, Capacidad] = {}
    for codigo, nombre, tipo, unidad, fracciones in (
        ("AGUA", "Agua potable", TipoRecurso.SUMINISTRO, "litros", True),
        ("PARAMEDICOS", "Personal paramédico", TipoRecurso.PERSONAL, "personas", False),
        ("AMBULANCIAS", "Ambulancias", TipoRecurso.VEHICULO, "vehículos", False),
    ):
        capacidad = session.scalar(select(Capacidad).where(Capacidad.codigo == codigo))
        if capacidad is None:
            capacidad = Capacidad(
                codigo=codigo,
                nombre=nombre,
                tipo=tipo,
                unidad=unidad,
                admite_fracciones=fracciones,
            )
            session.add(capacidad)
            session.flush()
        capacidades[codigo] = capacidad

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

    seed_certificaciones(session)


def main() -> int:
    """Carga datos demo sin realizar llamadas a RescueSync ni publicar secretos."""

    if get_settings().app_env not in {"development", "test"}:
        print("El seed no puede ejecutarse en este entorno.")
        return 1
    with SessionLocal.begin() as session:
        seed_development_data(session)
    print("Seed nacional listo: dos ONGs, inventario y certificaciones de desarrollo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
