# Guía de desarrollo para RescueSync API Nacional

## Alcance y fuentes de verdad

Estas reglas se aplican a todo `RescueSyncAPI/`, un repositorio independiente de
la aplicación local `RescueSync/`. La prioridad es la Entrega 3: cuentas y JWT,
ONGs, certificaciones, inventario, validación de competencias y
compromiso/liberación nacional de recursos.

Antes de implementar una tarea, consultar:

- `docs/Grooming Entrega 3.xlsx`: tareas T22–T42, estimaciones y semanas sugeridas.
- `docs/PLAN_IMPLEMENTACION_ENTREGA_3.md`: secuencia, contratos propuestos, criterios
  de aceptación y enlaces a issues.
- `../RescueSync/docs/Trabajo integrador 2026.pdf`: requisitos funcionales y
  directivas obligatorias de arquitectura distribuida.
- `../RescueSync/AGENTS.md` y las guías pertinentes del índice
  `../RescueSync/docs/README.md`, cuando haya integración entre repositorios.
- `../RescueSync/docs/bonita/proceso-bpm.md`, `callbacks.md` y
  `despliegue-y-operacion.md`, junto con el único `.bar` vigente, para cambios BPM.

Si el checkout hermano no está disponible, obtener sus documentos del repositorio
`neftalito/RescueSync` antes de cambiar contratos compartidos. No sustituirlos por
suposiciones. Las restricciones del enunciado prevalecen; las decisiones nuevas
del plan deben identificarse como propuestas, no como requisitos de la cátedra.

La referencia a la Entrega 2 en `RescueSync/AGENTS.md` corresponde a ese repositorio;
no limita el desarrollo nacional solicitado aquí. Este archivo tampoco autoriza
modificaciones de la aplicación local fuera de la tarea encomendada.

## Ramas y coordinación

- Comprobar rama y estado con `git branch --show-current` y `git status --short`
  antes de editar. No implementar ni hacer push directo a `main` o `develop`.
- Este repositorio inicialmente tiene `main` como base. Usar `develop` como base
  solo si existe y el equipo la adoptó; no asumir que existe ni crearla por rutina.
- Usar ramas `<tipo>/<descripcion>` o `<tipo>/tNN-<descripcion>`, con tipos
  `feature`, `fix`, `hotfix`, `refactor`, `test`, `docs`, `ci`, `chore` o `release`.
  La descripción usa minúsculas ASCII, números y guiones medios.
- Una rama corresponde a una tarea o corte coherente. La documentación de la
  preparación inicial puede acompañar `feature/setup-api-cloud`.
- Preservar cambios previos. No descartar, mover ni incluir en commits cambios
  ajenos; si hay solapamiento que no puede resolverse, pedir indicaciones.
- El Excel puede estar sin versionar: leerlo no autoriza a modificarlo, agregarlo
  a Git ni inventar horas efectivas. Su actualización se realiza dentro de T42
  con horas informadas y autorización para ese artefacto.
- Integrar mediante pull request y exigir `quality` exitoso. No marcar una tarea
  terminada por disponer de código local o de documentación solamente.
- Los issues T22–T42 se coordinan en `neftalito/RescueSyncAPI`; el cuerpo indica
  dónde implementar. Cambios locales/BPM se integran mediante PR en
  `neftalito/RescueSync`, enlazando el issue del repositorio nacional.

## Invariantes de arquitectura

- Hay tres fuentes de estado separadas: PostgreSQL local para emergencias,
  convocatorias y ofertas/versiones; Bonita para la orquestación y el timer;
  PostgreSQL nacional para identidades, certificaciones, inventario y compromisos.
- La API nacional no persiste borradores, ofertas preliminares ni cuerpos de
  validación. Puede evaluar transitoriamente ofertas consolidadas después del
  cierre y conservar referencias mínimas en compromisos efectivamente adjudicados.
- Bonita inicia la consulta de ofertas al backend local y llama a la validación
  nacional. No reemplazar ese flujo por un scheduler, Celery o un timer del frontend.
- El frontend local consume únicamente su FastAPI. Inventario nacional o datos
  institucionales se consultan/modifican mediante un adaptador del backend local.
- La API nacional no accede a la base local ni a la base interna de Bonita. No
  declarar claves foráneas entre bases ni suponer que sus IDs numéricos coinciden.
- La validación devuelve capacidades, niveles de riesgo y motivos; no se reduce
  a un booleano aprobado/rechazado y no reserva recursos por anticipado.
