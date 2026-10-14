"""Contrato protegido y competencia por capacidad, estado y límites temporales."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session
from test_database_models import DatosNacionales, crear_datos

from app.core.security import emitir_token
from app.db.models import (
    Capacidad,
    Cuenta,
    EstadoAcreditacion,
    EstadoOng,
    NivelRiesgo,
    RolNacional,
    TipoRecurso,
)
from app.db.session import get_db
from app.main import app
from app.schemas.certificaciones import (
    AcreditacionCreate,
    AlcanceCreate,
    CertificacionCreate,
    CodigoMotivo,
    EstadoVigencia,
)
from app.services.certificaciones import (
    consultar_certificaciones_ong,
    estado_vigencia,
    otorgar_acreditacion,
    publicar_certificacion,
)


@pytest.fixture
def datos(session: Session) -> DatosNacionales:
    datos = crear_datos(session, f"cert-{uuid4().hex}")
    session.commit()
    return datos


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    def database() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = database
    with TestClient(app) as cliente:
        yield cliente
    app.dependency_overrides.clear()


def auth(cuenta: Cuenta) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_token(cuenta.id)}"}


def cuenta_ong(session: Session, datos: DatosNacionales) -> Cuenta:
    cuenta = Cuenta(
        identificador_login=f"ong-{uuid4()}@example.test",
        ong_id=datos.ong.id,
        rol=RolNacional.ONG,
        password_hash="$argon2id$hash-de-prueba",
    )
    session.add(cuenta)
    session.commit()
    return cuenta


def test_catalogo_filtra_un_mismo_alcance_y_devuelve_todos(
    client: TestClient,
    session: Session,
    datos: DatosNacionales,
) -> None:
    segunda = Capacidad(
        codigo=f"AGUA-{uuid4()}",
        nombre="Agua",
        tipo=TipoRecurso.SUMINISTRO,
        unidad="litros",
        admite_fracciones=True,
    )
    session.add(segunda)
    session.flush()
    id_revision = publicar_certificacion(
        session,
        datos.admin.id,
        CertificacionCreate(
            codigo="MULTIPLE",
            revision=1,
            nombre="Múltiples alcances",
            alcances=[
                AlcanceCreate(
                    capacidad_id=datos.capacidad.id, riesgo_maximo=NivelRiesgo.BAJA
                ),
                AlcanceCreate(
                    capacidad_id=segunda.id, riesgo_maximo=NivelRiesgo.CRITICA
                ),
            ],
        ),
    )
    session.commit()
    ruta = "/api/v1/certificaciones"
    response = client.get(
        ruta,
        headers=auth(datos.integracion),
        params={
            "capacidadId": str(datos.capacidad.id),
            "nivelRiesgo": "ALTA",
        },
    )
    assert response.status_code == 200
    assert all(r["id"] != str(id_revision) for r in response.json())
    response = client.get(
        ruta,
        headers=auth(datos.admin),
        params={
            "capacidadId": str(segunda.id),
            "nivelRiesgo": "MEDIA",
        },
    )
    assert response.status_code == 200 and len(response.json()) == 1
    assert len(response.json()[0]["alcances"]) == 2
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.get(
            ruta, headers=auth(datos.admin), params={"capacidadId": str(uuid4())}
        ).json()
        == []
    )


def test_catalogo_inactivo_solo_admin_y_aliases(
    client: TestClient,
    session: Session,
    datos: DatosNacionales,
) -> None:
    datos.certificacion.activa = False
    session.commit()
    assert client.get("/api/v1/certificaciones", headers=auth(datos.admin)).json() == []
    params = {"incluirInactivas": "true"}
    assert (
        client.get(
            "/api/v1/certificaciones", headers=auth(datos.integracion), params=params
        ).status_code
        == 403
    )
    assert (
        len(
            client.get(
                "/api/v1/certificaciones", headers=auth(datos.admin), params=params
            ).json()
        )
        == 1
    )
    for params in ({"capacidadId": "incorrecto"}, {"nivelRiesgo": "MAXIMO"}):
        respuesta = client.get(
            "/api/v1/certificaciones", headers=auth(datos.admin), params=params
        )
        assert respuesta.status_code == 422
        assert isinstance(respuesta.json()["detail"], str)


@pytest.mark.parametrize("token", [None, "invalido"])
def test_consultas_exigen_jwt(
    client: TestClient, datos: DatosNacionales, token: str | None
) -> None:
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    for ruta in (
        "/api/v1/certificaciones",
        f"/api/v1/ongs/{datos.ong.id}/certificaciones",
    ):
        respuesta = client.get(ruta, headers=headers)
        assert respuesta.status_code == 401
        assert respuesta.headers["www-authenticate"] == "Bearer"


def test_ong_propietaria_y_roles_vigentes(
    client: TestClient,
    session: Session,
    datos: DatosNacionales,
) -> None:
    ong = cuenta_ong(session, datos)
    ruta = f"/api/v1/ongs/{datos.ong.id}/certificaciones"
    respuesta = client.get(ruta, headers=auth(ong))
    assert (
        respuesta.status_code == 200 and respuesta.json()["estadoOng"] == "HABILITADA"
    )
    assert respuesta.json()["capacidadesHabilitadas"][0]["nivelesRiesgoPermitidos"] == [
        "BAJA",
        "MEDIA",
        "ALTA",
    ]
    assert (
        client.get(
            f"/api/v1/ongs/{uuid4()}/certificaciones", headers=auth(ong)
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/ongs/{uuid4()}/certificaciones", headers=auth(datos.admin)
        ).status_code
        == 404
    )
    ong.activa = False
    session.commit()
    assert client.get(ruta, headers=auth(ong)).status_code == 401
    datos.origen.activo = False
    session.commit()
    assert client.get(ruta, headers=auth(datos.integracion)).status_code == 403


@pytest.mark.parametrize(
    "estado", [EstadoOng.PENDIENTE, EstadoOng.SUSPENDIDA, EstadoOng.BAJA]
)
def test_ong_no_habilitada_tiene_historia_y_motivos(
    client: TestClient,
    session: Session,
    datos: DatosNacionales,
    estado: EstadoOng,
) -> None:
    datos.ong.estado = estado
    session.commit()
    perfil = consultar_certificaciones_ong(session, datos.ong.id)
    assert len(perfil.acreditaciones) == 1 and not perfil.capacidades_habilitadas
    assert perfil.motivos_institucionales[0].codigo == CodigoMotivo(
        f"ONG_{estado.value}"
    )
    ong = cuenta_ong(session, datos)
    assert client.get(
        f"/api/v1/ongs/{datos.ong.id}/certificaciones", headers=auth(ong)
    ).status_code == (200 if estado == EstadoOng.PENDIENTE else 403)


@pytest.mark.parametrize(
    "segundos,esperado",
    [
        (-1, EstadoVigencia.FUTURA),
        (0, EstadoVigencia.VIGENTE),
        (9, EstadoVigencia.VIGENTE),
        (10, EstadoVigencia.VENCIDA),
    ],
)
def test_limites_exclusivos_sin_cron(segundos: int, esperado: EstadoVigencia) -> None:
    desde = datetime(2030, 1, 1, tzinfo=UTC)
    assert (
        estado_vigencia(
            EstadoAcreditacion.OTORGADA,
            desde,
            desde + timedelta(seconds=10),
            desde + timedelta(seconds=segundos),
        )
        == esperado
    )
    assert (
        estado_vigencia(
            EstadoAcreditacion.REVOCADA, desde, desde + timedelta(seconds=10), desde
        )
        == EstadoVigencia.REVOCADA
    )


def test_vencimiento_y_catalogo_inactivo_no_elevan_competencia(
    session: Session,
    datos: DatosNacionales,
) -> None:
    ahora = datetime.now(UTC)
    critica = publicar_certificacion(
        session,
        datos.admin.id,
        CertificacionCreate(
            codigo="CRITICA",
            revision=1,
            nombre="Crítica",
            alcances=[
                AlcanceCreate(
                    capacidad_id=datos.capacidad.id, riesgo_maximo=NivelRiesgo.CRITICA
                ),
            ],
        ),
    )
    for numero, desde, hasta in (
        ("vencida", ahora - timedelta(days=2), ahora - timedelta(days=1)),
        ("futura", ahora + timedelta(days=1), ahora + timedelta(days=2)),
    ):
        otorgar_acreditacion(
            session,
            datos.admin.id,
            AcreditacionCreate(
                ong_id=datos.ong.id,
                certificacion_id=critica,
                emisor="Autoridad",
                numero_credencial=numero,
                vigente_desde=desde,
                vigente_hasta=hasta,
            ),
        )
    session.commit()
    perfil = consultar_certificaciones_ong(session, datos.ong.id, ahora=ahora)
    assert len(perfil.acreditaciones) == 3
    assert perfil.capacidades_habilitadas[0].riesgo_maximo == NivelRiesgo.ALTA
    datos.certificacion.activa = False
    session.commit()
    perfil = consultar_certificaciones_ong(session, datos.ong.id, ahora=ahora)
    assert not perfil.capacidades_habilitadas
    assert any(
        m.codigo == CodigoMotivo.CERTIFICACION_INACTIVA
        for a in perfil.acreditaciones
        for m in a.motivos
    )


def test_una_capacidad_inactiva_no_descarta_otros_alcances(
    session: Session, datos: DatosNacionales
) -> None:
    otra = Capacidad(
        codigo=f"OTRA-{uuid4()}",
        nombre="Otra",
        tipo=TipoRecurso.SUMINISTRO,
        unidad="kg",
        admite_fracciones=True,
    )
    session.add(otra)
    session.flush()
    certificacion = publicar_certificacion(
        session,
        datos.admin.id,
        CertificacionCreate(
            codigo="DOS",
            revision=1,
            nombre="Dos capacidades",
            alcances=[
                AlcanceCreate(
                    capacidad_id=datos.capacidad.id, riesgo_maximo=NivelRiesgo.ALTA
                ),
                AlcanceCreate(capacidad_id=otra.id, riesgo_maximo=NivelRiesgo.MEDIA),
            ],
        ),
    )
    otorgar_acreditacion(
        session,
        datos.admin.id,
        AcreditacionCreate(
            ong_id=datos.ong.id,
            certificacion_id=certificacion,
            emisor="Autoridad",
            numero_credencial="dos",
            vigente_desde=datetime.now(UTC) - timedelta(days=1),
            vigente_hasta=datetime.now(UTC) + timedelta(days=1),
        ),
    )
    session.commit()
    otra.activa = False
    session.commit()
    perfil = consultar_certificaciones_ong(session, datos.ong.id)
    assert len(perfil.capacidades_habilitadas) == 1
    assert len(perfil.capacidades_habilitadas[0].acreditacion_ids) == 2
    assert any(
        m.capacidad_id == otra.id for a in perfil.acreditaciones for m in a.motivos
    )


@pytest.mark.parametrize(
    "cambio",
    [
        {"vigenteDesde": "2030-01-01T00:00:00"},
        {"vigenteHasta": "2020-01-01T00:00:00Z"},
        {"emisor": " "},
        {"registradaPorId": str(uuid4())},
        {"estado": "OTORGADA"},
    ],
)
def test_acreditacion_rechaza_entradas_invalidas(cambio: dict[str, str]) -> None:
    entrada = {
        "ongId": str(uuid4()),
        "certificacionId": str(uuid4()),
        "emisor": "Autoridad",
        "numeroCredencial": "oficial",
        "vigenteDesde": "2030-01-01T00:00:00Z",
        "vigenteHasta": "2031-01-01T00:00:00Z",
    }
    with pytest.raises(ValidationError):
        AcreditacionCreate.model_validate({**entrada, **cambio})


def test_openapi_publica_bearer_y_no_crud_ong(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for ruta in ("/api/v1/certificaciones", "/api/v1/ongs/{ong_id}/certificaciones"):
        assert spec["paths"][ruta]["get"]["security"] == [{"HTTPBearer": []}]
        assert set(spec["paths"][ruta]) == {"get"}
