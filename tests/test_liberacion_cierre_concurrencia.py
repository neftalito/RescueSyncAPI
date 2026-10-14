"""Locks reales entre liberación, cierre y reservas, sin transacciones compartidas."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine, event, select, text
from sqlalchemy.orm import Session
from test_compromisos_concurrencia import (
    Escenario,
    Trabajador,
    esperar_bloqueo,
    preparar,
    reservar,
)

from app.db.models import Compromiso, Cuenta, EstadoCompromiso, EstadoProyecto, Proyecto
from app.schemas.proyectos import (
    ConfirmacionCierre,
    ConfirmacionLiberacion,
    FinalizacionRequest,
)
from app.services.compromisos import registrar_compromisos
from app.services.inventario import cantidad_comprometida
from app.services.liberaciones import liberar_compromiso
from app.services.operaciones import ErrorOperacion
from app.services.proyectos import cerrar_proyecto


def comprometido(engine: Engine) -> tuple[Escenario, UUID, UUID]:
    e = preparar(engine)
    with Session(engine) as db:
        cuenta = db.get(Cuenta, e.cuenta_id)
        assert cuenta is not None
        r = registrar_compromisos(db, cuenta, e.solicitud, "crear")
        return e, r.compromiso_ids[0], r.proyecto_id


def transicion(
    engine: Engine,
    e: Escenario,
    destino: UUID,
    tipo: Literal["liberar", "cerrar"],
    clave: str,
    estado: Trabajador,
    *,
    pausar: bool = False,
) -> tuple[int, ConfirmacionLiberacion | ConfirmacionCierre | None]:
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
            tabla = "FROM recurso" if tipo == "liberar" else "FROM proyecto"
            if (
                pausar
                and tabla in sql
                and "FOR UPDATE" in sql
                and not estado.bloqueado.is_set()
            ):
                estado.bloqueado.set()
                assert estado.continuar.wait(10)

        event.listen(connection, "after_cursor_execute", detener)
        try:
            cuenta = db.get(Cuenta, e.cuenta_id)
            assert cuenta is not None
            datos = FinalizacionRequest(case_id="100")
            try:
                if tipo == "liberar":
                    resultado = liberar_compromiso(db, cuenta, destino, datos, clave)
                else:
                    resultado = cerrar_proyecto(db, cuenta, destino, datos, clave)
                return 200, resultado
            except ErrorOperacion as error:
                return error.status, None
        finally:
            event.remove(connection, "after_cursor_execute", detener)


@pytest.mark.parametrize("misma_clave", [False, True])
def test_liberaciones_simultaneas_devuelven_una_vez(
    engine_migrado: Engine, misma_clave: bool
) -> None:
    e, cid, _ = comprometido(engine_migrado)
    primera, segunda = Trabajador(), Trabajador()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(
            transicion, engine_migrado, e, cid, "liberar", "uno", primera, pausar=True
        )
        try:
            assert primera.bloqueado.wait(5)
            f2 = pool.submit(
                transicion,
                engine_migrado,
                e,
                cid,
                "liberar",
                "uno" if misma_clave else "dos",
                segunda,
            )
            esperar_bloqueo(engine_migrado, segunda, primera)
        finally:
            primera.continuar.set()
        r1, r2 = f1.result(timeout=10), f2.result(timeout=10)
    assert r1[0] == r2[0] == 200
    assert isinstance(r1[1], ConfirmacionLiberacion)
    assert isinstance(r2[1], ConfirmacionLiberacion)
    assert r1[1].liberado_en == r2[1].liberado_en
    if misma_clave:
        assert r1[1] == r2[1]
    with Session(engine_migrado) as db:
        c = db.get(Compromiso, cid)
        assert c is not None and c.estado == EstadoCompromiso.LIBERADO
        assert c.liberado_por_id == e.cuenta_id
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(0)


@pytest.mark.parametrize("primero", ["reserva", "cierre"])
def test_cierre_y_compromiso_se_serializan_por_proyecto(
    engine_migrado: Engine, primero: str
) -> None:
    e = preparar(engine_migrado)
    e.solicitud.id_emergencia = "10"
    with Session(engine_migrado) as db:
        cuenta = db.get(Cuenta, e.cuenta_id)
        assert cuenta is not None
        pid = db.scalar(
            select(Proyecto.id).where(
                Proyecto.sistema_origen_id == cuenta.sistema_origen_id,
                Proyecto.emergencia_ref == "10",
            )
        )
        assert pid is not None
    inicial, espera = Trabajador(), Trabajador()
    with ThreadPoolExecutor(max_workers=2) as pool:
        if primero == "reserva":
            f1 = pool.submit(
                reservar,
                engine_migrado,
                e,
                e.solicitud,
                "reserva",
                inicial,
                pausar=True,
            )
        else:
            f1 = pool.submit(
                transicion,
                engine_migrado,
                e,
                pid,
                "cerrar",
                "cierre",
                inicial,
                pausar=True,
            )
        try:
            assert inicial.bloqueado.wait(5)
            if primero == "reserva":
                f2 = pool.submit(
                    transicion, engine_migrado, e, pid, "cerrar", "cierre", espera
                )
            else:
                f2 = pool.submit(
                    reservar, engine_migrado, e, e.solicitud, "reserva", espera
                )
            esperar_bloqueo(engine_migrado, espera, inicial)
        finally:
            inicial.continuar.set()
        assert f1.result(timeout=10)[0] == (201 if primero == "reserva" else 200)
        assert f2.result(timeout=10)[0] == 409
    with Session(engine_migrado) as db:
        assert db.get(Proyecto, pid).estado == (
            EstadoProyecto.ABIERTO if primero == "reserva" else EstadoProyecto.TERMINADO
        )
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(
            6 if primero == "reserva" else 0
        )


def test_nueva_emergencia_espera_liberacion_y_recalcula_stock(
    engine_migrado: Engine,
) -> None:
    e, cid, _ = comprometido(engine_migrado)
    otra = e.solicitud.model_copy(deep=True)
    otra.id_emergencia = "102"
    otra.adjudicacion_id = "otra"
    primera, segunda = Trabajador(), Trabajador()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(
            transicion, engine_migrado, e, cid, "liberar", "lib", primera, pausar=True
        )
        try:
            assert primera.bloqueado.wait(5)
            f2 = pool.submit(reservar, engine_migrado, e, otra, "otra", segunda)
            esperar_bloqueo(engine_migrado, segunda, primera)
        finally:
            primera.continuar.set()
        assert f1.result(timeout=10)[0] == 200
        assert f2.result(timeout=10)[0] == 201
    with Session(engine_migrado) as db:
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(6)
        assert db.get(Compromiso, cid).estado == EstadoCompromiso.LIBERADO


def test_cierre_espera_la_ultima_liberacion_confirmada(engine_migrado: Engine) -> None:
    e, cid, pid = comprometido(engine_migrado)
    primera, segunda = Trabajador(), Trabajador()
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(
            transicion, engine_migrado, e, cid, "liberar", "lib", primera, pausar=True
        )
        try:
            assert primera.bloqueado.wait(5)
            f2 = pool.submit(
                transicion, engine_migrado, e, pid, "cerrar", "cierre", segunda
            )
            esperar_bloqueo(engine_migrado, segunda, primera)
        finally:
            primera.continuar.set()
        assert f1.result(timeout=10)[0] == f2.result(timeout=10)[0] == 200
    with Session(engine_migrado) as db:
        assert db.get(Proyecto, pid).estado == EstadoProyecto.TERMINADO
        assert cantidad_comprometida(db, e.recurso_id) == Decimal(0)
