"""Pruebas de integridad real del esquema nacional y sus migraciones."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import Error as PostgresError
from sqlalchemy import (
    Engine,
    delete,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, configure_mappers

from app.db.base import Base
from app.db.models import (
    Capacidad,
    Certificacion,
    CertificacionCapacidad,
    Compromiso,
    CompromisoItem,
    Cuenta,
    EstadoAcreditacion,
    EstadoCompromiso,
    EstadoOng,
    NivelRiesgo,
    Ong,
    OngCertificacion,
    OperacionIdempotente,
    Proyecto,
    Recurso,
    RolNacional,
    SistemaOrigen,
    TipoOperacion,
    TipoRecurso,
)

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def rechaza_restriccion(nombre: str) -> Iterator[None]:
    """Verifica el diagnóstico estructurado, sin depender del texto de PostgreSQL."""

    with pytest.raises(IntegrityError) as captured:
        yield
    original = captured.value.orig
    assert isinstance(original, PostgresError)
    assert original.diag.constraint_name == nombre


def alembic_config(connection_engine: Engine) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", str(connection_engine.url))
    return config


@dataclass
class DatosNacionales:
    origen: SistemaOrigen
    admin: Cuenta
    integracion: Cuenta
    ong: Ong
    capacidad: Capacidad
    certificacion: Certificacion
    acreditacion: OngCertificacion
    recurso: Recurso
    proyecto: Proyecto


def crear_datos(session: Session, identificador: str = "prueba") -> DatosNacionales:
    """Prepara dependencias en orden explícito para transacciones independientes."""

    origen = SistemaOrigen(
        codigo=f"rescuesync-{identificador}", nombre="RescueSync local"
    )
    admin = Cuenta(
        identificador_login=f"admin-{identificador}@example.test",
        password_hash="$argon2id$hash-de-prueba",
        rol=RolNacional.ADMIN_NACIONAL,
    )
    ong = Ong(
        identificador_institucional=f"registro:{identificador}",
        nombre="ONG de prueba",
        email_contacto="contacto@example.test",
    )
    capacidad = Capacidad(
        codigo=f"ATENCION_{identificador}",
        nombre="Atención prehospitalaria",
        tipo=TipoRecurso.PERSONAL,
        unidad="persona",
        admite_fracciones=False,
    )
    certificacion = Certificacion(
        codigo=f"RESCATE_{identificador}", revision=1, nombre="Rescate"
    )
    session.add_all([origen, admin, ong, capacidad, certificacion])
    session.flush()
    ong.estado = EstadoOng.HABILITADA
    ong.habilitada_en = datetime.now(UTC)
    ong.habilitada_por_id = admin.id
    integracion = Cuenta(
        identificador_login=f"bonita-{identificador}",
        password_hash="$argon2id$hash-tecnico-de-prueba",
        rol=RolNacional.INTEGRACION,
        sistema_origen_id=origen.id,
    )
    session.add(integracion)
    session.add(
        CertificacionCapacidad(
            certificacion_id=certificacion.id,
            capacidad_id=capacidad.id,
            riesgo_maximo=NivelRiesgo.ALTA,
        )
    )
    session.flush()
    certificacion.activa = True
    session.flush()
    now = datetime.now(UTC)
    acreditacion = OngCertificacion(
        ong_id=ong.id,
        certificacion_id=certificacion.id,
        emisor="Autoridad de prueba",
        numero_credencial="credencial-1",
        vigente_desde=now - timedelta(days=1),
        vigente_hasta=now + timedelta(days=365),
        registrada_por_id=admin.id,
    )
    recurso = Recurso(
        ong_id=ong.id,
        capacidad_id=capacidad.id,
        codigo_interno="paramedicos-sede-1",
        nombre="Paramédicos sede 1",
        cantidad_total=Decimal("10.000"),
    )
    proyecto = Proyecto(
        sistema_origen_id=origen.id, emergencia_ref="10", case_ref="100"
    )
    session.add_all([acreditacion, recurso, proyecto])
    session.flush()
    return DatosNacionales(
        origen,
        admin,
        integracion,
        ong,
        capacidad,
        certificacion,
        acreditacion,
        recurso,
        proyecto,
    )


@pytest.fixture
def datos(session: Session) -> DatosNacionales:
    return crear_datos(session)


def crear_compromiso(
    session: Session,
    datos: DatosNacionales,
    *,
    con_items: bool = True,
    cantidad: Decimal = Decimal("3.000"),
    clave: str | None = None,
) -> Compromiso:
    """Reproduce reclamo, cabecera, ítems y resultado en una sola transacción."""

    operacion = OperacionIdempotente(
        sistema_origen_id=datos.origen.id,
        cuenta_id=datos.integracion.id,
        operacion=TipoOperacion.COMPROMETER,
        clave=clave if clave is not None else uuid4().hex,
        huella_sha256="a" * 64,
    )
    session.add(operacion)
    session.flush()
    compromiso = Compromiso(
        proyecto_id=datos.proyecto.id,
        ong_id=datos.ong.id,
        operacion_creacion_id=operacion.id,
        adjudicacion_ref=uuid4().hex,
    )
    session.add(compromiso)
    session.flush()
    if con_items:
        session.add(
            CompromisoItem(
                compromiso_id=compromiso.id,
                recurso_id=datos.recurso.id,
                ong_id=datos.ong.id,
                convocatoria_ref="20",
                oferta_ref="30",
                oferta_version=1,
                lote_ref="40",
                aporte_ref="50",
                riesgo_requerido=NivelRiesgo.MEDIA,
                cantidad=cantidad,
            )
        )
    operacion.proyecto_id = datos.proyecto.id
    operacion.codigo_http = 201
    operacion.respuesta_minima = {
        "proyectoId": str(datos.proyecto.id),
        "compromisoIds": [str(compromiso.id)],
    }
    session.flush()
    return compromiso


def verificar_diferidas(session: Session) -> None:
    """Fuerza en el savepoint las restricciones que PostgreSQL evalúa al commit."""

    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_metadata_y_relaciones(session: Session, datos: DatosNacionales) -> None:
    configure_mappers()
    compromiso = crear_compromiso(session, datos)
    verificar_diferidas(session)
    session.expire_all()
    assert compromiso.items[0].compromiso is compromiso
    assert compromiso.items[0].cantidad == Decimal("3.000")
    assert compromiso.creado_en.utcoffset() == timedelta(0)
    assert set(Base.metadata.tables) == {
        "sistema_origen",
        "cuenta",
        "ong",
        "capacidad",
        "certificacion",
        "certificacion_capacidad",
        "ong_certificacion",
        "recurso",
        "proyecto",
        "operacion_idempotente",
        "compromiso",
        "compromiso_item",
    }
    assert "cantidad_disponible" not in Recurso.__table__.c
    assert "cantidad_comprometida" not in Recurso.__table__.c


def test_upgrade_downgrade_upgrade(engine_vacio: Engine) -> None:
    """La reversión elimina también funciones/enums; el nuevo upgrade no colisiona."""

    with engine_vacio.begin() as connection:
        config = alembic_config(engine_vacio)
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid=t.typnamespace "
                    "WHERE n.nspname=current_schema() AND t.typtype='e'"
                )
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname=current_schema() AND p.proname LIKE 'nacional_%'"
                )
            )
            == 0
        )
        command.upgrade(config, "head")
        command.check(config)


@pytest.mark.parametrize(
    ("rol", "con_ong", "con_origen"),
    [
        (RolNacional.ONG, False, False),
        (RolNacional.ONG, True, True),
        (RolNacional.INTEGRACION, False, False),
        (RolNacional.INTEGRACION, True, True),
        (RolNacional.ADMIN_NACIONAL, True, False),
        (RolNacional.ADMIN_NACIONAL, False, True),
    ],
)
def test_cuenta_rechaza_vinculos_incompatibles(
    session: Session,
    datos: DatosNacionales,
    rol: RolNacional,
    con_ong: bool,
    con_origen: bool,
) -> None:
    session.add(
        Cuenta(
            identificador_login="invalida@example.test",
            password_hash="$argon2id$hash-de-prueba",
            rol=rol,
            ong_id=datos.ong.id if con_ong else None,
            sistema_origen_id=datos.origen.id if con_origen else None,
        )
    )
    with rechaza_restriccion("ck_cuenta_rol_vinculos"):
        session.flush()


@pytest.mark.parametrize("login", ["ADMIN@example.test", " admin@example.test", " "])
def test_login_exige_normalizacion(session: Session, login: str) -> None:
    session.add(
        Cuenta(
            identificador_login=login,
            password_hash="$argon2id$prueba",
            rol=RolNacional.ADMIN_NACIONAL,
        )
    )
    with rechaza_restriccion("ck_cuenta_login_normalizado"):
        session.flush()


def test_cuenta_no_acepta_password_plano(session: Session) -> None:
    session.add(
        Cuenta(
            identificador_login="usuario@example.test",
            password_hash="password",
            rol=RolNacional.ADMIN_NACIONAL,
        )
    )
    with rechaza_restriccion("ck_cuenta_hash_argon2id"):
        session.flush()


@pytest.mark.parametrize("cantidad", [Decimal("-1"), Decimal("NaN")])
def test_inventario_rechaza_total_invalido(
    session: Session,
    datos: DatosNacionales,
    cantidad: Decimal,
) -> None:
    datos.recurso.cantidad_total = cantidad
    with rechaza_restriccion("ck_recurso_total_finito"):
        session.flush()


def test_personal_no_admite_fracciones(
    session: Session, datos: DatosNacionales
) -> None:
    datos.recurso.cantidad_total = Decimal("1.500")
    with rechaza_restriccion("ck_cantidad_discreta"):
        session.flush()


def test_suministro_fraccionable_preserva_decimal(
    session: Session,
    datos: DatosNacionales,
) -> None:
    capacidad = Capacidad(
        codigo="ALIMENTO_KG",
        nombre="Alimento por peso",
        tipo=TipoRecurso.SUMINISTRO,
        unidad="kg",
        admite_fracciones=True,
    )
    session.add(capacidad)
    session.flush()
    recurso = Recurso(
        ong_id=datos.ong.id,
        capacidad_id=capacidad.id,
        codigo_interno="alimento",
        nombre="Alimento",
        cantidad_total=Decimal("15.125"),
    )
    session.add(recurso)
    session.flush()
    session.expire(recurso)
    assert recurso.cantidad_total == Decimal("15.125")


def test_capacidad_referenciada_no_cambia_unidad(
    session: Session,
    datos: DatosNacionales,
) -> None:
    datos.capacidad.unidad = "kg"
    with rechaza_restriccion("ck_capacidad_semantica_inmutable"):
        session.flush()


def test_certificacion_activa_no_puede_quedar_sin_alcances(session: Session) -> None:
    session.add(Certificacion(codigo="VACIA", revision=1, nombre="Vacía", activa=True))
    session.flush()
    with rechaza_restriccion("ck_certificacion_con_alcances"):
        verificar_diferidas(session)


def test_catalogo_admite_varias_capacidades(
    session: Session, datos: DatosNacionales
) -> None:
    capacidad = Capacidad(
        codigo="APOYO_LOGISTICO",
        nombre="Apoyo",
        tipo=TipoRecurso.EQUIPAMIENTO,
        unidad="equipo",
    )
    revision = Certificacion(codigo="CONSORCIO", revision=1, nombre="Capacidades")
    session.add_all([capacidad, revision])
    session.flush()
    session.add_all(
        [
            CertificacionCapacidad(
                certificacion_id=revision.id,
                capacidad_id=datos.capacidad.id,
                riesgo_maximo=NivelRiesgo.ALTA,
            ),
            CertificacionCapacidad(
                certificacion_id=revision.id,
                capacidad_id=capacidad.id,
                riesgo_maximo=NivelRiesgo.BAJA,
            ),
        ]
    )
    revision.activa = True
    session.flush()
    verificar_diferidas(session)
    assert (
        len(
            session.scalars(
                select(CertificacionCapacidad).where(
                    CertificacionCapacidad.certificacion_id == revision.id,
                )
            ).all()
        )
        == 2
    )


def test_alcance_otorgado_no_puede_ampliarse(
    session: Session,
    datos: DatosNacionales,
) -> None:
    with rechaza_restriccion("ck_alcance_otorgado_inmutable"):
        session.execute(
            update(CertificacionCapacidad)
            .where(
                CertificacionCapacidad.certificacion_id == datos.certificacion.id,
            )
            .values(riesgo_maximo=NivelRiesgo.CRITICA)
        )


def test_revision_otorgada_es_inmutable(
    session: Session, datos: DatosNacionales
) -> None:
    datos.certificacion.revision = 2
    with rechaza_restriccion("ck_revision_otorgada_inmutable"):
        session.flush()


def test_renovacion_no_sobrescribe_vigencia(
    session: Session, datos: DatosNacionales
) -> None:
    datos.acreditacion.vigente_hasta += timedelta(days=365)
    with rechaza_restriccion("ck_acreditacion_inmutable"):
        session.flush()


def test_revocar_exige_administrador(session: Session, datos: DatosNacionales) -> None:
    datos.acreditacion.estado = EstadoAcreditacion.REVOCADA
    datos.acreditacion.revocada_en = datetime.now(UTC)
    datos.acreditacion.revocada_por_id = datos.integracion.id
    datos.acreditacion.motivo_revocacion = "Prueba"
    with rechaza_restriccion("ck_acreditacion_autor_admin"):
        session.flush()


def test_revocacion_y_renovacion_conservan_registros(
    session: Session,
    datos: DatosNacionales,
) -> None:
    datos.acreditacion.estado = EstadoAcreditacion.REVOCADA
    datos.acreditacion.revocada_en = datetime.now(UTC)
    datos.acreditacion.revocada_por_id = datos.admin.id
    datos.acreditacion.motivo_revocacion = "Renovada"
    session.flush()
    now = datetime.now(UTC)
    nueva = OngCertificacion(
        ong_id=datos.ong.id,
        certificacion_id=datos.certificacion.id,
        emisor="Autoridad de prueba",
        numero_credencial="credencial-2",
        vigente_desde=now,
        vigente_hasta=now + timedelta(days=365),
        registrada_por_id=datos.admin.id,
    )
    session.add(nueva)
    verificar_diferidas(session)
    assert datos.acreditacion.id != nueva.id
    assert datos.acreditacion.estado == EstadoAcreditacion.REVOCADA
    assert nueva.estado == EstadoAcreditacion.OTORGADA


def test_compromiso_no_puede_confirmarse_vacio(
    session: Session,
    datos: DatosNacionales,
) -> None:
    crear_compromiso(session, datos, con_items=False)
    with rechaza_restriccion("ck_compromiso_con_items"):
        verificar_diferidas(session)


@pytest.mark.parametrize(
    ("cantidad", "restriccion"),
    [
        (Decimal("0"), "ck_item_cantidad"),
        (Decimal("-1"), "ck_item_cantidad"),
        (Decimal("NaN"), "ck_item_cantidad"),
        (Decimal("1.500"), "ck_cantidad_discreta"),
    ],
)
def test_items_rechazan_cantidades_invalidas(
    session: Session,
    datos: DatosNacionales,
    cantidad: Decimal,
    restriccion: str,
) -> None:
    with rechaza_restriccion(restriccion):
        crear_compromiso(session, datos, cantidad=cantidad)


def test_item_no_puede_reservar_recurso_de_otra_ong(
    session: Session,
    datos: DatosNacionales,
) -> None:
    compromiso = crear_compromiso(session, datos, con_items=False)
    otra = Ong(
        identificador_institucional="registro:otra",
        nombre="Otra ONG",
        email_contacto="otra@example.test",
    )
    session.add(otra)
    session.flush()
    recurso = Recurso(
        ong_id=otra.id,
        capacidad_id=datos.capacidad.id,
        codigo_interno="personal",
        nombre="Personal de otra ONG",
        cantidad_total=Decimal("10"),
    )
    session.add(recurso)
    session.flush()
    session.add(
        CompromisoItem(
            compromiso_id=compromiso.id,
            recurso_id=recurso.id,
            ong_id=datos.ong.id,
            convocatoria_ref="20",
            oferta_ref="30",
            oferta_version=1,
            lote_ref="40",
            aporte_ref="50",
            riesgo_requerido=NivelRiesgo.MEDIA,
            cantidad=Decimal("1"),
        )
    )
    with rechaza_restriccion("fk_item_recurso_ong"):
        session.flush()


def test_adjudicacion_no_se_duplica_con_otra_clave(
    session: Session,
    datos: DatosNacionales,
) -> None:
    anterior = crear_compromiso(session, datos)
    session.add(
        Compromiso(
            proyecto_id=anterior.proyecto_id,
            ong_id=anterior.ong_id,
            operacion_creacion_id=anterior.operacion_creacion_id,
            adjudicacion_ref=anterior.adjudicacion_ref,
        )
    )
    with rechaza_restriccion("uq_compromiso_adjudicacion"):
        session.flush()


def test_operacion_incompleta_no_se_confirma(
    session: Session,
    datos: DatosNacionales,
) -> None:
    session.add(
        OperacionIdempotente(
            sistema_origen_id=datos.origen.id,
            cuenta_id=datos.integracion.id,
            operacion=TipoOperacion.COMPROMETER,
            clave="reclamo-pendiente",
            huella_sha256="b" * 64,
        )
    )
    session.flush()
    with rechaza_restriccion("ck_operacion_resultado_completo"):
        verificar_diferidas(session)


def test_clave_es_unica_por_emisor_y_operacion(
    session: Session,
    datos: DatosNacionales,
) -> None:
    compromiso = crear_compromiso(session, datos)
    original = session.get(OperacionIdempotente, compromiso.operacion_creacion_id)
    assert original is not None
    session.add(
        OperacionIdempotente(
            sistema_origen_id=datos.origen.id,
            cuenta_id=datos.integracion.id,
            operacion=TipoOperacion.COMPROMETER,
            clave=original.clave,
            huella_sha256="b" * 64,
        )
    )
    with rechaza_restriccion("uq_operacion_clave"):
        session.flush()


def test_operacion_no_apunta_a_proyecto_de_otro_emisor(
    session: Session,
    datos: DatosNacionales,
) -> None:
    otro = SistemaOrigen(codigo="otro", nombre="Otro emisor")
    session.add(otro)
    session.flush()
    session.add(
        OperacionIdempotente(
            sistema_origen_id=otro.id,
            cuenta_id=datos.integracion.id,
            proyecto_id=datos.proyecto.id,
            operacion=TipoOperacion.COMPROMETER,
            clave="origen-incorrecto",
            huella_sha256="b" * 64,
        )
    )
    with rechaza_restriccion("fk_operacion_proyecto_origen"):
        session.flush()


def test_resultado_idempotente_confirmado_no_se_modifica(
    session: Session,
    datos: DatosNacionales,
) -> None:
    compromiso = crear_compromiso(session, datos)
    with rechaza_restriccion("ck_operacion_inmutable"):
        session.execute(
            update(OperacionIdempotente)
            .where(
                OperacionIdempotente.id == compromiso.operacion_creacion_id,
            )
            .values(respuesta_minima={"estado": "otro"})
        )


@pytest.mark.parametrize("borrar", [False, True])
def test_item_adjudicado_conserva_historial(
    session: Session,
    datos: DatosNacionales,
    borrar: bool,
) -> None:
    compromiso = crear_compromiso(session, datos)
    sentencia = (
        delete(CompromisoItem).where(CompromisoItem.compromiso_id == compromiso.id)
        if borrar
        else update(CompromisoItem)
        .where(CompromisoItem.compromiso_id == compromiso.id)
        .values(cantidad=Decimal("1"))
    )
    with pytest.raises(IntegrityError):
        session.execute(sentencia)


def test_liberacion_conserva_items_y_excluye_cantidad_activa(
    session: Session,
    datos: DatosNacionales,
) -> None:
    compromiso = crear_compromiso(session, datos)
    comprometido = (
        select(func.coalesce(func.sum(CompromisoItem.cantidad), 0))
        .join(
            Compromiso,
            Compromiso.id == CompromisoItem.compromiso_id,
        )
        .where(Compromiso.estado == EstadoCompromiso.ACTIVO)
    )
    assert session.scalar(comprometido) == Decimal("3")
    compromiso.estado = EstadoCompromiso.LIBERADO
    compromiso.liberado_en = datetime.now(UTC)
    compromiso.liberado_por_id = datos.integracion.id
    verificar_diferidas(session)
    assert session.scalar(comprometido) == Decimal("0")
    assert session.scalar(select(func.count()).select_from(CompromisoItem)) == 1
    assert datos.recurso.cantidad_total == Decimal("10.000")


def test_liberacion_repetida_no_cambia_primera_fecha(
    session: Session,
    datos: DatosNacionales,
) -> None:
    compromiso = crear_compromiso(session, datos)
    compromiso.estado = EstadoCompromiso.LIBERADO
    compromiso.liberado_en = datetime.now(UTC)
    compromiso.liberado_por_id = datos.integracion.id
    session.flush()
    compromiso.liberado_en += timedelta(seconds=1)
    with rechaza_restriccion("ck_compromiso_inmutable"):
        session.flush()


def test_clave_concurrente_confirma_una_sola_asignacion(engine_migrado: Engine) -> None:
    """Dos conexiones reales compiten por la unicidad, sin compartir sesiones."""

    identificador = uuid4().hex
    with Session(engine_migrado, expire_on_commit=False) as setup:
        with setup.begin():
            escenario = crear_datos(setup, identificador)
    barrera = Barrier(2)

    def reservar() -> bool:
        with Session(engine_migrado) as db:
            try:
                with db.begin():
                    barrera.wait(timeout=10)
                    crear_compromiso(db, escenario, clave=identificador)
                return True
            except IntegrityError as error:
                assert isinstance(error.orig, PostgresError)
                assert error.orig.diag.constraint_name == "uq_operacion_clave"
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        solicitudes = [executor.submit(reservar) for _ in range(2)]
        resultados = [solicitud.result(timeout=15) for solicitud in solicitudes]
    assert sorted(resultados) == [False, True]
    with Session(engine_migrado) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OperacionIdempotente)
                .where(
                    OperacionIdempotente.sistema_origen_id == escenario.origen.id,
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Compromiso)
                .where(
                    Compromiso.proyecto_id == escenario.proyecto.id,
                )
            )
            == 1
        )


def test_certificacion_otorgada_inactiva_requiere_alcances(
    session: Session,
    datos: DatosNacionales,
) -> None:
    vacia = Certificacion(
        codigo="INCOMPLETA", revision=1, nombre="Incompleta", activa=True
    )
    session.add(vacia)
    session.flush()
    now = datetime.now(UTC)
    session.add(
        OngCertificacion(
            ong_id=datos.ong.id,
            certificacion_id=vacia.id,
            emisor="Autoridad de prueba",
            numero_credencial="credencial-incompleta",
            vigente_desde=now,
            vigente_hasta=now + timedelta(days=365),
            registrada_por_id=datos.admin.id,
        )
    )
    session.flush()
    vacia.activa = False
    session.flush()
    with rechaza_restriccion("ck_certificacion_con_alcances"):
        verificar_diferidas(session)
