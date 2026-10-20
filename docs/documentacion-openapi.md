# Documentación nacional — T40

Relacionado con [issue #19](https://github.com/neftalito/RescueSyncAPI/issues/19).

## Consulta y artefactos de entrega

En desarrollo con Compose: [Swagger UI](http://localhost:8001/docs),
[ReDoc](http://localhost:8001/redoc) y
[OpenAPI JSON](http://localhost:8001/openapi.json). En otro entorno, reemplazar
el origen por la URL de la API desplegada. Estos accesos y health son públicos.

- [Especificación OpenAPI exportada](./generated/openapi.json): contrato completo,
  modelos, ejemplos de solicitudes/respuestas, permisos y códigos de error.
- [Referencia PDF](./generated/documentacion-api.pdf): generada desde el mismo
  esquema; las secciones y modelos tienen enlaces internos.
- [Ejemplos correlacionados](../app/api/ejemplos.py): datos ficticios publicados
  por Swagger. Los UUID y credenciales ilustrativos se reemplazan antes de usar
  un entorno real; no son identidades ni secretos aprovisionados.

## Autenticación y permisos

`POST /api/v1/login` recibe JSON con `identificadorLogin` y `password`. Su respuesta
contiene `access_token`, `token_type=bearer` y `expires_in` en segundos. Enviar
`Authorization: Bearer <access_token>` en las operaciones protegidas; en Swagger,
pegar el token en **Authorize**. No enviar el token en query strings.

JWT valida firma HS256, expiración, issuer y audience. La autorización recarga
cuenta, ONG y emisor vigentes desde PostgreSQL. Los roles no se toman del JWT.
Cuentas técnicas ONG: duración de 300 segundos; otras cuentas:
`JWT_ACCESS_SECONDS`, 1800 por defecto. Ante expiración, autenticar nuevamente;
no hay refresh tokens. `BONITA_CALLBACK_TOKEN` autentica callbacks locales y
no sustituye al JWT nacional. Ver [cuentas técnicas](./acceso-automatico-ong.md).

Todas las rutas de la tabla llevan `/api/v1`:

Los [endpoints de mantenimiento](./mantenimiento-db.md) usan la contraseña
`DB_MAINTENANCE_PASSWORD` en `X-DB-Maintenance-Password`, con esquema Swagger
`DBMaintenancePassword`, independiente del JWT. Funcionan también en producción;
sin configuración devuelven `403` y con contraseña ausente/incorrecta, `401`.

| Método y ruta | Acceso |
| --- | --- |
| `POST /mantenimiento/seed`, `POST /mantenimiento/seed-masivo`, `POST /mantenimiento/flush` | Contraseña de mantenimiento configurada; no requiere cuenta ni JWT |
| `GET /health`, `GET /health/database` | Público |
| `POST /login`, `POST /ongs` | Público; onboarding crea una ONG pendiente |
| `GET /me`, `GET /capacidades`, `GET /unidades` | ONG, ADMIN_NACIONAL o INTEGRACION vigentes |
| `POST /capacidades` | Sólo ADMIN_NACIONAL |
| `GET /ongs/{ong_id}/recursos` | ONG propietaria, ADMIN_NACIONAL o INTEGRACION |
| `POST /ongs/{ong_id}/recursos`, `PATCH /ongs/{ong_id}/recursos/{recurso_id}` | ONG propietaria o ADMIN_NACIONAL |
| `GET /certificaciones` | Cuenta vigente; `incluirInactivas=true` sólo ADMIN_NACIONAL |
| `GET /ongs/{ong_id}/certificaciones` | ONG propia, ADMIN_NACIONAL o INTEGRACION |
| `GET /ongs/habilitadas`, `GET /recursos/disponibilidad` | ONG, ADMIN_NACIONAL o INTEGRACION vigentes |
| `POST /validaciones`, `POST /compromisos` | INTEGRACION de `sistemaOrigen` o ADMIN_NACIONAL seleccionando emisor activo |
| `GET /compromisos/{compromiso_id}` | INTEGRACION del emisor dueño o ADMIN_NACIONAL |
| `POST /compromisos/{compromiso_id}/liberacion`, `POST /proyectos/{proyecto_id}/cierre` | INTEGRACION del emisor dueño o ADMIN_NACIONAL; `caseId` correlacionado |
| `PUT /integraciones/ongs/{referencia_local}` | Sólo INTEGRACION con emisor activo |

`ONG` no puede adjudicar, liberar ni cerrar proyectos nacionales directamente.
La finalización se registra localmente y Bonita comunica la transición con la
identidad técnica autorizada. Una ONG no se habilita ni emite certificaciones
para sí misma. Los catálogos administrativos se mantienen mediante CLI.

## Ejemplos y consumidores

Swagger y el PDF contienen ejemplos de cada respuesta y de cada operación con
cuerpo. Cada error documentado incluye un ejemplo JSON con `detail` seguro.
El login conserva sus campos camelCase y la respuesta OAuth habitual
`access_token`, `token_type`, `expires_in`. Las cantidades nacionales exactas se
transportan como strings decimales; fechas en UTC e identificadores nacionales UUID.

El ejemplo de `POST /validaciones` coincide con
[la fixture T34](../tests/fixtures/snapshot_t34.json): `contratoVersion=2`, ronda
cerrada, ofertas/versiones y aportes. La adjudicación usa los mismos aportes,
ONGs, recursos, capacidades y cantidades. Las respuestas de compromiso,
consulta, liberación y cierre mantienen la correlación de proyecto y compromiso.
El GET de compromiso ilustra el estado LIBERADO a las 19:00; la consulta de
acreditaciones muestra su revocación al día siguiente, conservando el historial.

Los contratos existentes de los consumidores se describen en
[ofertas consolidadas T34](https://github.com/neftalito/RescueSync/blob/develop/docs/ofertas-consolidadas-nacionales.md)
y [Bonita/backend local T36–T37](https://github.com/neftalito/RescueSync/blob/develop/docs/bonita/contratos-t36-t37.md).
Se validaron localmente 11 ejemplos de transporte contra los DTO de RescueSync
(commit `117c97b3c4190d3876c577be4c4fc8d4d0cf0c1f`): snapshot T34,
validación, adjudicación, confirmación y detalle de compromiso, liberación,
cierre, token, cuenta, recursos y aprovisionamiento. Esta comprobación valida
compatibilidad de estructuras; no es una ejecución distribuida del proceso.

El frontend consume exclusivamente el backend local. No se igualan IDs locales
con UUID nacionales ni se comparten bases. Los ejemplos no ejecutan el proceso
Bonita ni prueban su despliegue real.

## Validación, compromiso y cierre

- [Validación transitoria](./validaciones.md): snapshot READ ONLY / REPEATABLE
  READ; capacidades, niveles de riesgo, perfiles y motivos por aporte. No guarda
  ofertas/resultados ni crea proyectos o reservas. Una evaluación no garantiza
  disponibilidad futura.
- [Compromiso e idempotencia](./compromisos.md): adjudicación atómica,
  revalidación de permisos/competencias/stock y locks PostgreSQL en orden estable.
  Inventario, compromiso y liberación comparten el criterio de locking; no hay
  HTTP mientras se mantienen locks. Fallar un aporte revierte todos.
- [Liberación por ONG y cierre](./liberacion-y-cierre.md): cada compromiso libera
  sólo su ONG una vez, conservando historial. Cerrar no libera otros compromisos;
  exige cero activos y comparte el lock de proyecto con nuevas adjudicaciones.

`Idempotency-Key` es estable por emisor y tipo de operación. Misma clave y
contenido reproduce la confirmación original; mismo identificador con contenido
o destino distinto da `409`. Un timeout puede suceder después del commit:
reintentar con **la misma clave**, o consultar el compromiso conocido. No generar
otra clave para un resultado incierto. El PUT de aprovisionamiento usa su
referencia UUID durable por emisor y datos idénticos, sin esa cabecera.

## Errores

| Código | Interpretación |
| --- | --- |
| `401` | Login incorrecto, JWT ausente/inválido/expirado o cuenta inactiva |
| `403` | Rol, ONG, emisor o destino no autorizado |
| `404` | Referencia nacional inexistente |
| `409` | Unicidad, versión, stock, estado, caso o clave idempotente en conflicto |
| `422` | Datos, cantidades, unidad o estructura inválidos |
| `500` | Inconsistencia interna de inventario; detalle seguro |
| `503` | Fallo temporal de base; en escrituras idempotentes, conservar la clave |

Los códigos aplicables y sus modelos figuran en cada operación de OpenAPI.
No se devuelven SQL, trazas, secretos ni cuerpos de ofertas en los errores.
El `503` de health/database también devuelve JSON con `detail`.

## Regeneración y verificación

Desde la raíz nacional, con Python 3.13:

```bash
python -m pip install -r requirements-dev.txt
APP_ENV=test python docs/scripts/exportar_openapi_pdf.py
```

O utilizando la imagen de desarrollo:

```bash
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -e APP_ENV=test api python docs/scripts/exportar_openapi_pdf.py
```

El script no inicia un servidor, no ejecuta lifespan ni conecta a PostgreSQL.
Ambos archivos se guardan en `docs/generated/`. Opciones:

```bash
python docs/scripts/exportar_openapi_pdf.py --solo-json
python docs/scripts/exportar_openapi_pdf.py --url http://localhost:8001/openapi.json
python docs/scripts/exportar_openapi_pdf.py --archivo contrato.json --salida /tmp/api.pdf --salida-json /tmp/contrato.json
```

Después de cambiar rutas, modelos, permisos, ejemplos o dependencias que afecten
OpenAPI, regenerar y versionar JSON/PDF juntos. El JSON se serializa de forma
estable; el PDF incluye fecha de generación. La antigua copia
`docs/documentacion-api.pdf` se reemplaza por el único PDF en `docs/generated/`.

```bash
docker compose run --rm --no-deps -e APP_ENV=test api pytest tests/test_openapi.py tests/test_exportar_openapi.py
```

Las pruebas validan ejemplos contra JSON Schema y DTO, campos de transporte,
seguridad, errores, correlación T34 y equivalencia de la exportación con
`/openapi.json`. También ejecutan la exportación desde otro directorio y una
fuente alternativa. El check `quality` ejecuta estas pruebas junto a la suite
PostgreSQL y los controles existentes del repositorio.

## Evidencia de T40

Este complemento parte del commit `afc547b`, integrado mediante
[PR #41](https://github.com/neftalito/RescueSyncAPI/pull/41) y
[PR #42](https://github.com/neftalito/RescueSyncAPI/pull/42).
La evidencia de este complemento se registra en su PR hacia `develop`, enlazado
al issue #19, con el resultado de `quality` para el commit revisado.

La integración está pendiente mientras ese PR permanezca abierto. La generación
y las pruebas locales no acreditan despliegue cloud ni E2E real con Bonita.
Horas efectivas de T40: pendientes de informar por el responsable; no se deducen
de la estimación ni de tiempos automáticos. El Excel local se conserva sin cambios.
