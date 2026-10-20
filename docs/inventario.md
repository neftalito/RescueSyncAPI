# Inventario nacional de ONGs

> Actualización 20/10/2026: [perfiles informativos](./perfiles-competencia.md) reemplaza las
> reglas de certificación, habilitación previa y clasificación por riesgo de este
> documento. Las referencias a esas reglas describen el comportamiento anterior.


RescueSync consume estos servicios a través de su backend local. El inventario
se guarda exclusivamente en PostgreSQL nacional; las ofertas siguen siendo locales.

## Endpoints implementados

Todas las rutas usan `/api/v1`. Los DTO de inventario usan camelCase y cantidades
como strings decimales con tres decimales en las respuestas.

| Método y ruta | Acceso y resultado |
| --- | --- |
| `POST /login` | Credenciales `identificadorLogin` y `password`; responde `access_token`, `token_type` y `expires_in` |
| `GET /me` | Bearer JWT; cuenta, rol vigente y `ongId` |
| `POST /ongs` | Alta pública atómica de cuenta y ONG en estado `PENDIENTE` |
| `GET /capacidades` | Cuenta activa; capacidades activas, unidad y `admiteFracciones` |
| `POST /capacidades` | Sólo `ADMIN_NACIONAL`; crea una capacidad con una unidad existente |
| `GET /unidades` | Cuenta activa; catálogo de unidades predefinidas, de solo lectura |
| `GET /ongs/{id}/recursos` | ONG propia, administración o integración; total, comprometido y disponible |
| `POST /ongs/{id}/recursos` | ONG propia o administración; alta con capacidad y propietario inmutables |
| `PATCH /ongs/{id}/recursos/{recursoId}` | ONG propia o administración; total y versión `actualizadoEn` |

Ejemplo de alta:

```json
{
  "capacidadId": "UUID-del-catalogo",
  "codigoInterno": "AMB-02",
  "nombre": "Ambulancias de rescate",
  "cantidadTotal": "4"
}
```

Para editar, enviar `cantidadTotal` y el `actualizadoEn` recibido en el listado.
La API bloquea el recurso con `FOR UPDATE`, vuelve a sumar los compromisos activos
y rechaza con `409` un total inferior a lo comprometido o una versión obsoleta.
El listado lee inventario y compromisos en un mismo snapshot SQL. Compromiso y
liberación futuros deben bloquear los mismos recursos, en orden de UUID, después
de bloquear el proyecto; ver [bloqueo de recursos](./bloqueo%20de%20recursos.md).
La consulta y la edición de inventario no crean reservas.

El alta y la edición requieren un total estrictamente positivo. Cantidades cero,
negativas, no finitas, de más de 11 dígitos enteros o 3 decimales son
inválidas. Personal y vehículos requieren cantidades enteras. Los códigos internos
son únicos por ONG. La ONG no puede cambiar propietario, capacidad, habilitación
institucional ni certificaciones. Las cuentas suspendidas/de baja y sistemas de
origen inactivos no acceden a rutas protegidas. El rol `INTEGRACION` sólo consulta
inventario; no puede editarlo.

Swagger documenta Bearer y los errores `401`, `403`, `404`, `409` y `422`.
Los errores de validación nunca devuelven contraseñas ni entradas completas.
JWT usa HS256 fijo, `sub`, `iat`, `exp`, issuer y audience. Se recarga la cuenta
desde PostgreSQL en cada operación. No hay refresh tokens ni reintentos de login.
Configurar un `JWT_SECRET` estable para varias réplicas y reinicios; en desarrollo,
una clave vacía es efímera y reiniciar la API exige reconectar las cuentas.

## Seed coordinado con RescueSync

Las 31 unidades y las 56 capacidades de referencia se cargan por migración tanto
en producción como en desarrollo. Los cuatro tipos de recurso se instalan como
enum desde la migración inicial. El seed siguiente sólo agrega el escenario demo;
no es necesario para disponer del catálogo. La administración de capacidades y
sus permisos se detallan en
[Catálogo de capacidades y unidades](./catalogo-capacidades.md).

Después de aplicar migraciones:

```bash
docker compose run --rm api python -m app.scripts.seed
```

El seed sólo se permite en `development` o `test`. Agrega dos ONGs,
sus cuentas personales y técnicas y cuatro recursos, reutilizando las capacidades
`AGUA`, `PARAMEDICOS` y `AMBULANCIAS` del catálogo base. T28 agrega un escenario de
[certificaciones](./certificaciones.md): Ayuda Sin Fronteras habilitada y Red
Médica Solidaria pendiente, con historia de credenciales. Repetirlo no cambia stock,
contraseñas ni compromisos existentes, y no revive suspensiones o revocaciones.
Un login o identificador
demo vinculado a otra identidad produce error y rollback, no una sustitución.

