# Perfiles informativos y alta automática

Cambio solicitado el 20/10/2026: las ONG no se certifican ni necesitan aprobación
institucional para ofertar. Esto sustituye las exigencias de certificación del
enunciado original, que se conserva sin modificaciones. JWT, roles, suspensión,
baja, inventario y bloqueo concurrente siguen vigentes.

## Consulta y directorio

- `GET /api/v1/ongs`: instituciones activas, incluso sin inventario; admite
  `capacidadId`, sin filtro por nivel de riesgo.
- `GET /api/v1/ongs/{id}/perfil-competencia`: ONG propia, administración o
  integración. Devuelve `ongId`, `nombre`, `estadoOng`, `evaluadoEn` y
  `capacidadesDeclaradas`. Cada capacidad contiene identificación, tipo, unidad,
  granularidad y cantidades totales, comprometidas y disponibles.

Se agrupan recursos activos con capacidades activas; una capacidad con todo su
stock comprometido sigue en el perfil con disponible cero. Las cantidades son
strings decimales exactos. No se deducen experiencia, permisos ni riesgos permitidos.
La consulta utiliza un snapshot de sólo lectura y no reserva recursos.

Se retiraron `/certificaciones`, `/ongs/{id}/certificaciones`,
`/ongs/habilitadas` y el CLI de acreditaciones/habilitación. Las tablas históricas
se conservan con sus restricciones y no alimentan servicios operativos. Los seeds
ya no crean acreditaciones ni aprobaciones administrativas ficticias.

## Evaluación y compromiso

`POST /validaciones` sigue recibiendo el snapshot local contrato 2 y devuelve
contrato 3. Cada aporte conserva sus referencias y cantidades; incluye
`perfilCompetencia`, `cantidadDisponibleConsultada` y `motivos` técnicos. Se
eliminan `clasificacion`, `capacidadesHabilitadas` y `nivelesRiesgoPermitidos`.

El perfil es descriptivo. La identidad institucional y el inventario se verifican
por separado: existencia, estado operativo, pertenencia, capacidad, unidad,
fracciones y cantidad disponible. El riesgo del lote conserva su valor como
contexto y no habilita ni restringe a ninguna ONG. El municipio elige los aportes.
Disponibilidad insuficiente se informa sin ocultar el aporte: puede adjudicarse
una cantidad parcial que quepa en el stock consultado.

Comprometer vuelve a verificar identidad e inventario bajo locks ordenados de ONG,
capacidad y recurso, sin consultar perfiles ni acreditaciones. Se mantienen
idempotencia, rollback atómico multi-ONG, liberación y cierre.

## Actualización coordinada

1. Aplicar `alembic upgrade head`: `20261020_0006` habilita ONG pendientes y
   establece el alta automática. No modifica suspendidas, bajas ni autores
   históricos. No ejecutar migraciones al construir imágenes.
2. Actualizar API nacional y consumidor local juntos, pausando nuevas evaluaciones
   durante el cambio de contrato. El snapshot y los callbacks de Bonita conservan
   rutas y correlaciones; el proceso transporta el JSON sin interpretar el perfil.
3. Resultados locales contrato 2 permanecen consultables, sin habilitar nuevas
   adjudicaciones. Para casos pendientes con esos resultados, preparar una nueva
   evaluación con otro UUID mediante la integración de Bonita; no sobreescribir
   el resultado anterior ni repetir compromisos confirmados.

`downgrade` conserva filas: las altas automáticas sin autor histórico vuelven a
PENDIENTE. Las aprobaciones administrativas antiguas permanecen intactas.
No se necesita ninguna variable de entorno nueva.

## Verificación del 20/10/2026

288 pruebas nacionales, incluidas migración ida/vuelta, alta sin certificados,
compromiso/liberación y concurrencia con PostgreSQL real.

La E2E completa con Runtime no se ejecutó: Bonita 1.5 estaba habilitado, pero
la API nacional no estaba sirviendo HTTP en la URL configurada para el proceso.
Las pruebas con PostgreSQL y las comprobaciones del BAR no sustituyen esa E2E.
