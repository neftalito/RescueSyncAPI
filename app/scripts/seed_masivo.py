"""Carga nacional sintética, aditiva e idempotente para pruebas de volumen."""

import argparse
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import batched
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid5

from faker import Faker
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generar_password_hash
from app.db.models import (
    Capacidad,
    Certificacion,
    CertificacionCapacidad,
    Cuenta,
    EstadoOng,
    NivelRiesgo,
    Ong,
    OngCertificacion,
    PropositoCuenta,
    Recurso,
    RolNacional,
)
from app.db.session import SessionLocal
from app.scripts.seed_admin import asegurar_admin_demo

# Mantener este contrato de fixture alineado con el seed masivo local.
PASSWORD_PRUEBA = "CargaMasiva2026!"
PASSWORD_TECNICA = "CargaMasivaTecnica2026!"
CODIGOS_CAPACIDAD = ("AGUA", "RACIONES", "PARAMEDICOS", "AMBULANCIAS")


@dataclass(frozen=True)
class ConfiguracionSeed:
    """Los recursos se amplían por ONG sin reemplazar stock ni credenciales."""

    seed: int = 2026
    ongs: int = 1000
    recursos_por_ong: int = 20
    batch_size: int = 250

    def __post_init__(self) -> None:
        if not 0 <= self.seed <= 2_147_483_647:
            raise ValueError("seed debe estar entre 0 y 2147483647.")
        if self.ongs <= 0:
            raise ValueError("ongs debe ser positivo.")
        if self.recursos_por_ong < len(CODIGOS_CAPACIDAD):
            raise ValueError("recursos_por_ong debe ser al menos 4 para el seed local.")
        if not 1 <= self.batch_size <= 1000:
            raise ValueError("batch_size debe estar entre 1 y 1000.")


@dataclass
class ResultadoSeed:
    ongs: int = 0
    cuentas: int = 0
    recursos: int = 0
    acreditaciones: int = 0


def id_nacional(seed: int, referencia: str) -> UUID:
    """Usa las mismas referencias de ONG, cuenta y recurso que RescueSync."""
    return uuid5(NAMESPACE_URL, f"rescuesync-masivo:{seed}:{referencia}")


def _cuenta(
    session: Session,
    cuenta_id: UUID,
    login: str,
    rol: RolNacional,
    password_hash: str,
    *,
    ong_id: UUID | None = None,
    proposito: PropositoCuenta = PropositoCuenta.PERSONAL,
) -> bool:
    cuenta = session.scalar(select(Cuenta).where(Cuenta.identificador_login == login))
    if cuenta is not None:
        if (cuenta.id, cuenta.rol, cuenta.ong_id, cuenta.proposito) != (
            cuenta_id,
            rol,
            ong_id,
            proposito,
        ):
            raise ValueError("El login masivo pertenece a otra identidad nacional.")
        return False
    session.add(
        Cuenta(
            id=cuenta_id,
            identificador_login=login,
            rol=rol,
            ong_id=ong_id,
            proposito=proposito,
            password_hash=password_hash,
        )
    )
    return True


def _certificacion(
    session: Session, config: ConfiguracionSeed, capacidades: list[Capacidad]
) -> UUID:
    """Crea una revisión propia, sin modificar el catálogo oficial de capacidades."""
    cert_id = id_nacional(config.seed, "certificacion:1")
    codigo = f"MASIVO_{config.seed}"
    cert = session.scalar(
        select(Certificacion).where(
            Certificacion.codigo == codigo, Certificacion.revision == 1
        )
    )
    if cert is None:
        cert = Certificacion(
            id=cert_id,
            codigo=codigo,
            revision=1,
            nombre="Competencias sintéticas para pruebas de volumen",
            activa=False,
        )
        session.add(cert)
        session.flush()
        session.add_all(
            [
                CertificacionCapacidad(
                    certificacion_id=cert_id,
                    capacidad_id=cap.id,
                    riesgo_maximo=NivelRiesgo.CRITICA,
                )
                for cap in capacidades
            ]
        )
        session.flush()
        cert.activa = True
        session.flush()
    alcances = dict(
        session.execute(
            select(
                CertificacionCapacidad.capacidad_id,
                CertificacionCapacidad.riesgo_maximo,
            ).where(CertificacionCapacidad.certificacion_id == cert.id)
        ).all()
    )
    if cert.id != cert_id or alcances != {
        cap.id: NivelRiesgo.CRITICA for cap in capacidades
    }:
        raise ValueError("La certificación masiva tiene otra identidad o alcances.")
    return cert_id


