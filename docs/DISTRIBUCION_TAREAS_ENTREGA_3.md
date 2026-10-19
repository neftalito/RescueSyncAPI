# Distribución de tareas abiertas — Entrega 3

Propuesta para **cinco integrantes**, elaborada el **05/10/2026** a partir de
los issues abiertos de `neftalito/RescueSyncAPI`. La fecha objetivo es la semana
del **22/10/2026**.

## Fuentes y alcance

Se consultaron los issues con GitHub CLI y se seleccionaron únicamente los que
tenían estado `OPEN` al momento del relevamiento:

```bash
gh issue list --repo neftalito/RescueSyncAPI --state open --limit 100 \
  --json number,title,body,state,labels,assignees,url,milestone
```

El reparto comprende **18 issues abiertos, por 92 horas de estimación original**.
Los issues cerrados quedan fuera de la distribución y de sus totales.
Las horas se contrastaron con el [grooming](<./Grooming Entrega 3.xlsx>).
Son estimaciones originales, no horas efectivas ni una nueva estimación del
esfuerzo restante: algunos issues abiertos ya tienen avances parciales.

También se consultaron el [plan de implementación](./PLAN_IMPLEMENTACION_ENTREGA_3.md),
el [enunciado](<../../RescueSync/docs/Trabajo integrador 2026.pdf>), las reglas
de ambos repositorios y las guías locales de
[proceso BPM](../../RescueSync/docs/bonita/proceso-bpm.md),
[callbacks](../../RescueSync/docs/bonita/callbacks.md) y
[operación](../../RescueSync/docs/bonita/despliegue-y-operacion.md).
El estado actual de GitHub prevalece sobre el estado inicial del plan, registrado
el 01/10/2026. Los contratos nuevos del plan siguen siendo propuestas de diseño.

Se usan identificadores **Integrante 1–5** porque no se indicó quién ocupará
cada bloque. Esta es una propuesta de responsabilidades: no modifica los
assignees de GitHub. Actualmente hay 13 issues abiertos sin asignación;
T38–T41 están asignados a `neftalito` y T42 tiene varios assignees.

## Criterio de distribución

- Cada issue abierto tiene un único responsable principal en esta propuesta.
  Las colaboraciones y revisiones no duplican su estimación.
- Se mantienen juntos seguridad/onboarding, certificaciones/validación,
  inventario/locking y los conectores de Bonita para reducir traspasos.
- El promedio es **18,4 h por integrante**; las cargas van de **17 a 20 h**.
- Inventario, compromiso y liberación quedan bajo una misma persona con 19 h;
  el bloque BPM recibe 17 h por su incertidumbre de integración. El equilibrio
  considera dificultad además de horas.
- Cada responsable incluye las pruebas y documentación de sus funcionalidades.
  T40 y T41 consolidan y amplían esa verificación.
- El repositorio de ejecución se toma del cuerpo del issue. Los cambios locales
  o BPM llevan PR en `neftalito/RescueSync`, enlazado al issue nacional.

## Resumen de carga

| Integrante | Bloque principal | Tareas abiertas | Cantidad | Horas originales |
| --- | --- | --- | ---: | ---: |
| 1 | Identidades, seguridad y documentación | T25, T26, T40, T42 | 4 | **17 h** |
| 2 | Certificaciones, consultas y validación | T28, T29, T30, T31 | 4 | **19 h** |
| 3 | Inventario y operaciones transaccionales | T27, T32, T33 | 3 | **19 h** |
| 4 | Orquestación Bonita y flujo operativo local | T35, T36, T37 | 3 | **17 h** |
| 5 | Consolidado local, infraestructura y QA | T38, T34, T39, T41 | 4 | **20 h** |
| **Total** | | **18 issues abiertos** | **18** | **92 h** |

## Integrante 1 — Identidades, seguridad y documentación

