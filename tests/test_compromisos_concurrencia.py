"""Espera real en PostgreSQL entre conexiones: stock, reintentos y vigencia."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from decimal import Decimal
from threading import Barrier, Event
from time import monotonic
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, event, func, select, text
from sqlalchemy.orm import Session
from test_compromisos import peticion
from test_database_models import crear_datos

from app.db.models import Compromiso, Cuenta, OperacionIdempotente, Recurso
from app.schemas.compromisos import CompromisoRequest, ConfirmacionCompromisos
from app.schemas.inventario import RecursoUpdate
from app.services import compromisos as servicio
from app.services.compromisos import registrar_compromisos
from app.services.inventario import (
    InventarioConflictivoError,
    actualizar_recurso,
    cantidad_comprometida,
)
from app.services.operaciones import ErrorOperacion


@dataclass
class Escenario:
    cuenta_id: UUID
    recurso_id: UUID
    ong_id: UUID
    actualizado_en: datetime
    vencimiento: datetime
    solicitud: CompromisoRequest


@dataclass
class Trabajador:
    iniciado: Event = field(default_factory=Event)
    bloqueado: Event = field(default_factory=Event)
    continuar: Event = field(default_factory=Event)
    pid: int | None = None


def preparar(engine: Engine) -> Escenario:
    with Session(engine, expire_on_commit=False) as db:
        datos = crear_datos(db, f"concurrente-{uuid4().hex}")
        escenario = Escenario(
            datos.integracion.id,
            datos.recurso.id,
            datos.ong.id,
            datos.recurso.actualizado_en,
            datos.acreditacion.vigente_hasta,
            peticion(datos),
        )
        db.commit()
        return escenario


def esperar_bloqueo(engine: Engine, espera: Trabajador, bloqueante: Trabajador) -> None:
    """Observa pg_blocking_pids; no asume que iniciar threads prueba una carrera."""
    assert espera.iniciado.wait(5) and bloqueante.iniciado.wait(5)
    assert espera.pid is not None and bloqueante.pid is not None
    fin = monotonic() + 5
    with engine.connect() as observer:
        while monotonic() < fin:
            bloqueado = observer.scalar(
                text("SELECT :bloqueante = ANY(pg_blocking_pids(:espera))"),
                {"bloqueante": bloqueante.pid, "espera": espera.pid},
            )
            if bloqueado:
                return
    pytest.fail("La segunda transacción no esperó el lock PostgreSQL esperado.")


def reservar(
    engine: Engine,
    escenario: Escenario,
    solicitud: CompromisoRequest,
    clave: str,
    estado: Trabajador,
    *,
    pausar: bool = False,
    barrera: Barrier | None = None,
) -> tuple[int, ConfirmacionCompromisos | None]:
    with Session(engine) as db:
        connection = db.connection()
        estado.pid = db.scalar(text("SELECT pg_backend_pid()"))
        estado.iniciado.set()

        def detener(
            _conn: Connection,
            _cursor: object,
            sql: str,
            _params: object,
            _context: object,
            _many: bool,
        ) -> None:
            if (
                pausar
                and "FROM recurso" in sql
                and "FOR UPDATE" in sql
                and not estado.bloqueado.is_set()
            ):
                estado.bloqueado.set()
                assert estado.continuar.wait(10), (
                    "No se liberó la transacción de prueba."
                )

        event.listen(connection, "after_cursor_execute", detener)
        try:
            if barrera is not None:
                barrera.wait(timeout=5)
            cuenta = db.get(Cuenta, escenario.cuenta_id)
            assert cuenta is not None
            try:
                return 201, registrar_compromisos(db, cuenta, solicitud, clave)
            except ErrorOperacion as error:
                return error.status, None
        finally:
            event.remove(connection, "after_cursor_execute", detener)


@pytest.mark.parametrize("misma_clave", [False, True])
def test_dos_emergencias_y_reintentos_esperan_el_commit(
    engine_migrado: Engine, misma_clave: bool
) -> None:
    e = preparar(engine_migrado)
    otra = e.solicitud.model_copy(deep=True)
    if not misma_clave:
        otra.id_emergencia = "102"
        otra.adjudicacion_id = "seleccion-102"
    primera, segunda = Trabajador(), Trabajador()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(
            reservar, engine_migrado, e, e.solicitud, "primera", primera, pausar=True
        )
        try:
            assert primera.bloqueado.wait(5)
            f2 = pool.submit(
                reservar,
                engine_migrado,
                e,
                otra,
                "primera" if misma_clave else "segunda",
                segunda,
            )
            esperar_bloqueo(engine_migrado, segunda, primera)
        finally:
            primera.continuar.set()
        r1, r2 = f1.result(timeout=10), f2.result(timeout=10)
    assert r1[0] == 201
    assert r2[0] == (201 if misma_clave else 409)
    if misma_clave:
        assert r1[1] == r2[1]
    with Session(engine_migrado) as db:
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(6)
        assert (
            db.scalar(
                select(func.count())
                .select_from(OperacionIdempotente)
                .where(OperacionIdempotente.cuenta_id == e.cuenta_id)
            )
            == 1
        )


def test_recursos_en_orden_inverso_no_sobreasignan(engine_migrado: Engine) -> None:
    e = preparar(engine_migrado)
    with Session(engine_migrado) as db:
        a = e.solicitud.aportes[0]
        r = Recurso(
            ong_id=e.ong_id,
            capacidad_id=a.capacidad_nacional_id,
            codigo_interno="segundo",
            nombre="Otro",
            cantidad_total=Decimal(10),
        )
        db.add(r)
        db.flush()
        segundo_id = r.id
        e.solicitud.aportes.append(
            a.model_copy(update={"aporte_id": "51", "recurso_nacional_id": r.id})
        )
        db.commit()
    otra = e.solicitud.model_copy(deep=True)
    otra.id_emergencia = "102"
    otra.adjudicacion_id = "otra"
    otra.aportes.reverse()
    barrera = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuras = [
            pool.submit(
                reservar, engine_migrado, e, s, k, Trabajador(), barrera=barrera
            )
            for s, k in [(e.solicitud, "uno"), (otra, "dos")]
        ]
        resultados = [f.result(timeout=10)[0] for f in futuras]
    assert sorted(resultados) == [201, 409]
    with Session(engine_migrado) as db:
        assert (
            cantidad_comprometida(db, e.recurso_id)
            == cantidad_comprometida(db, segundo_id)
            == Decimal(6)
        )


def test_edicion_de_total_espera_y_respeta_compromiso(engine_migrado: Engine) -> None:
    e = preparar(engine_migrado)
    reserva, edicion = Trabajador(), Trabajador()

    def editar() -> bool:
        with Session(engine_migrado) as db:
            edicion.pid = db.scalar(text("SELECT pg_backend_pid()"))
            edicion.iniciado.set()
            try:
                actualizar_recurso(
                    db,
                    e.ong_id,
                    e.recurso_id,
                    RecursoUpdate(
                        cantidad_total=Decimal(4), actualizado_en=e.actualizado_en
                    ),
                )
            except InventarioConflictivoError:
                db.rollback()
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(
            reservar, engine_migrado, e, e.solicitud, "reserva", reserva, pausar=True
        )
        try:
            assert reserva.bloqueado.wait(5)
            f2 = pool.submit(editar)
            esperar_bloqueo(engine_migrado, edicion, reserva)
        finally:
            reserva.continuar.set()
        assert f1.result(timeout=10)[0] == 201
        assert f2.result(timeout=10) is False
    with Session(engine_migrado) as db:
        assert db.get(Recurso, e.recurso_id).cantidad_total == Decimal(10)
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(6)


def test_vencimiento_historico_no_bloquea_reserva_tras_esperar(
    engine_migrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = preparar(engine_migrado)
    instante = [datetime.now(UTC)]

    class Reloj(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return instante[0]

    monkeypatch.setattr(servicio, "datetime", Reloj)
    holder, solicitante = Trabajador(), Trabajador()
    with Session(engine_migrado) as db:
        holder.pid = db.scalar(text("SELECT pg_backend_pid()"))
        holder.iniciado.set()
        db.scalar(select(Recurso).where(Recurso.id == e.recurso_id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            futura = pool.submit(
                reservar, engine_migrado, e, e.solicitud, "vence", solicitante
            )
            try:
                esperar_bloqueo(engine_migrado, solicitante, holder)
                instante[0] = e.vencimiento
            finally:
                db.rollback()
            assert futura.result(timeout=10)[0] == 201
    with Session(engine_migrado) as db:
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(6)
        assert (
            db.scalar(
                select(func.count())
                .select_from(Compromiso)
                .where(Compromiso.ong_id == e.ong_id)
            )
            == 1
        )
