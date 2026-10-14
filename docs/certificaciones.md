# Certificaciones nacionales — T28

La API consulta el catálogo y las acreditaciones verificadas de cada ONG.
Calcula capacidades y niveles permitidos en UTC, conserva las credenciales
vencidas/revocadas como historia y no reserva inventario. El frontend de
RescueSync consulta estos servicios a través de su backend local.

## Consultas implementadas

Todas las rutas requieren Bearer JWT nacional y usan `/api/v1`.

| Ruta | Resultado y permisos |
| --- | --- |
| `GET /certificaciones` | Lista de revisiones activas y sus alcances. ONG activa (también pendiente), administración o integración con emisor activo. |
| `GET /certificaciones?capacidadId={uuid}&nivelRiesgo=ALTA` | Revisiones con un alcance activo que cumpla ambos filtros, conservando todos sus alcances. |
| `GET /certificaciones?incluirInactivas=true` | Incluye revisiones inactivas; sólo administración nacional. |
| `GET /ongs/{uuid}/certificaciones` | Estado institucional, historia, motivos, capacidades habilitadas y fecha de evaluación. ONG propia, administración o integración. |

Los contratos usan camelCase. Cada revisión incluye `id`, `codigo`, `revision`,
`nombre`, `activa` y `alcances`: capacidad UUID/código/nombre, tipo, unidad,
fraccionabilidad, estado y `riesgoMaximo`. El catálogo no acredita a la cuenta
que lo consulta. Se conservan todas las revisiones activas, no sólo la última.

El perfil devuelve `ongId`, `estadoOng`, `evaluadoEn`, `acreditaciones`,
`capacidadesHabilitadas` y `motivosInstitucionales`. Cada acreditación incluye
la revisión completa, emisor, número, fechas, estado persistido, estado temporal,
revocación y motivos `{codigo, mensaje, capacidadId}`. Cada capacidad habilitada
incluye riesgo máximo, niveles permitidos e IDs de acreditaciones que la sustentan.

Una ONG inexistente produce `404` para lectores autorizados. Una ONG intentando
consultar otra obtiene `403` antes de buscarla. Sin JWT válido o cuenta vigente:
`401`. ONG suspendida/de baja o emisor inactivo: `403`. UUID/enum inválido:
`422` seguro. Sin coincidencias, el catálogo devuelve `[]`; una ONG sin
credenciales devuelve listas vacías. Las respuestas llevan `no-store`.

## Vigencia y competencia

El intervalo es `[vigenteDesde, vigenteHasta)`: justo al inicio está vigente;
justo al fin está vencida. La revocación tiene prioridad. `FUTURA`, `VIGENTE`,
`VENCIDA` y `REVOCADA` son estados calculados para consulta, sin cron ni cambios
del enum persistido `OTORGADA`/`REVOCADA`.

Una capacidad efectiva requiere ONG `HABILITADA`, credencial otorgada dentro
de vigencia, revisión activa y capacidad activa. Una capacidad inactiva no
invalida los otros alcances activos de la misma credencial. Entre acreditaciones
efectivas de la misma capacidad se toma el riesgo máximo según
`BAJA < MEDIA < ALTA < CRITICA`, con referencias verificables y motivos para
las exclusiones. Una credencial vencida de riesgo alto no eleva el permiso de
una vigente de riesgo bajo.

El servicio `consultar_certificaciones_ong` carga institución, historia y
alcances en una consulta SQL y acepta una hora explícita para pruebas. No
persiste perfiles ni ofertas nacionales. T29/T31 pueden reutilizarlo; T32 debe
revalidar bajo sus propios locks, con hora actual obtenida después de esperar.

## Carga administrativa

Los comandos requieren acceso al entorno nacional y una cuenta
`ADMIN_NACIONAL` activa. No hay rutas para que una ONG se autoacredite.
Administración local y nacional son identidades independientes.

Para aprovisionar una cuenta administrativa faltante:

```bash
docker compose run --rm api python -m app.scripts.bootstrap_admin --login admin@example.org
```

Pide y confirma una contraseña de al menos 12 caracteres, genera Argon2 y
rechaza cualquier login existente: no eleva roles ni reemplaza contraseñas.
En producción, ejecutar sólo como operador autorizado con acceso al entorno;
no usar la cuenta demo. El bootstrap no crea cuentas técnicas de Bonita.

Después preparar archivos JSON y ejecutar:

```bash
docker compose run --rm api python -m app.scripts.certificaciones --login admin@example.org publicar --archivo /app/catalogo.json
docker compose run --rm api python -m app.scripts.certificaciones --login admin@example.org otorgar --archivo /app/acreditacion.json
docker compose run --rm api python -m app.scripts.certificaciones --login admin@example.org revocar --archivo /app/revocacion.json
docker compose run --rm api python -m app.scripts.certificaciones --login admin@example.org habilitar-ong --archivo /app/habilitacion.json
```

Todos piden contraseña por terminal; no aceptan `--password`. Los archivos
pueden montarse en modo lectura. No versionar archivos con datos institucionales
reales ni secretos. Estos ejemplos de UUID deben reemplazarse por los obtenidos
de `/capacidades`, onboarding y publicación.

Publicación:

