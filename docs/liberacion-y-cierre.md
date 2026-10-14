# Liberación por ONG y cierre nacional (T33)

Relacionado con [issue #13](https://github.com/neftalito/RescueSyncAPI/issues/13).

Requiere JWT de INTEGRACION del emisor dueño o ADMIN_NACIONAL, `Idempotency-Key`
no vacía de hasta 160 caracteres y body `{"caseId":"100"}`. El caso debe coincidir
con el proyecto. La ONG registra su finalización local; Bonita/T37 comunica la
transición con su cuenta técnica. Una cuenta ONG no libera/cierra directamente.

## Liberación independiente

`POST /api/v1/compromisos/{compromisoId}/liberacion` libera una participante.
Cada compromiso pertenece a una sola ONG, incluso en un consorcio. Si tiene
varios compromisos finalizados, invocar por cada uno con claves estables distintas.
Los compromisos de ONGs que continúan trabajando permanecen ACTIVO.

La respuesta `200` contiene `operacionId`, `proyectoId`, `compromisoId`,
`ongNacionalId` y `liberadoEn`. El servicio reclama la clave, recarga permisos,
bloquea proyecto, recursos ordenados por UUID y compromiso; después pasa
ACTIVO a LIBERADO, guardando autor y primera fecha. Conserva todos los ítems.

La disponibilidad aumenta al dejar de sumar esos ítems como activos. No se
incrementa `cantidad_total`, no hay otro contador ni reposición de consumo físico.
Inventario individual y disponibilidad global T30 reflejan el cambio confirmado.

Una ONG suspendida/de baja, recurso/capacidad inactivos o acreditación vencida
no impiden devolver una reserva. Cuenta técnica/administrativa y emisor sí
deben conservar sus permisos vigentes.

Misma clave/contenido reproduce la confirmación original. Otra clave para un
compromiso ya LIBERADO conserva su primera fecha/autor y no devuelve stock otra
vez. El GET T32 muestra el historial vigente. La huella incluye destino y body:
reutilizar una clave LIBERAR para otro compromiso/caso recibe `409`. Las claves
COMPROMETER/LIBERAR/CERRAR_PROYECTO tienen namespaces separados.

## Cierre sin reservas activas

`POST /api/v1/proyectos/{proyectoId}/cierre` bloquea el mismo proyecto que T32
antes de consultar compromisos activos. Si queda alguno, devuelve `409` y no
libera ni cierra nada. Si no hay activos, pasa ABIERTO a TERMINADO registrando
autor/fecha y confirmación. Respuesta `200`: `operacionId`, `proyectoId`, `cerradoEn`.

Reintentos con la misma u otra clave conservan el primer cierre. TERMINADO es
terminal: T32 rechaza adjudicaciones nuevas. Un replay del POST de creación
puede reproducir su confirmación original sin recrear ni reactivar la reserva.

El lock de proyecto impide una reserva entre comprobar activos y cerrar. Un
cierre que espera una reserva ve sus activos y recibe `409`; si primero se
cierra, la reserva posterior falla. Al esperar la última liberación, se consulta
su estado confirmado antes de terminar.

Una emergencia sin adjudicaciones no genera proyecto nacional al validar T31.
T37 debe tratar su recorrido local explícitamente; este endpoint no crea
proyectos vacíos ni reemplaza la confirmación local/Bonita.

## Recuperación y verificación

Ambos usan READ COMMITTED y límites de espera T32. Timeout/deadlock/fallo de
base provoca rollback y `503` seguro. Reintentar la misma clave o consultar el
compromiso conocido: un timeout puede ocurrir después del commit. No generar
otra clave para repetir un resultado incierto. Respuestas `no-store`;
JWT/cuenta inválidos `401`, permisos `403`, referencias inexistentes `404`,
correlación/estado/clave conflictivos `409` y entradas inválidas `422`.

```bash
docker compose run --rm --no-deps -e APP_ENV=test api pytest tests/test_liberaciones.py tests/test_proyectos.py tests/test_liberacion_cierre_concurrencia.py
```

Las pruebas PostgreSQL observan `pg_blocking_pids` entre conexiones independientes:
liberaciones simultáneas, nueva emergencia esperando stock, cierre contra reserva
y cierre esperando la última liberación. Cubren además multiONG, auditoría,
pérdida de habilitación, disponibilidad y permisos.

Se reutiliza el esquema sin migración ni variables adicionales a T32. La
finalización web, conectores y callback `/resolver` corresponden a T37;
esta tarea implementa los endpoints y garantías del servicio nacional.