- Comprometer exige volver a validar disponibilidad y permisos dentro de una
  transacción. Un resultado de validación anterior no garantiza stock actual.
- Los clientes reciben únicamente errores seguros: no SQL, trazas, secretos ni
  respuestas externas sensibles.

## Organización y Python

- El código está directamente bajo `app/`; no crear otro directorio `backend/`.
- `app/api/routes/`: handlers HTTP y traducción de errores; `app/schemas/`:
  contratos Pydantic; `app/services/`: reglas de negocio y transacciones;
  `app/db/`: base, sesiones y modelos; `app/core/`: configuración y seguridad.
- Agregar `app/integrations/` únicamente cuando se necesite una llamada externa;
  encapsular allí clientes con timeouts y ciclo de vida claro. No crear clientes
  HTTP por petición ni poner llamadas HTTPX directamente en rutas.
- Usar Python 3.13, tipos modernos, `collections.abc` y funciones completamente
  tipadas, incluidas dependencias y fixtures. Evitar `Any` y casts que oculten fallos.
- Mantener SQLAlchemy síncrono con `Session`; las rutas que hacen I/O bloqueante
  usan `def`. No mezclar sesiones síncronas y asíncronas.
- Modelos SQLAlchemy 2.x con `Mapped[T]`/`mapped_column()`; Pydantic en límites
  HTTP, enums para estados/roles y `Decimal`/`Numeric` para cantidades.
- Usar timestamps conscientes de zona horaria y almacenar UTC. No usar floats
  para aritmética de disponibilidad ni `datetime.now()` sin zona horaria.
- Capturar excepciones específicas y evitar abstracciones sin dos usos reales.
  Ruff define formato y lint; no desactivar reglas globalmente para un caso local.
- Docstrings en español para responsabilidades o contratos no obvios.

## Contratos HTTP y autenticación nacional

- Las rutas de negocio usan `/api/v1`; el login previsto es
  `POST /api/v1/login`. `/`, `/docs`, `/redoc`, `/openapi.json` y health son
  públicos. Nuevas rutas protegidas declaran autenticación y autorización explícitas.
- Los callbacks locales de Bonita siguen usando `BONITA_CALLBACK_TOKEN` y
  `X-Bonita-Root-Process-Instance-Id`; ese token no es un JWT nacional.
- Para JWT, usar una biblioteca mantenida, algoritmo permitido configurado por el
  servidor y validación de firma, expiración, issuer y audience. No aceptar el
  algoritmo indicado por el cliente sin una allowlist.
- Hash de contraseñas con pwdlib/Argon2. No registrar contraseñas, JWT,
  Authorization ni payloads completos que contengan credenciales/ofertas.
- Separar cuentas ONG, administración nacional y cuentas técnicas de integración.
  Cargar la cuenta/ONG vigente para autorizar; no confiar solo en roles del JWT ni
  permitir que una ONG cambie inventario o compromisos de otra.
- Las ONGs no autoemiten certificaciones ni se habilitan administrativamente a
  sí mismas. El onboarding no equivale a habilitación para todo nivel de riesgo.
- Emitir JWT de duración limitada; reautenticar ante expiración de forma acotada.
  Refresh tokens, sesiones web y federación no forman parte del corte inicial.
- Declarar `response_model`, summary/description y respuestas de error útiles
  en OpenAPI. `401` para autenticación, `403` para autorización, `404` para
  referencias inexistentes, `409` para conflictos y `422` para entradas inválidas.

## PostgreSQL, migraciones y concurrencia

- Cada cambio de esquema tiene revisión Alembic manual con `upgrade()` y
  `downgrade()` viables. No modificar revisiones que otro integrante pudo aplicar.
- Importar todos los modelos desde `app/db/models/__init__.py`, que se importa en
  `alembic/env.py`. Aplicación y Alembic usan la misma configuración de base.
- Usar `NOT NULL`, `CHECK`, `UNIQUE`, índices y claves foráneas para invariantes
  persistentes, además de Pydantic. No usar `create_all()` como migración productiva.
- Cantidades totales y comprometidas no negativas; disponible = total menos
  comprometido. Una actualización de inventario no puede bajar el total por
  debajo de los compromisos activos.
- Bloquear las filas involucradas mediante PostgreSQL en un orden estable.
  Compromisos, liberaciones y edición de stock deben compartir el mismo criterio
  de locking; no usar mutex de Python para garantizar consistencia distribuida.
- Un compromiso compuesto es atómico: si falla un ítem, no reservar los demás.
  Confirmar una operación solo después del commit; rollback ante fallos.