| ONG | Login nacional | Contraseña demo nacional | Recursos iniciales |
| --- | --- | --- | --- |
| Ayuda Sin Fronteras | `ong@rescuesync.org` | `ong-nacional123` | 5000 litros de agua y 12 paramédicos |
| Red Médica Solidaria | `redmedica@rescuesync.org` | `redmedica123` | 4 ambulancias y 20 paramédicos |

Son credenciales públicas exclusivas de desarrollo. Los UUID se generan con
`uuid5(NAMESPACE_URL, "rescuesync-demo:ong:ayuda-sin-fronteras")` y
`uuid5(NAMESPACE_URL, "rescuesync-demo:ong:red-medica-solidaria")`. El seed local
usa exactamente esas referencias para guardar la vinculación explícita; no
busca equivalencias por nombre ni presupone IDs numéricos iguales entre bases.

El seed nacional también crea una cuenta `TECNICA_ONG` por ONG demo. El seed
local guarda su referencia y secreto cifrado; no hace falta ejecutar comandos de
cuentas técnicas ni importar archivos para estas dos instituciones. Los contratos
compartidos de desarrollo son:

- Cuenta: `uuid5(NAMESPACE_URL, "rescuesync-demo:cuenta-tecnica:<referencia>")`.
- Login: `demo-tecnica-<referencia>`.
- Secreto público de demo: `demo-only-rescuesync-tecnica:<referencia>:2026`.

Se usa `ayuda-sin-fronteras` o `red-medica-solidaria` como referencia. No son las
contraseñas personales de los representantes ni credenciales productivas. El seed
no rota ni reactiva una cuenta existente; una identidad técnica incompatible
produce un error y requiere revisar/importar su credencial real.

El recorrido web y los comandos de ambos repositorios se documentan en
`RescueSync/docs/inventario-nacional.md`. Configurar una vez la clave Fernet en el
backend local, ejecutar ambos seeds e iniciar sesión local con `ong123` o
`redmedica123`. Mis recursos utiliza automáticamente la cuenta técnica.
Para ONG nuevas fuera del seed, seguir el
[aprovisionamiento automático](./acceso-automatico-ong.md).

## Trazabilidad T25, T26 y T27

| Tarea | Criterios implementados | Evidencia |
| --- | --- | --- |
| [T25 #4](https://github.com/neftalito/RescueSyncAPI/issues/4) | Login, Argon2, JWT limitado por firma/HS256/issuer/audience, permisos vigentes y secretos de entorno | Pruebas de login, JWT alterado y ONG suspendida/de baja |
| [T26 #5](https://github.com/neftalito/RescueSyncAPI/issues/5) | ONG y cuenta atómicas, estado pendiente, duplicados de login/identificador institucional, sin autoasignación de privilegios | Pruebas de rollback y login de la nueva identidad; adaptador y formulario locales |
| [T27 #6](https://github.com/neftalito/RescueSyncAPI/issues/6) | GET/POST/PATCH, cantidades positivas, unidades, disponibilidad derivada y locking | Pruebas de permisos, compromisos activos/liberados, edición obsoleta y reserva concurrente; pantalla Mis recursos |

Estos cambios se revisan en el [PR nacional #28](https://github.com/neftalito/RescueSyncAPI/pull/28)
y el [PR local #45](https://github.com/neftalito/RescueSync/pull/45). Implementación
en ramas de trabajo no equivale a integración en `develop` ni despliegue.
Las horas efectivas no fueron informadas y no se modifica el Excel.
La lista de validación manual está en `RescueSync/docs/pruebas-manuales-t25-t27.md`.

## Pruebas

```bash
docker compose run --rm -e APP_ENV=test api pytest --cov=app --cov-report=term-missing
```

Las pruebas usan schemas aislados de PostgreSQL real. Cubren firma, expiración,
issuer/audience, algoritmo, roles vigentes, ONG ajena, onboarding atómico, unidades,
stock comprometido, versiones obsoletas, seed repetido y una reserva concurrente
con una edición en conexiones independientes.

Referencias: [PyJWT](https://pyjwt.readthedocs.io/en/latest/api.html) y
[protocolo de locking](./bloqueo%20de%20recursos.md).
