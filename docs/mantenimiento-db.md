# Seeds y flush por HTTP

Configurar `DB_MAINTENANCE_PASSWORD` en el `.env` de RescueSyncAPI. Usar una
contraseña aleatoria de al menos 32 caracteres, independiente de `JWT_SECRET` y
de las cuentas de la base. Para generarla:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

El `.env` es privado y no se versiona; `.env.example` declara la variable vacía.
Sin valor, los tres endpoints devuelven `403` y no ejecutan mantenimiento.
En Compose, después de cambiarla, recrear la API:

```bash
docker compose up -d --no-deps --force-recreate api
```

En un servicio desplegado, configurar la misma variable como secreto del entorno
y reiniciar el proceso. Los endpoints están disponibles también con
`APP_ENV=production` cuando se configura esta contraseña. Faker forma parte de
la imagen de producción para permitir el seed masivo. Los comandos CLI conservan
su restricción a desarrollo/pruebas.

## Autenticación

Enviar `X-DB-Maintenance-Password` con el valor configurado. En `/docs`, usar
**Authorize → DBMaintenancePassword**. No necesitan login ni JWT: la contraseña
continúa funcionando después de borrar todas las cuentas. Un JWT por sí solo
no autoriza estas operaciones. Contraseña ausente o incorrecta devuelve `401`.
La comparación es en tiempo constante; la API no registra ni devuelve el secreto.
Usar HTTPS fuera de localhost y no poner la contraseña en parámetros de URL.

En los ejemplos, `DB_MAINTENANCE_PASSWORD` contiene el secreto del entorno de
destino y `API_URL` su origen, por ejemplo `http://localhost:8001`.

## Operaciones

| Método y ruta | Efecto |
| --- | --- |
| `POST /api/v1/mantenimiento/seed` | Escenario normal: dos ONGs, cuatro cuentas ONG, cuatro recursos y el administrador demo. Sin cuerpo. |
| `POST /api/v1/mantenimiento/seed-masivo` | Escenario masivo configurable. Cuerpo opcional; omitirlo usa los valores de la tabla siguiente. Devuelve conteos de filas nuevas. |
| `POST /api/v1/mantenimiento/flush` | Elimina todas las filas de las tablas de aplicación. Sin cuerpo. |

```bash
curl --fail-with-body -X POST "$API_URL/api/v1/mantenimiento/seed" \
  -H "X-DB-Maintenance-Password: $DB_MAINTENANCE_PASSWORD"

curl --fail-with-body -X POST "$API_URL/api/v1/mantenimiento/seed-masivo" \
  -H "X-DB-Maintenance-Password: $DB_MAINTENANCE_PASSWORD" \
  -H 'Content-Type: application/json' \
  -d '{"seed":2026,"ongs":1000,"recursosPorOng":20,"batchSize":250}'
```

| Campo del seed masivo | Predeterminado | Rango |
| --- | ---: | --- |
| `seed` | 2026 | 0–2.147.483.647 |
| `ongs` | 1000 | 1–10.000 |
| `recursosPorOng` | 20 | 4–1.000 |
| `batchSize` | 250 | 1–1.000 |

Se admiten hasta 200.000 recursos por petición (`ongs × recursosPorOng`).
Todos los campos requieren enteros; valores inválidos y campos desconocidos
devuelven `422`. Ejemplo de respuesta de una carga nueva:

```json
{"operacion":"seed-masivo","mensaje":"Seed masivo confirmado.","ongs":1000,"cuentas":2001,"recursos":20000}
```

Ambos seeds restauran unidades y capacidades base faltantes, sin reemplazar
referencias existentes. Se pueden ejecutar después de un flush sin volver a
aplicar migraciones. Repetir un seed agrega sólo faltantes; no restablece stock,
contraseñas ni cuentas desactivadas. Las credenciales demo y los UUID siguen los
contratos de [inventario](./inventario.md) y [seed masivo](./seed-masivo.md).
Las colisiones de identidad o catálogos incompatibles devuelven `409` y revierten
la carga completa.

## Alcance del flush

El siguiente comando borra todas las cuentas (incluido INTEGRACION y el admin),
ONGs, mappings de aprovisionamiento, inventario, proyectos, compromisos,
operaciones idempotentes, historial de acreditaciones y catálogos nacionales.
Conserva las tablas, restricciones y `alembic_version`; no repuebla datos.

```bash
curl --fail-with-body -X POST "$API_URL/api/v1/mantenimiento/flush" \
  -H "X-DB-Maintenance-Password: $DB_MAINTENANCE_PASSWORD"
```

Sólo afecta la base nacional configurada para la API. No accede a RescueSync ni
a Bonita; sus mappings pueden requerir reconciliación después del vaciado.
Un seed posterior recupera el catálogo y las cuentas de su escenario. La cuenta
INTEGRACION debe volver a aprovisionarse con el procedimiento de bootstrap
existente; los seeds no la recrean.

Las tres operaciones son sincrónicas y se confirman en una sola transacción.
Un advisory lock PostgreSQL las serializa entre instancias HTTP. El flush toma
locks exclusivos sobre las tablas: ejecutarlo sin tráfico de negocio.
Los comandos CLI no participan del lock HTTP de mantenimiento; no ejecutarlos
simultáneamente con un flush.

Un error de base devuelve `503` con detalle seguro y rollback si la transacción
no se confirmó. `OPERACION_LOCK_TIMEOUT_MS` y `OPERACION_STATEMENT_TIMEOUT_MS`
limitan esperas y sentencias; no limitan el tiempo total de una carga por tandas.
Ante timeout o resultado incierto, comprobar el estado antes de repetir un flush:
la conexión puede interrumpirse después del commit. Se puede repetir un seed
con la misma configuración para completar faltantes.
