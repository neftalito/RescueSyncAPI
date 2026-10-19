# Compromiso transaccional de recursos (T32)

Relacionado con [issue #12](https://github.com/neftalito/RescueSyncAPI/issues/12).

`POST /api/v1/compromisos` recibe una adjudicación completa después de la
selección municipal. Requiere JWT INTEGRACION de su emisor, o ADMIN_NACIONAL
seleccionando un emisor activo, y `Idempotency-Key` no vacía de hasta 160 caracteres.
Las cuentas ONG no ejecutan adjudicaciones nacionales.

```json
{
  "sistemaOrigen": "instalacion-prueba",
  "idEmergencia": "101",
  "caseId": "100",
  "convocatoriaId": "20",
  "adjudicacionId": "seleccion-101-1",
  "aportes": [{
    "ofertaId": "30",
    "version": 1,
    "loteId": "40",
    "aporteId": "50",
    "ongNacionalId": "00000000-0000-4000-8000-000000000101",
    "recursoNacionalId": "00000000-0000-4000-8000-000000000103",
    "capacidadNacionalId": "00000000-0000-4000-8000-000000000102",
    "riesgoRequerido": "MEDIA",
    "cantidad": "6.000",
    "unidad": "persona"
  }]
}
```

Estos UUID son ejemplos. Los IDs locales positivos también pueden recibirse como
enteros; se normalizan a referencias opacas. `adjudicacionId` debe identificar
una selección confirmada e inmutable, producida por T37; no está en el snapshot
T34 porque se genera después de evaluar. `aporteId` es el congelado de T34.
Una solicitud no repite aportes ni mezcla versiones de una misma oferta.

La respuesta `201` contiene `operacionId`, `proyectoId`, `compromisoIds` y
`registradoEn`. Un consorcio produce un compromiso por ONG, con todos sus ítems;
todos se confirman o se revierten. Sólo se guardan asignaciones efectivas y
referencias mínimas; no el cuerpo de las ofertas.

`GET /api/v1/compromisos/{id}` consulta el estado vigente, ONG, proyecto, referencias
de caso/emergencia/adjudicación/oferta/version y cantidades por recurso. Sólo el
emisor dueño o administración pueden leerlo. Las respuestas usan `no-store`.

## Idempotencia y reconciliación

La clave es única por emisor y tipo de operación, permitiendo rotación de cuentas
técnicas. La huella SHA-256 usa DTO validado, referencias/UUID normalizados,
cantidades a tres decimales y orden estable de aportes. `6`, `6.0` y `6.000`
identifican la misma cantidad; reordenar aportes no crea otra reserva.

Misma clave y contenido reproduce la confirmación original y código `201`;
cambiar contenido/destino da `409`. La respuesta de creación es estable incluso
después de liberar; el GET muestra el estado actual. Repetir una adjudicación
con otra clave también da `409`, sin extenderla con otros participantes.
Una operación fallida hace rollback y no deja un reclamo incompleto confirmado.

Después de un timeout, repetir con la misma clave recupera los UUID aunque el
cliente no los haya recibido. Si ya los conoce, puede consultar el GET. No
generar otra clave para repetir un resultado incierto. Los permisos vigentes
se verifican también para reproducir confirmaciones anteriores.

## Transacción y orden de locks

Usar PostgreSQL READ COMMITTED. Orden: reclamo único → cuenta/emisor compartidos
→ proyecto exclusivo → ONGs compartidas → capacidades/revisiones compartidas
→ recursos exclusivos. Cada conjunto se ordena por UUID. Edición/alta de
inventario toma ONG antes del recurso/capacidad; liberación T33 comparte el orden.
Los cambios de habilitación/acreditación existentes toman ONG exclusiva.

Crear/reutilizar proyecto por `(emisor, emergencia)`; otro caso para esa emergencia
o un proyecto terminado produce `409`. El proyecto sólo nace con una adjudicación
exitosa, nunca al validar ofertas. Después de adquirir todos los locks, una nueva
sentencia recalcula compromisos activos y se toma la hora UTC de evaluación.
Se revalidan pertenencia, actividad, capacidades/unidades/fracciones, competencia
vigente y cantidades agregadas por recurso, incluso entre ofertas y lotes distintos.

Las reservas usan `total - SUM(ítems de compromisos ACTIVO)` como única disponibilidad.
No se guarda un contador adicional, no hay reserva parcial ni HTTP dentro de locks.
Una credencial que venció durante una espera no habilita la asignación.
T31 es informativo; su resultado previo no garantiza stock o permisos actuales.

RescueSync/Bonita deben garantizar cierre, consentimiento y cantidades ofrecidas
de la selección local. Esta API no accede a sus bases ni puede comprobar el
dominio local a partir de referencias externas. T35–T37 implementan ese recorrido.

`OPERACION_LOCK_TIMEOUT_MS` vale 5000 y `OPERACION_STATEMENT_TIMEOUT_MS`, 15000
por defecto; se aplican por transacción y admiten configuración por entorno.
Un timeout/deadlock/fallo de base revierte la transacción y devuelve un `503`
seguro para reintentar con la misma clave. No se imprimen SQL o cuerpos de ofertas.

## Verificación

```bash
docker compose run --rm --no-deps -e APP_ENV=test api pytest tests/test_compromisos.py tests/test_compromisos_concurrencia.py
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
```

Las pruebas usan schemas PostgreSQL aislados y conexiones/transacciones
independientes. Observan `pg_blocking_pids` para probar esperas reales; cubren dos
emergencias, reintentos simultáneos, recursos en orden inverso, edición de total,
vencimiento durante espera, multiONG/rollback, permisos y stock repetido.
Se reutiliza el esquema `20261004_0001`; no hay migración nueva.
