"""Escenario determinista y pequeño para la colección manual de Yaak."""

from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.orm import Session

from app.core.security import generar_password_hash
from app.db.catalogo_base import CAPACIDADES, UNIDADES
from app.db.models import (
    Capacidad,
    Cuenta,
    EstadoOng,
    Ong,
    PropositoCuenta,
    Recurso,
    RolNacional,
    SistemaOrigen,
    TipoRecurso,
)
from app.schemas.mantenimiento import (
    LOGINS_YAAK,
    ReferenciasSeedYaak,
    SeedYaakRequest,
    SeedYaakResponse,
)

# Credencial exclusivamente demostrativa; nunca se devuelve por HTTP.
PASSWORD_YAAK = "demo-only-yaak-pruebas-2026-clave-123456"


def identidad(run_id: str, referencia: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"rescuesync:yaak:{run_id}:{referencia}")


def respuesta_seed_yaak(datos: SeedYaakRequest) -> SeedYaakResponse:
    """Construye las referencias públicas sin incluir contraseñas ni JWT."""
    run = datos.run_id
    return SeedYaakResponse(
        operacion="seed-yaak",
        mensaje="Base nacional reiniciada y escenario Yaak preparado.",
        run_id=run,
        unidades=len(UNIDADES),
        capacidades=len(CAPACIDADES) + 1,
        ongs=5,
        cuentas=8,
        recursos=7,
        proyectos=0,
        compromisos=0,
        sistema_origen=datos.integracion.sistema_origen,
        identificadores_login={
            **LOGINS_YAAK,
            "integracion": datos.integracion.identificador_login,
        },
        referencias=ReferenciasSeedYaak(
            admin_id=identidad(run, "cuenta:admin"),
            integracion_id=identidad(run, "cuenta:integracion"),
            ong_a_id=identidad(run, "ong:a"),
            ong_b_id=identidad(run, "ong:b"),
            ong_tecnica_id=identidad(run, "ong:tecnica"),
            ong_suspendida_id=identidad(run, "ong:suspendida"),
            ong_baja_id=identidad(run, "ong:baja"),
            capacidad_personal_id=uuid5(
                NAMESPACE_URL, "rescuesync:capacidad:PARAMEDICOS"
            ),
            capacidad_agua_id=uuid5(NAMESPACE_URL, "rescuesync:capacidad:AGUA"),
            capacidad_inactiva_id=identidad(run, "capacidad:inactiva"),
            personal_a_id=identidad(run, "recurso:personal-a"),
            personal_b_id=identidad(run, "recurso:personal-b"),
            agua_a_id=identidad(run, "recurso:agua-a"),
            recurso_inactivo_id=identidad(run, "recurso:inactivo"),
            recurso_capacidad_inactiva_id=identidad(run, "recurso:capacidad-inactiva"),
            personal_suspendida_id=identidad(run, "recurso:suspendida"),
            personal_baja_id=identidad(run, "recurso:baja"),
        ),
    )


def cargar_escenario_yaak(session: Session, datos: SeedYaakRequest) -> SeedYaakResponse:
    """Carga sólo el escenario; el servicio controla flush, lock y commit."""
    respuesta = respuesta_seed_yaak(datos)
    refs = respuesta.referencias
    run = datos.run_id
    origen_id = identidad(run, "sistema-origen")
    session.add(
        SistemaOrigen(
            id=origen_id,
            codigo=datos.integracion.sistema_origen,
            nombre="Integración del escenario Yaak",
        )
    )
    session.add(
        Capacidad(
            id=refs.capacidad_inactiva_id,
            codigo="YAAK_INACTIVA",
            nombre="Capacidad inactiva de prueba",
            tipo=TipoRecurso.EQUIPAMIENTO,
            unidad="equipos",
            admite_fracciones=False,
            activa=False,
        )
    )
    for key, estado in [
        ("a", EstadoOng.HABILITADA),
        ("b", EstadoOng.HABILITADA),
        ("tecnica", EstadoOng.HABILITADA),
        ("suspendida", EstadoOng.SUSPENDIDA),
        ("baja", EstadoOng.BAJA),
    ]:
        session.add(
            Ong(
                id=identidad(run, f"ong:{key}"),
                nombre=f"Yaak ONG {key.upper()}",
                identificador_institucional=f"yaak:{run}:{key}".lower(),
                email_contacto=f"yaak-{key}@example.org",
                estado=estado,
            )
        )
    session.flush()
    for key in [
        "admin",
        "integracion",
        "ong_a",
        "ong_b",
        "tecnica",
        "suspendida",
        "baja",
        "inactiva",
    ]:
        ong_key = {"ong_a": "a", "ong_b": "b", "inactiva": "a"}.get(key, key)
        password = (
            datos.integracion.password.get_secret_value()
            if key == "integracion"
            else PASSWORD_YAAK
        )
        session.add(
            Cuenta(
                id=identidad(run, f"cuenta:{key}"),
                identificador_login=respuesta.identificadores_login[key],
                password_hash=generar_password_hash(password),
                rol=RolNacional.ADMIN_NACIONAL
                if key == "admin"
                else (
                    RolNacional.INTEGRACION if key == "integracion" else RolNacional.ONG
                ),
                ong_id=identidad(run, f"ong:{ong_key}")
                if key not in {"admin", "integracion"}
                else None,
                sistema_origen_id=origen_id if key == "integracion" else None,
                proposito=PropositoCuenta.TECNICA_ONG
                if key == "tecnica"
                else PropositoCuenta.PERSONAL,
                activa=key != "inactiva",
            )
        )
    for key, ong_key, capacidad_id, cantidad, activo in [
        ("personal-a", "a", refs.capacidad_personal_id, "14.000", True),
        ("personal-b", "b", refs.capacidad_personal_id, "10.000", True),
        ("agua-a", "a", refs.capacidad_agua_id, "10.125", True),
        ("inactivo", "a", refs.capacidad_personal_id, "2.000", False),
        ("capacidad-inactiva", "a", refs.capacidad_inactiva_id, "4.000", True),
        ("suspendida", "suspendida", refs.capacidad_personal_id, "5.000", True),
        ("baja", "baja", refs.capacidad_personal_id, "5.000", True),
    ]:
        session.add(
            Recurso(
                id=identidad(run, f"recurso:{key}"),
                ong_id=identidad(run, f"ong:{ong_key}"),
                capacidad_id=capacidad_id,
                codigo_interno=f"BASE-{key.upper()}",
                nombre=f"Recurso base Yaak {key}",
                cantidad_total=Decimal(cantidad),
                activo=activo,
            )
        )
    session.flush()
    return respuesta