```json
{
  "codigo": "RESPUESTA_SANITARIA",
  "revision": 1,
  "nombre": "Respuesta sanitaria",
  "alcances": [
    {"capacidadId": "00000000-0000-4000-8000-000000000001", "riesgoMaximo": "ALTA"}
  ]
}
```

Otorgamiento:

```json
{
  "ongId": "00000000-0000-4000-8000-000000000002",
  "certificacionId": "00000000-0000-4000-8000-000000000003",
  "emisor": "Autoridad acreditadora",
  "numeroCredencial": "OFICIAL-2026-001",
  "vigenteDesde": "2026-10-01T00:00:00Z",
  "vigenteHasta": "2027-10-01T00:00:00Z"
}
```

Revocación: `ongId`, `acreditacionId`, `motivo`. Habilitación: únicamente
`ongId`; habilita una ONG pendiente, sin otorgar certificaciones y sin reactivar
una suspensión/baja. Autor, fecha y estado se obtienen del servidor. Rechazar
campos extra, alcances vacíos/repetidos, fechas sin zona/invertidas o referencias
inexistentes. Una vigencia histórica/futura válida puede registrarse, pero no
concede competencia actual.

Renovar usa `otorgar` con una nueva referencia oficial: no modifica la credencial
anterior. La unicidad vigente es `(ong, emisor, numeroCredencial)`; si el emisor
reutiliza números, acordar una representación de la renovación y el eventual
cambio de esquema antes de cargarla.

Misma revisión/contenido o credencial/contenido devuelve su ID, también con
cargas concurrentes. Contenido diferente produce conflicto seguro. Repetir una
revocación con el mismo motivo conserva fecha y autor; con otro motivo se rechaza.
Una credencial revocada no se reactiva al repetir `otorgar`.

Los servicios hacen `flush` y dejan el commit al caller. El CLI autentica,
despacha y confirma en una sola sesión; informa éxito sólo después de commit y
revierte al salir ante errores. Usa cuenta vigente bajo lock compartido, ONG
exclusiva, capacidades ordenadas y revisión; la revocación bloquea ONG,
revisión y credencial. Los triggers siguen siendo la segunda defensa. No se
modificó el esquema ni la migración inicial.

## Escenario de desarrollo

```bash
docker compose run --rm api python -m app.scripts.seed
```

El seed funciona sólo en `development`/`test` y preserva UUID, fechas,
contraseñas, stock e historia al repetirlo. Sus cuentas y credenciales son
públicas exclusivamente para desarrollo:

| Identidad | Datos del escenario |
| --- | --- |
| Administración demo | `admin.nacional.demo@rescuesync.org` / `admin-nacional-demo123` |
| Ayuda Sin Fronteras | ONG habilitada; sanitaria vigente (paramédicos `ALTA`, ambulancias `MEDIA`), sanitaria crítica vencida, logística futura y sanitaria revocada. |
| Red Médica Solidaria | ONG pendiente con credencial sanitaria vigente; no tiene capacidades efectivas hasta verificación institucional. |

Las fechas se fijan en la primera carga respecto de la hora de ejecución; no
se desplazan al repetir el seed ni se reviven revocaciones. Los dos mappings de
ONG siguen coincidiendo con el seed de RescueSync. Los recursos demo se
mantienen. El seed rechaza colisiones de identidad o alcance, no las reemplaza.

## Integración y condiciones para merge

El consumidor local necesita el PR de RescueSync con los dos GET de `/mi-ong`
y la sección **Mis certificaciones**. Aplicar primero la versión nacional,
después la local. Para este corte no hay migraciones nuevas ni cambio del BPM.

Antes de mergear: `quality` exitoso en ambos PRs, revisión del contrato camelCase,
cuenta/ONG verificada para datos reales y prueba consulta nacional → adaptador →
pantalla. Los PRs se mantienen abiertos y no se cierra T28 automáticamente.

Para incorporar competencia al proceso automático siguen pendientes:

- **T29/T30/T31:** perfiles de ONGs/disponibilidad y `POST /validaciones`,
  reutilizando estas reglas sin persistir ofertas en la API nacional.
- **T34:** capacidad/riesgo en el snapshot de lotes y aportes por recurso/ONG,
  con mappings/versiones y cantidades nacionales decimales exactas.
- **T36:** fuente `.bos`, versión nueva de Bonita, login JWT técnico, conector de
  validación y callback local de perfiles correlacionado/idempotente; cambiar la
  compuerta de cantidad bruta a cobertura compatible.
- **T32/T37:** revalidar vigencia/estado y disponibilidad antes del compromiso,
  sin asumir que esta consulta reservó recursos.

Esos cambios tienen su propia aceptación y PRs. No declarar la integración BPM
completa al mergear estos dos PRs. El detalle de diseño distribuido está en
[IMPLEMENTACION_T28_CERTIFICACIONES.md](./IMPLEMENTACION_T28_CERTIFICACIONES.md).

## Verificación

En Docker con Python 3.13 y PostgreSQL real pasaron las 116 pruebas nacionales,
Ruff y el control de formato. Las nuevas pruebas incluyen límites de fechas,
permisos, perfil por capacidad, referencias inválidas, seed, carga oficial,
historial y publicación/otorgamiento concurrentes con sesiones independientes.
No se ejecutó ni se afirma una integración automática con Bonita en este corte.
