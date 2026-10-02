# Bloqueo de recursos de las ONG

Este documento describe el diseño propuesto para comprometer y liberar recursos
en la API nacional de RescueSync. Corresponde a T32, T33 y su integración con
Bonita en T37. Los modelos y endpoints de negocio todavía deben implementarse;
esta guía desarrolla el
[plan de implementación de la Entrega 3](./PLAN_IMPLEMENTACION_ENTREGA_3.md).

## Momento del bloqueo

El bloqueo representa un compromiso de cantidades de recursos de una ONG para
un proyecto. Ocurre después de que el municipio adjudica una oferta:

1. La ONG presenta su oferta en la aplicación local.
2. Al cerrar la convocatoria, Bonita solicita las ofertas consolidadas y llama
   a la API nacional para validar capacidades y consultar disponibilidad.
3. El municipio selecciona las ofertas y cantidades adjudicadas.
4. Bonita solicita el compromiso a la API nacional con su cuenta de integración.
5. La API nacional vuelve a validar disponibilidad y habilitaciones, registra
   los compromisos y confirma la transacción.
6. Bonita confirma la adjudicación en la aplicación local y notifica a las ONG.

Presentar o validar una oferta no reserva recursos. El frontend consume
únicamente el backend local; Bonita orquesta el compromiso nacional.

Por ejemplo, si una ONG tiene 10 ambulancias y compromete 6 para una emergencia,
quedan 4 disponibles para otros proyectos. Se reservan cantidades, por lo que
un booleano `bloqueado` sobre todo el recurso no alcanza para este diseño.

## Modelo de datos propuesto

| Tabla | Datos principales |
| --- | --- |
| `recurso` | ID, ONG propietaria, tipo/capacidad, unidad y cantidad total. |
| `proyecto` | ID, sistema de origen, referencia de emergencia y estado. |
| `compromiso` | ID, proyecto, ONG, estado `ACTIVO` o `LIBERADO` y fechas. |
| `compromiso_item` | Compromiso, recurso y cantidad comprometida. |
| `operacion_idempotente` | Emisor/cuenta, operación, clave, huella del contenido y resultado mínimo. |

Un compromiso corresponde a una ONG dentro de un proyecto. Una solicitud puede
comprometer recursos de varias ONG y debe confirmarse completa o revertirse
completa. El proyecto tiene una referencia única por
`(sistemaOrigen, emergenciaId)`.

La disponibilidad se calcula a partir de los compromisos activos:

```text
disponible = cantidad_total − suma de cantidades de compromisos activos
```

Usar `Decimal` en Python y `Numeric(14,3)` en PostgreSQL. El total debe ser no
negativo y cada cantidad comprometida debe ser positiva. Mantener timestamps
con zona horaria en UTC y definir restricciones, índices y claves foráneas
nacionales mediante migraciones Alembic.

Los IDs nacionales propuestos son UUID. Las referencias locales de emergencia,
convocatoria, oferta, versión y caso de Bonita sirven para trazabilidad y no son
claves foráneas entre bases. La API nacional conserva compromisos efectivos y
referencias mínimas; la evaluación de ofertas es transitoria.

## Endpoints propuestos

| Método y ruta | Comportamiento |
| --- | --- |
| `POST /api/v1/validaciones` | Evalúa capacidades y consulta disponibilidad sin reservar. |
| `POST /api/v1/compromisos` | Compromete atómicamente las cantidades adjudicadas. |
| `GET /api/v1/compromisos/{id}` | Consulta el resultado, incluso después de un timeout. |
| `POST /api/v1/compromisos/{id}/liberacion` | Libera una sola vez el compromiso de una ONG. |
| `PATCH /api/v1/ongs/{id}/recursos/{recursoId}` | Modifica el total sin bajarlo de lo comprometido. |
| `POST /api/v1/proyectos/{id}/cierre` | Cierra el proyecto cuando no quedan compromisos activos. |

Compromiso, liberación y cierre requieren JWT nacional y permisos de integración
o administración nacional. La cuenta de integración sólo opera proyectos de su
emisor autorizado, que se obtiene de la cuenta autenticada. Una ONG gestiona su
propio inventario y comunica su finalización desde la aplicación local.

El JWT nacional y el token de callbacks locales de Bonita son credenciales
distintas. El `caseId` permite correlacionar el flujo, pero no reemplaza la
autenticación ni la autorización.

## Transacción de compromiso y concurrencia

El servicio de compromiso debe ejecutar los siguientes pasos en una única
transacción:

1. Autenticar y autorizar al emisor, y reclamar la clave de idempotencia mediante
   una restricción única.
2. Crear o recuperar el proyecto y bloquearlo; comprobar que admite nuevos
   compromisos.
3. Agrupar las cantidades solicitadas por recurso. Si aparece varias veces,
   comprobar la suma de todas las cantidades, incluso entre ofertas distintas.
4. Bloquear las filas de todos los recursos involucrados con
   `SELECT ... FOR UPDATE`, siempre ordenadas por ID.
5. Después de adquirir esos bloqueos, recalcular los compromisos activos en una
   consulta posterior y validar disponibilidad, pertenencia a la ONG, unidades,
   permisos y habilitaciones vigentes para la capacidad y el riesgo requeridos.
6. Si todos los ítems son válidos, insertar los compromisos y sus ítems, guardar
   el resultado de la operación idempotente y hacer `commit`.