def seed_mass_data(
    session: Session,
    config: ConfiguracionSeed,
    *,
    progreso: Callable[[str], None] | None = None,
) -> ResultadoSeed:
    """Agrega filas faltantes; la transacción y su rollback pertenecen al llamador."""
    if get_settings().app_env not in {"development", "test"}:
        raise ValueError("El seed masivo sólo está disponible en desarrollo y pruebas.")
    session.execute(select(func.pg_advisory_xact_lock(73843, config.seed)))
    catalogo = {
        cap.codigo: cap
        for cap in session.scalars(
            select(Capacidad).where(
                Capacidad.codigo.in_(CODIGOS_CAPACIDAD), Capacidad.activa.is_(True)
            )
        )
    }
    if set(catalogo) != set(CODIGOS_CAPACIDAD):
        raise ValueError("Aplicá las migraciones: faltan capacidades base activas.")
    capacidades = [catalogo[codigo] for codigo in CODIGOS_CAPACIDAD]
    for cap in capacidades:
        if cap.id != uuid5(NAMESPACE_URL, f"rescuesync:capacidad:{cap.codigo}"):
            raise ValueError(
                "El catálogo usa UUIDs distintos del contrato del seed local."
            )
    resultado = ResultadoSeed()
    # Reutilizar hashes de fixtures evita ejecutar Argon2 miles de veces.
    hash_personal = generar_password_hash(PASSWORD_PRUEBA)
    hash_tecnico = generar_password_hash(PASSWORD_TECNICA)
    admin, creado = asegurar_admin_demo(session)
    admin_id = admin.id
    resultado.cuentas += creado
    cert_id = _certificacion(session, config, capacidades)
    fake = Faker("es_AR", use_weighting=False)
    ahora = datetime.now(UTC)
    for indices in batched(range(1, config.ongs + 1), config.batch_size, strict=False):
        ids = {i: id_nacional(config.seed, f"ong:{i}") for i in indices}
        existentes = {
            ong.id: ong
            for ong in session.scalars(select(Ong).where(Ong.id.in_(ids.values())))
        }
        for i, ong_id in ids.items():
            identificador = f"masivo:{config.seed}:ong:{i}"
            if ong_id in existentes:
                if existentes[ong_id].identificador_institucional != identificador:
                    raise ValueError(
                        "Una ONG masiva pertenece a otra identidad nacional."
                    )
                continue
            fake.seed_instance(f"{config.seed}:ong:{i}")
            session.add(
                Ong(
                    id=ong_id,
                    identificador_institucional=identificador,
                    nombre=f"Masivo {config.seed} ONG {i:06d} — {fake.company()}"[:160],
                    email_contacto=f"masivo-{config.seed}-ong-{i}@example.test",
                    estado=EstadoOng.HABILITADA,
                    habilitada_en=ahora,
                    habilitada_por_id=admin_id,
                )
            )
            resultado.ongs += 1
        session.flush()
        for i, ong_id in ids.items():
            resultado.cuentas += _cuenta(
                session,
                id_nacional(config.seed, f"cuenta:{i}"),
                f"masivo-{config.seed}-ong-{i}@example.test",
                RolNacional.ONG,
                hash_personal,
                ong_id=ong_id,
            )
            resultado.cuentas += _cuenta(
                session,
                id_nacional(config.seed, f"cuenta-tecnica:{i}"),
                f"masivo-{config.seed}-tecnica-{i}",
                RolNacional.ONG,
                hash_tecnico,
                ong_id=ong_id,
                proposito=PropositoCuenta.TECNICA_ONG,
            )
        session.flush()
        acreditadas = set(
            session.scalars(
                select(OngCertificacion.ong_id).where(
                    OngCertificacion.ong_id.in_(ids.values()),
                    OngCertificacion.certificacion_id == cert_id,
                )
            )
        )
        for i, ong_id in ids.items():
            if ong_id not in acreditadas:
                session.add(
                    OngCertificacion(
                        id=id_nacional(config.seed, f"acreditacion:{i}"),
                        ong_id=ong_id,
                        certificacion_id=cert_id,
                        emisor="Autoridad sintética de pruebas",
                        numero_credencial=f"MASIVO-{config.seed}-{i}",
                        vigente_desde=ahora - timedelta(days=180),
                        vigente_hasta=ahora + timedelta(days=365),
                        registrada_por_id=admin_id,
                    )
                )
                resultado.acreditaciones += 1
        # Paginar también los recursos limita la memoria aunque una ONG tenga miles.
        referencias = (
            (i, j) for i in ids for j in range(1, config.recursos_por_ong + 1)
        )
        for posiciones in batched(referencias, config.batch_size, strict=False):
            presentes = {
                (recurso.ong_id, recurso.codigo_interno): recurso
                for recurso in session.scalars(
                    select(Recurso).where(
                        Recurso.ong_id.in_({ids[i] for i, _ in posiciones}),
                        Recurso.codigo_interno.in_(
                            {f"MASIVO-{j:08d}" for _, j in posiciones}
                        ),
                    )
                )
            }
            for i, j in posiciones:
                ong_id = ids[i]
                codigo = f"MASIVO-{j:08d}"
                recurso_id = id_nacional(config.seed, f"recurso:{i}:{j}")
                cap = capacidades[(j - 1) % len(capacidades)]
                existente = presentes.get((ong_id, codigo))
                if existente is not None:
                    if existente.id != recurso_id or existente.capacidad_id != cap.id:
                        raise ValueError("Un recurso masivo tiene otra identidad.")
                    continue
                fake.seed_instance(f"{config.seed}:recurso:{i}:{j}")
                session.add(
                    Recurso(
                        id=recurso_id,
                        ong_id=ong_id,
                        capacidad_id=cap.id,
                        codigo_interno=codigo,
                        nombre=f"{cap.nombre} — {fake.city()} / {j}"[:160],
                        cantidad_total=Decimal(fake.random_int(min=1000, max=10000)),
                    )
                )
                resultado.recursos += 1
            session.flush()
        if progreso:
            progreso(
                f"ONGs procesadas: {indices[-1]}/{config.ongs} (sin commit todavía)."
            )
    return resultado


