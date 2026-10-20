# Preparación de la base para Yaak

`POST /api/v1/mantenimiento/seed-yaak` elimina todos los datos nacionales y deja
únicamente un escenario determinista para probar los endpoints. El vaciado y la
carga se realizan en una sola transacción PostgreSQL. Un fallo durante la carga
o el commit revierte también el vaciado. Conserva el esquema y `alembic_version`;
no necesita una migración nueva.

Este endpoint funciona también con `APP_ENV=production`. Requiere
`DB_MAINTENANCE_PASSWORD` configurada y la cabecera
`X-DB-Maintenance-Password`. No requiere JWT: el mantenimiento continúa
funcionando después de borrar las cuentas. Ejecutarlo sin tráfico de negocio ni
pruebas de otro usuario en curso. Sólo afecta la base nacional de esta API.

## Petición

En Yaak, enviar `Content-Type: application/json`, la cabecera de mantenimiento
y este body, sustituyendo la contraseña de ejemplo por la integración del destino:

```json
{
  "confirmacion": "BORRAR_Y_PREPARAR_YAAK",
  "runId": "YAAK2026",
  "integracion": {
    "identificadorLogin": "integracion-rescuesync",
    "password": "demo-integracion-yaak-2026-123456",
    "sistemaOrigen": "rescuesync-local"
  }
}
```

| Campo | Regla |
| --- | --- |
| `confirmacion` | Literal obligatorio `BORRAR_Y_PREPARAR_YAAK`. |
| `runId` | Entre 1 y 32 caracteres, patrón `^[A-Z0-9][A-Z0-9_-]*$`. |
| `integracion.identificadorLogin` | De 1 a 320 caracteres útiles; se normaliza a minúsculas. No puede coincidir con los siete logins de prueba. |
| `integracion.password` | Entre 12 y 128 caracteres. Se guarda como hash Argon2 y nunca se devuelve. |
| `integracion.sistemaOrigen` | Código útil de 1 a 80 caracteres para el emisor nacional. |

Todos los campos son obligatorios; se rechazan campos adicionales. La validación
del body y de los logins ocurre antes del vaciado. Usar las mismas credenciales de
integración que utiliza RescueSync y que tiene el bootstrap del entorno; así un
reinicio posterior puede validar la cuenta. La integración se recrea durante el
seed y permite iniciar sesión inmediatamente, sin reiniciar FastAPI.

## Respuesta y referencias

Devuelve **HTTP 200**, `operacion: seed-yaak` y
`mensaje: Base nacional reiniciada y escenario Yaak preparado.`. Incluye el
`runId`, `sistemaOrigen`, los `identificadoresLogin` y estos conteos exactos:

| Campo | Valor |
| --- | ---: |
| `unidades` | 31 |
| `capacidades` | 57 |
| `ongs` | 5 |
| `cuentas` | 8 |
| `recursos` | 7 |
| `proyectos` | 0 |
| `compromisos` | 0 |

El objeto `referencias` devuelve los UUID de las cuentas admin e integración,
las cinco ONGs, las capacidades personal/agua/inactiva y los siete recursos.
Los clientes deben tomar esos IDs de la respuesta para construir las consultas,
snapshots y compromisos. El ejemplo completo de respuesta está publicado en
`/docs` y en el [OpenAPI exportado](./generated/openapi.json).

Los UUID del escenario son UUIDv5 derivados de `runId` y una referencia estable;
el catálogo base conserva sus UUID originales. Este seed no usa Faker: nombres,
logins y cantidades son fijos. Fechas y hashes se generan durante la ejecución.
Los conteos describen el estado inmediatamente después del seed; las pruebas
posteriores crean datos adicionales mediante los endpoints.

## Cuentas e inventario

Las siete cuentas de demostración usan
`demo-only-yaak-pruebas-2026-clave-123456`. La octava cuenta, INTEGRACION, utiliza
exclusivamente el login y la contraseña enviados en el body.

| Login | Estado y propósito |
| --- | --- |
| `admin.yaak@example.org` | ADMIN_NACIONAL activo. |
| `ong-a.yaak@example.org` | ONG A habilitada. |
| `ong-b.yaak@example.org` | ONG B habilitada. |
| `tecnica.yaak@example.org` | Cuenta técnica ONG, habilitada, JWT de 300 segundos; ONG sin recursos. |
| `suspendida.yaak@example.org` | Cuenta activa en ONG suspendida: login `200`, rutas protegidas `403`. |
| `baja.yaak@example.org` | Cuenta activa en ONG de baja: login `200`, rutas protegidas `403`. |
| `inactiva.yaak@example.org` | Cuenta inactiva de A: login `401`. |

| ONG | Código de recurso | Cantidad y condición |
| --- | --- | --- |
| A | `BASE-PERSONAL-A` | 14 personas activas. |
| A | `BASE-AGUA-A` | 10.125 litros activos. |
| A | `BASE-INACTIVO` | 2 personas; recurso inactivo. |
| A | `BASE-CAPACIDAD-INACTIVA` | 4 equipos; capacidad `YAAK_INACTIVA` desactivada. |
| B | `BASE-PERSONAL-B` | 10 personas activas. |
| Suspendida | `BASE-SUSPENDIDA` | 5 personas, excluidas de disponibilidad por el estado de la ONG. |
| Baja | `BASE-BAJA` | 5 personas, excluidas de disponibilidad por el estado de la ONG. |

## Errores, repetición y verificación

Contraseña de mantenimiento ausente o incorrecta: `401`. Mantenimiento
deshabilitado: `403`. Body ausente, confirmación incorrecta o campos inválidos:
`422`. Fallo de PostgreSQL: `503` con mensaje seguro, sin detalles SQL.

Comparte el advisory lock de mantenimiento con los demás seeds y flush. El
vaciado toma locks exclusivos; los límites de espera utilizan
`OPERACION_LOCK_TIMEOUT_MS` y `OPERACION_STATEMENT_TIMEOUT_MS`.

Cada llamada vuelve a vaciar la base, incluso si conserva `runId`. Usar un
`runId` nuevo por recorrido y volver a ejecutar los logins y consultas de Yaak
después de cada reset. Ante timeout, comprobar el estado antes de repetir:
la conexión podría interrumpirse después del commit.

La colección y su guía paso a paso están en
`../RescueSyncAPI_Proyecto_YAAK/`, desde la raíz del checkout. Importar
`RescueSyncAPI.yaak.json`, ejecutar explícitamente **C009** y seguir
`GUIA_PRUEBAS.md`. Las referencias al reset usan `behavior='never'`, para que una
consulta dependiente no dispare otro vaciado. La guía incluye los bodies,
respuestas esperadas y los 318 casos para las 24 operaciones.

Las pruebas PostgreSQL de `tests/test_seed_yaak.py` verifican autorización,
validación previa al vaciado, contenido exacto, logins, repetición, rollback
después del TRUNCATE y del commit fallido, y exclusión entre conexiones. La
colección se comprueba por HTTP contra el Compose descartable del proyecto Yaak.
No utiliza ni vacía las bases locales habituales de RescueSync/Bonita.

El endpoint necesita que se publique esta versión de la API en el destino;
aplicar sólo las migraciones no incorpora una ruta HTTP nueva. En Render,
despertar el servicio mediante `/api/v1/health` y esperar su `200` antes de
comenzar: el plan gratuito se suspende tras 15 minutos de inactividad, según la
[documentación de Render](https://render.com/docs/free#spinning-down-on-idle).
