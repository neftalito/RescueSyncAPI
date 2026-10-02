# RescueSync API Nacional

Servicio independiente para el Sistema Nacional de Gestión de Recursos y Riesgos
de RescueSync. Esta base cubre el setup y la dockerización de la Entrega 3 y deja
preparados PostgreSQL, Alembic, OpenAPI y los controles de calidad.

Este corte todavía no implementa autenticación JWT ni endpoints de cuentas,
ONGs, certificaciones, inventario, validación, compromiso o liberación. La API
nacional tampoco almacenará borradores u ofertas preliminares: las ofertas sólo
se recibirán transitoriamente para su futura validación.

Las reglas de desarrollo están en [AGENTS.md](./AGENTS.md). La secuencia completa,
los contratos propuestos y la trazabilidad T22–T42 se describen en el
[plan de implementación de la Entrega 3](./docs/PLAN_IMPLEMENTACION_ENTREGA_3.md).

## Requisitos

- Docker Engine con Docker Compose v2.
- Para ejecutar sin contenedores: Python 3.13 y PostgreSQL 16.

## Inicio rápido

```bash
cp .env.example .env
docker compose up --build
```

La API queda disponible en `http://localhost:8001`:

- Swagger UI: `http://localhost:8001/docs`
- ReDoc: `http://localhost:8001/redoc`
- Liveness: `http://localhost:8001/api/v1/health`
- PostgreSQL readiness: `http://localhost:8001/api/v1/health/database`

El puerto 8001 y PostgreSQL 5433 se publican en el host para no colisionar con la
aplicación local de RescueSync. Dentro de Compose, la API escucha en 8000 y se
conecta a PostgreSQL en 5432.

Los puertos publicados de RescueSync son 8000 (backend), 5432 (PostgreSQL),
5173 (frontend), 8080 (Bonita) y 8025 (Mailpit). Ambos stacks pueden ejecutarse
simultáneamente con sus configuraciones predeterminadas. Repetir puertos internos
es válido porque sus redes Docker son independientes. Para cambiar los puertos
publicados del Sistema Nacional, usar `API_PORT` y `POSTGRES_EXPOSED_PORT`.

Para detener el entorno sin borrar los datos:

```bash
docker compose down
```

## Arquitectura

```text
app/
├── api/routes/    # Adaptadores HTTP pequeños
├── core/          # Configuración y seguridad transversal
├── db/models/     # Modelos SQLAlchemy 2.x
├── schemas/       # Contratos Pydantic de entrada y salida
└── services/      # Casos de uso y reglas de negocio
```

El acceso a PostgreSQL es síncrono. Esta decisión permite mantener transacciones
explícitas y preparar el locking requerido para el compromiso de recursos sin
mezclar sesiones síncronas y asíncronas.

## Configuración

La configuración se toma de variables de entorno. `DATABASE_URL` tiene prioridad
sobre las variables PostgreSQL individuales.

Compose mantiene el puerto interno de la API en 8000; `API_PORT` cambia el puerto
del host. Fuera de Compose, el comando del Dockerfile usa `PORT` directamente.
API y migraciones reciben la misma `DATABASE_URL`, también al usar Compose.

| Variable | Valor de desarrollo | Propósito |
| --- | --- | --- |
| `APP_ENV` | `development` | Entorno: `development`, `test` o `production` |
| `PORT` | `8000` | Puerto interno del proceso HTTP |
| `API_PORT` | `8001` | Puerto publicado por Compose en el host |
| `DATABASE_URL` | vacío | URL entregada por el proveedor cloud |
| `POSTGRES_HOST` | `db` | Host usado sin `DATABASE_URL` |
| `POSTGRES_PORT` | `5432` | Puerto usado sin `DATABASE_URL` |
| `POSTGRES_EXPOSED_PORT` | `5433` | Puerto PostgreSQL publicado por Compose |
| `POSTGRES_DB` | `rescuesync_nacional` | Base nacional |
| `POSTGRES_USER` | `rescuesync_nacional` | Usuario local |
| `POSTGRES_PASSWORD` | sólo desarrollo | Contraseña local; debe ser secreta en cloud |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Lista JSON de orígenes HTTP permitidos |

Las URLs `postgres://` y `postgresql://` se normalizan automáticamente al driver
`postgresql+psycopg://`, por lo que son compatibles con Render, Fly.io y otros
proveedores que entregan `DATABASE_URL`.

## Migraciones

Compose ejecuta `alembic upgrade head` antes de iniciar la API. Todavía no existe
una revisión porque este corte no define tablas de negocio.

Al incorporar el modelo nacional:

```bash
docker compose run --rm api alembic revision --autogenerate -m "crear esquema nacional"
docker compose run --rm api alembic upgrade head
```

Cada revisión debe incluir `upgrade()` y `downgrade()` viables y ser revisada
antes de integrarse.

## Calidad y pruebas

Con las imágenes construidas:

```bash
docker compose run --rm api ruff check .
docker compose run --rm api ruff format --check .
docker compose run --rm api pytest --cov=app --cov-report=term-missing
```

El workflow `quality` ejecuta las mismas verificaciones y aplica las migraciones
contra PostgreSQL 16 real en cada pull request. Las pruebas incluyen una consulta
real de readiness; requieren una base accesible, que Compose inicia como
dependencia al ejecutar los comandos anteriores.

## Imagen de producción

```bash
docker build --target production -t rescuesync-national-api .
docker run --rm -p 9000:9000 \
  -e PORT=9000 \
  -e APP_ENV=production \
  -e DATABASE_URL='postgresql://usuario:clave@host:5432/base' \
  -e 'CORS_ORIGINS=[]' \
  rescuesync-national-api
```

La imagen usa un usuario no privilegiado, escucha en `0.0.0.0` y respeta
`PORT`. No contiene configuración específica de ningún proveedor.

## Despliegue en Render

1. Crear PostgreSQL y un Web Service en la misma región.
2. Conectar este repositorio y seleccionar el runtime Docker.
3. Configurar `APP_ENV=production`, la URL interna como `DATABASE_URL` y los
   secretos futuros, incluido `JWT_SECRET`, desde el panel.
4. Usar `/api/v1/health` como health check.
5. Cuando existan revisiones, ejecutar `alembic upgrade head` como tarea previa
   al despliegue; no ejecutarla en cada réplica al arrancar.

Render define `PORT` automáticamente y ejecuta el `CMD` del Dockerfile.
El comando pre-deploy está disponible para servicios pagos. En el plan gratuito,
aplicar las migraciones como un paso separado contra la base antes de publicar
una versión que dependa del esquema nuevo. Ver la
[documentación de despliegues](https://render.com/docs/deploys).

## Portabilidad a Fly.io

El código y la imagen no requieren cambios. Una migración futura sólo necesita
agregar `fly.toml` con:

- el Dockerfile como fuente de build;
- puerto interno 8000;
- `release_command = "alembic upgrade head"`;
- health check `/api/v1/health`;
- una región primaria, preferentemente `gru` para Sudamérica.

Además de agregar ese archivo, aprovisionar PostgreSQL y configurar `DATABASE_URL`
y los secretos en Fly.io. Estos pasos pertenecen al entorno de despliegue y no
requieren cambios en Python o en el Dockerfile.

## Próximo corte

El siguiente incremento debe definir mediante una migración el modelo de cuentas,
ONGs, certificaciones, recursos, disponibilidad y compromisos. Luego incorporará
`/login` con JWT y la dependencia Bearer para los endpoints protegidos.