| Orden | Issue | Horas | Ejecución | Dependencias abiertas |
| ---: | --- | ---: | --- | --- |
| 1 | [T25 — Endpoint de login con JWT](https://github.com/neftalito/RescueSyncAPI/issues/4) | 5 | RescueSyncAPI | Ninguna |
| 2 | [T26 — Registro / onboarding de ONGs](https://github.com/neftalito/RescueSyncAPI/issues/5) | 5 | RescueSyncAPI | T25 |
| 3 | [T40 — Documentar servicios con Swagger / OpenAPI](https://github.com/neftalito/RescueSyncAPI/issues/19) | 4 | RescueSyncAPI; ejemplos compartidos | T25–T33 |
| 4 | [T42 — Actualizar grooming y preparar material de entrega](https://github.com/neftalito/RescueSyncAPI/issues/21) | 3 | RescueSyncAPI; evidencias de ambos repositorios | T39, T40, T41 |

Entregar primero las dependencias de autenticación y autorización: JWT con
firma, expiración, issuer/audience y algoritmo permitido; Argon2 y carga de
cuenta/ONG vigente. Probar autenticación inválida, permisos denegados y onboarding
atómico sin escalamiento de roles ni autoacreditación.

En T40, consolidar contratos, ejemplos, errores y exportación de OpenAPI con los
responsables funcionales. En T42, reunir URLs, evidencias, PRs y horas efectivas
informadas por los cinco integrantes. La edición del Excel requiere autorización
para ese artefacto; no inventar horas ni versionarlo automáticamente.

## Integrante 2 — Certificaciones, consultas y validación

| Orden | Issue | Horas | Ejecución | Dependencias abiertas |
| ---: | --- | ---: | --- | --- |
| 1 | [T28 — Consulta de certificaciones](https://github.com/neftalito/RescueSyncAPI/issues/7) | 4 | RescueSyncAPI | T25 |
| 2 | [T29 — Consulta de ONGs habilitadas](https://github.com/neftalito/RescueSyncAPI/issues/8) | 4 | RescueSyncAPI | T26, T28 |
| 3 | [T30 — Disponibilidad global de recursos](https://github.com/neftalito/RescueSyncAPI/issues/9) | 5 | RescueSyncAPI | T27 |
| 4 | [T31 — Validación por niveles de competencia](https://github.com/neftalito/RescueSyncAPI/issues/11) | 6 | RescueSyncAPI | T28, T29, T30, T34 |

Mantener coherentes catálogo, vigencia, habilitación institucional y perfiles
de competencia. Incluir la carga administrativa de certificaciones y seed de
desarrollo prevista en T28. Consolidar disponibilidad por capacidad y unidad,
sin sumar recursos incompatibles.

T31 evalúa el snapshot transitoriamente y devuelve capacidades, niveles de
riesgo, disponibilidad consultada y motivos por aporte. No persiste ofertas ni
reserva stock. Probar certificaciones vencidas, referencias faltantes,
consorcios y apoyo compatible. Compartir sus reglas con el integrante 3 para
que el compromiso revalide la habilitación vigente.

## Integrante 3 — Inventario y operaciones transaccionales

| Orden | Issue | Horas | Ejecución | Dependencias abiertas |
| ---: | --- | ---: | --- | --- |
| 1 | [T27 — Inventario y disponibilidad](https://github.com/neftalito/RescueSyncAPI/issues/6) | 6 | RescueSyncAPI + adaptador/UI en RescueSync | T26 |
| 2 | [T32 — Compromiso transaccional de recursos](https://github.com/neftalito/RescueSyncAPI/issues/12) | 8 | RescueSyncAPI | T27, T31 |
| 3 | [T33 — Liberación de recursos y cierre](https://github.com/neftalito/RescueSyncAPI/issues/13) | 5 | RescueSyncAPI | T32 |

Ser responsable del criterio común de locking PostgreSQL para editar stock,
comprometer y liberar. Usar cantidades decimales y locks en orden estable;
impedir bajar el total por debajo de compromisos activos. T27 incluye el
adaptador y la consulta/edición local del inventario: el frontend consume
únicamente FastAPI local.

T32 debe ser atómico e idempotente, revalidar permisos y stock dentro de la
transacción y permitir consultar el resultado de un compromiso. T33 libera una
sola vez por ONG/compromiso, conserva historial y rechaza cierre con compromisos
activos. Probar concurrencia con conexiones independientes, rollback multiítem,
clave repetida con distinto contenido y liberación reiterada.

## Integrante 4 — Orquestación Bonita y flujo operativo local

| Orden | Issue | Horas | Ejecución | Dependencias abiertas |
| ---: | --- | ---: | --- | --- |
| 1 | [T35 — Conector Bonita para consultar ofertas](https://github.com/neftalito/RescueSyncAPI/issues/14) | 5 | RescueSync BPM | T34 |
| 2 | [T36 — Conector Bonita hacia validación externa](https://github.com/neftalito/RescueSyncAPI/issues/15) | 6 | RescueSync BPM + backend | T25, T31, T35 |
| 3 | [T37 — Integrar compromiso y liberación](https://github.com/neftalito/RescueSyncAPI/issues/16) | 6 | RescueSync BPM + backend/frontend | T32, T33, T36 |

Mantener el timer y la iniciativa de consulta en Bonita. T35 revisa y adapta el
conector existente en el `.bar` 1.2. T36 realiza login nacional, validación y
callback local de perfiles correlacionados por caso, convocatoria y versión.
La reautenticación debe ser acotada y los caminos de reapertura, reformulación
y continuidad parcial deben conservarse.

T37 incluye selección municipal, cantidades adjudicadas, notificaciones después
del compromiso confirmado, finalización por ONG, seguimiento/cierre del
coordinador y callback `/resolver`. Registrar estado de sincronización y
reconciliar timeouts reutilizando la misma clave; no mantener locks durante HTTP.

Confirmar al inicio la disponibilidad del proceso editable y Bonita Studio:
el `.bos` no está versionado. Todo cambio BPM requiere nueva versión del pool,
un único `.bar`, `BONITA_PROCESS_VERSION`, contratos, parámetros y pruebas en el
mismo PR local. Las credenciales se inyectan como secretos del entorno.

## Integrante 5 — Consolidado local, infraestructura y QA

| Orden | Issue | Horas | Ejecución | Dependencias abiertas |
| ---: | --- | ---: | --- | --- |
| 1 | [T38 — Dockerfile de producción](https://github.com/neftalito/RescueSyncAPI/issues/17) | 3 | RescueSyncAPI | Ninguna |
| 2 | [T34 — Ofertas consolidadas para Bonita](https://github.com/neftalito/RescueSyncAPI/issues/10) | 4 | RescueSync backend | T26, T27 |
| 3 | [T39 — Desplegar API y base de datos en cloud](https://github.com/neftalito/RescueSyncAPI/issues/18) | 5 | RescueSyncAPI + configuración Runtime Bonita | T25, T33, T38 |
| 4 | [T41 — Pruebas de concurrencia y extremo a extremo](https://github.com/neftalito/RescueSyncAPI/issues/20) | 8 | Ambos repositorios + Runtime aislado | T36, T37, T39 |

T38 verifica e integra los avances existentes de Docker: Python 3.13, usuario
no root, targets separados y `PORT` configurable. T34 amplía el GET existente,
con mappings explícitos ONG/recurso nacional y cantidades por participante;
conserva camelCase, autenticación técnica y correlación del caso raíz. Excluir
borradores, retiradas y resultados de rondas anteriores.

T39 prepara y ejecuta el despliegue cuando exista el pedido específico requerido
por las reglas del repositorio; este reparto no autoriza aprovisionamiento ni
gastos. Aplicar migraciones como paso separado y verificar HTTPS, health,
OpenAPI y acceso desde Bonita. Coordinar los parámetros BPM con el integrante 4.

T41 completa la matriz transversal: JWT/permisos, perfiles, disputa de stock,
idempotencia concurrente, rollback, timeout incierto, doble liberación y cierre
prematuro. Ejecutar la E2E timer → consolidado → validación → selección →
compromiso → finalización → liberación → cierre, con evidencia de emergencia
`RESUELTA` y disponibilidad recuperada. La suite habitual usa dobles HTTP;
la E2E real utiliza un entorno controlado.

## Secuencia y coordinación

La semana sugerida del grooming orienta el orden; las dependencias determinan
cuándo puede integrarse cada tarea. Este calendario es una propuesta, sujeta a
la disponibilidad real del equipo y al esfuerzo adicional detectado.

| Integrante | 5–9 de octubre | 12–16 de octubre | 19–22 de octubre |
| --- | --- | --- | --- |
| 1 | T25 → T26 | Revisar aplicación de permisos y preparar ejemplos T40 | Completar T40 → T42 |
| 2 | T28 → T29 | T30 → T31 | Verificar perfiles en E2E y aportar evidencias |
| 3 | Preparar contrato de inventario y locking | T27 → T32 → T33, según disponibilidad de T31 | Resolver hallazgos transaccionales de T41 |
| 4 | Obtener modelo editable y acordar contratos | T35 después de T34; preparar T36/T37 con dobles | T36 → T37 y prueba del nuevo BPM |
| 5 | T38 y preparar matriz QA | T34 después de T26/T27; preparar T41 | T39 → completar T41 |

Preparar contratos, fixtures, dobles HTTP y casos de prueba permite avanzar
antes de integrar las dependencias. Ese avance no habilita cerrar el issue
sin verificar el recorrido real y sus criterios de aceptación.

| Entrega que habilita trabajo | Responsable | Consumidores y acuerdo |
| --- | --- | --- |
| JWT, permisos y onboarding | 1 — T25/T26 | 2, 3, 4 y 5: publicar dependencias y matriz de roles temprano. Cada dueño prueba permisos en sus rutas. |
| Inventario y mappings | 3 — T27 | 2 — T30 y 5 — T34: acordar IDs, unidades, cantidades y stock comprometido. |
| Snapshot consolidado | 5 — T34 | 2 — T31 y 4 — T35: fijar DTO camelCase y ejemplos de versiones/consorcios antes de integrar consumidores. |
| Perfiles y habilitación | 2 — T31 | 3 — T32 y 4 — T36: compartir reglas de riesgo, vigencia y motivos. La validación previa no garantiza stock. |
| Compromiso/liberación | 3 — T32/T33 | 4 — T37 y 5 — T39/T41: acordar idempotencia, consulta tras timeout y cierre sin activos. |
| Flujo BPM/local completo | 4 — T36/T37 | 5 — T41: probar también reabrir convocatoria y reconciliar errores. |
| Evidencias de todos los bloques | Los cinco | 1 — T40/T42: aportar contratos, PRs, checks, URLs y horas informadas desde cada tarea. |

## Riesgos y acuerdos de ejecución

T27 y T37 incluyen backend/frontend local además de la API o BPM. El plan
identifica ese alcance sin estimación separada; las horas originales pueden
subestimar el trabajo. La obtención o reconstrucción del modelo editable también
agrega incertidumbre. Registrar desvíos y reequilibrar tareas explícitamente;
no asumir que esos trabajos caben en las estimaciones iniciales.

El integrante 1 apoya la revisión de permisos locales, el 2 revisa los perfiles
usados en adjudicación, el 3 revisa reconciliación y stock, y el 5 apoya las
pruebas de contratos BPM. El integrante 4 mantiene la responsabilidad de T37.
Cada uno registra su tiempo real en el issue donde colaboró, sin sumar otra vez
las horas nominales del reparto.

Cada issue se implementa en su propia rama desde `develop` actualizado y se
integra mediante PR en el repositorio correspondiente. Revisiones principales:
**1 → 2 → 3 → 4 → 5 → 1**, con revisión adicional de seguridad o locking cuando
corresponda. Coordinar migraciones para no modificar revisiones ya aplicadas.

Una tarea se considera terminada al cumplir su issue, incluir migraciones y
pruebas proporcionales, mantener contratos/documentación y obtener `quality`
exitoso en su PR. Distinguir código local verificado, integración en GitHub y
despliegue real al registrar evidencias.