def main(argv: list[str] | None = None) -> int:
    """Configura la carga, permite simularla y muestra sólo conteos confirmados."""
    parser = argparse.ArgumentParser(description=__doc__)
    for nombre, defecto in asdict(ConfiguracionSeed()).items():
        parser.add_argument(f"--{nombre.replace('_', '-')}", type=int, default=defecto)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el volumen sin conectar a la base.",
    )
    args = vars(parser.parse_args(argv))
    dry_run = args.pop("dry_run")
    try:
        config = ConfiguracionSeed(**args)
        if get_settings().app_env not in {"development", "test"}:
            raise ValueError(
                "El seed masivo sólo está disponible en desarrollo y pruebas."
            )
        if dry_run:
            print(
                f"Simulación sin escrituras: {config.ongs} ONGs, "
                f"{2 * config.ongs + 1} cuentas, "
                f"{config.ongs * config.recursos_por_ong} recursos y "
                f"{config.ongs} acreditaciones. Seed: {config.seed}."
            )
            return 0
        inicio = perf_counter()
        with SessionLocal.begin() as session:
            resultado = seed_mass_data(session, config, progreso=print)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print(
            "No se pudo completar la carga; se revirtió la transacción. "
            "Revisá la conexión, migraciones y posibles colisiones.",
            file=sys.stderr,
        )
        return 1
    print(f"Carga confirmada en {perf_counter() - inicio:.1f}s: {asdict(resultado)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