7. Ante un fallo, hacer `rollback` de toda la operación. El stock insuficiente
   se informa como `409 Conflict`; la respuesta de éxito se entrega después del
   `commit`.

Ejemplo del bloqueo de inventario con SQLAlchemy, dentro de la transacción del
servicio y suponiendo que ya existe el modelo `Recurso`:

```python
from sqlalchemy import select

recursos = session.scalars(
    select(Recurso)
    .where(Recurso.id.in_(ids_recursos))
    .order_by(Recurso.id)
    .with_for_update()
).all()
```

Este fragmento sólo muestra la adquisición de los bloqueos; la validación, las
inserciones y el manejo de la transacción forman parte del servicio completo.
La edición de inventario y la liberación deben bloquear las mismas filas de
recursos, en el mismo orden. Cuando interviene un proyecto, se bloquea antes
que los recursos.

Una transacción que intenta bloquear las mismas filas espera a que termine la
primera. Así se serializan las operaciones sobre ese stock, incluso con varias
réplicas de la API, siempre que todas las escrituras respeten el protocolo.
No realizar llamadas HTTP mientras se mantienen los bloqueos.

Hay dos duraciones diferentes:

- El bloqueo de PostgreSQL dura hasta el `commit` o `rollback` y protege la
  operación frente a escrituras concurrentes.
- El compromiso persistido mantiene las cantidades reservadas mientras la ONG
  trabaja, aunque la transacción que lo creó ya haya terminado.

## Idempotencia y reintentos

Exigir `Idempotency-Key` en las escrituras invocadas por Bonita. Guardar la clave
por emisor/cuenta y operación, junto con una huella del contenido canónico y las
referencias o respuesta mínimas:

- Misma clave y mismo contenido: devolver el resultado anterior sin reservar
  ni liberar de nuevo.
- Misma clave y contenido diferente: devolver `409 Conflict`.
- Solicitudes simultáneas con la misma clave: resolverlas mediante unicidad en
  PostgreSQL, dentro de la transacción.

Un timeout puede ocurrir después de que la API haya confirmado el compromiso.
Bonita debe reintentar con la misma clave o consultar el compromiso. La
aplicación local conserva las referencias, la clave y el estado de
sincronización para reconciliar el resultado; no debe generar otra clave para
repetir una operación cuyo resultado desconoce.

## Liberación, edición de inventario y cierre

Cuando una ONG informa que terminó su actividad, Bonita solicita la liberación
de sus compromisos. La API bloquea el proyecto y los recursos correspondientes,
marca el compromiso como `LIBERADO` y guarda la fecha dentro de una transacción.
Al dejar de contarse como activo, sus cantidades vuelven a estar disponibles.
Se conserva el historial y una liberación repetida no produce otro movimiento.

La liberación afecta únicamente a la ONG que terminó. Los recursos de otras
ONG que siguen trabajando permanecen comprometidos.

Para editar inventario, bloquear primero la fila del recurso, recalcular lo
comprometido y exigir:

```text
nuevo_total >= cantidad_comprometida_activa
```

Para cerrar un proyecto, bloquearlo y comprobar que no queden compromisos
activos. Si todavía existen, devolver `409`. La emergencia local pasa a
resuelta después de confirmar y reconciliar el cierre nacional.

## Organización de la implementación

- `app/api/routes/`: endpoints, dependencias de permisos y traducción de errores.
- `app/schemas/`: solicitudes y respuestas Pydantic, con alias camelCase hacia
  Bonita y cantidades decimales serializadas como strings.
- `app/services/`: reglas de compromiso, liberación, inventario y transacciones.
- `app/db/models/`: modelos SQLAlchemy e importación en `__init__.py`.
- `alembic/versions/`: migraciones revisadas con `upgrade()` y `downgrade()`.

Antes de T32, completar los modelos/migraciones, JWT, inventario y validación
previstos en T22, T24, T25, T27 y T31. Luego implementar T33 y conectar el flujo
con Bonita en T37.

## Verificación necesaria

Probar contra PostgreSQL real, con conexiones y transacciones independientes:

- Dos solicitudes simultáneas reservan 6 ambulancias cada una sobre un total de
  10: sólo una se confirma; la otra recibe conflicto y quedan 4 disponibles.
- Un ítem sin stock revierte toda una solicitud de varios recursos.
- La suma de ítems repetidos del mismo recurso no supera su disponibilidad.
- Los reintentos, incluidos los simultáneos, no duplican compromisos.
- Una clave reutilizada con contenido distinto devuelve `409`.
- Una liberación repetida no modifica nuevamente la disponibilidad.
- Editar el total por debajo de lo comprometido se rechaza, incluso mientras
  otra transacción intenta comprometer recursos.
- Un emisor ajeno no puede operar el proyecto y una ONG no puede modificar
  inventario de otra.
- Habilitaciones vencidas o incompatibles se detectan al comprometer.
- El cierre se rechaza mientras quede una ONG con compromisos activos.

## Referencias

- [Plan de implementación de la Entrega 3](./PLAN_IMPLEMENTACION_ENTREGA_3.md).
- [Reglas de desarrollo de la API nacional](../AGENTS.md).
- [Proceso BPM vigente de RescueSync](../../RescueSync/docs/bonita/proceso-bpm.md).
- [SQLAlchemy: `Select.with_for_update()`](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update).
- [PostgreSQL 16: bloqueos de filas](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS).