- Escrituras invocadas por conectores son idempotentes: clave única por emisor y
  operación, comprobación del contenido y respuesta reutilizable. Misma clave
  con contenido diferente es conflicto, nunca una operación nueva.
- Un timeout puede ocurrir después del commit. Reintentar con la misma clave o
  consultar el compromiso; nunca generar otra clave para repetir un resultado incierto.
- Liberar una sola vez y conservar historial. Un proyecto termina únicamente
  cuando no quedan compromisos activos; no liberar recursos de ONGs aún trabajando.

## Integración con RescueSync y Bonita

- Conservar mappings explícitos ONG local → ONG nacional y aportes locales →
  recursos/cantidades nacionales. No inferir equivalencias a partir de textos.
- Mantener contratos en camelCase hacia Bonita y tipados/validados a ambos lados.
  La evolución de contratos debe actualizar ejemplos, pruebas y documentación.
- Correlacionar sistema emisor, emergencia, convocatoria, oferta/versiones y caso.
  La API nacional autoriza al emisor autenticado; una cabecera `caseId` no prueba
  por sí sola la identidad ni los permisos de una cuenta nacional.
- Revisar antes de implementar T34/T35: ya existen el GET de ofertas consolidadas
  y su conector en el `.bar` 1.2. Ampliar lo faltante sin duplicar el recorrido.
- Todo cambio BPM requiere versión nueva del pool, un único `.bar` actualizado,
  `BONITA_PROCESS_VERSION`, contratos, parámetros de deploy y pruebas en el mismo
  PR de RescueSync. El proyecto fuente `.bos` actualmente no está versionado.
- Credenciales nacionales se aprovisionan como secretos del entorno de Bonita;
  nunca incorporar valores reales en el `.bar` versionado o en capturas de entrega.
- No mantener locks de PostgreSQL mientras se llama a otro sistema. Registrar el
  estado de sincronización y reconciliar fallos entre bases, sin prometer una
  transacción distribuida inexistente.

## Docker, secretos y portabilidad

- Conservar `python:3.13-slim`, targets `development`/`production`, usuario no root,
  escucha en `0.0.0.0` y `PORT` configurable en la imagen de producción.
- Mantener `DATABASE_URL` portable, incluyendo normalización a Psycopg y opciones
  TLS del proveedor. No acoplar lógica de negocio a Render o Fly.io.
- Compose nacional publica API 8001 y PostgreSQL 5433; RescueSync publica 8000,
  5432, 5173, 8080 y 8025. Los puertos internos 8000/5432 pueden repetirse en redes
  separadas. Comparar configuraciones efectivas si se cambian variables/puertos.
- Migraciones son un paso separado previo al despliegue. No ejecutarlas durante
  el build de imagen ni simultáneamente al arrancar cada réplica.
- Nunca versionar `.env`, secretos, dumps, entornos virtuales, cachés o coberturas.
  `.env.example` contiene únicamente ejemplos de desarrollo.
- Dependencias productivas van en `requirements.txt`; pruebas/calidad en
  `requirements-dev.txt`. Incorporar bibliotecas solo cuando resuelvan una necesidad.
- Desplegar, aprovisionar recursos pagos o cambiar servicios cloud requiere un
  pedido específico para esa operación; disponer de instrucciones no lo autoriza.

## Verificación y definición de terminado

Desde la raíz nacional:

```bash
docker compose config --quiet
docker compose build api migrate
docker compose run --rm api alembic upgrade head
docker compose run --rm api ruff check .
docker compose run --rm api ruff format --check .
docker compose run --rm api pytest --cov=app --cov-report=term-missing
```

Estas pruebas requieren PostgreSQL real; Compose inicia las dependencias. Probar
concurrencia con conexiones/transacciones independientes, no SQLite ni sesiones
compartidas. Aislar los datos y variables de configuración entre pruebas.

Cubrir permisos permitidos/denegados, JWT inválido o expirado, certificaciones
vencidas, validación sin persistencia de ofertas, stock insuficiente, rollback,
doble compromiso, reintentos, liberación repetida y cierre prematuro. Integraciones
HTTP usan dobles/RESPX; Runtime y cloud reales se reservan para E2E controladas.

Una tarea termina cuando cumple su issue y el grooming, incluye migraciones y
tests proporcionales, mantiene contratos compatibles, documenta comandos y
variables nuevos y obtiene `quality` exitoso en su PR. Distinguir siempre código
local verificado, integración en GitHub y despliegue real.
