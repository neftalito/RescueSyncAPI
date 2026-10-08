# Inventario nacional de ONGs

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

Cantidades negativas, no finitas, de más de 11 dígitos enteros o 3 decimales son
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

Después de aplicar migraciones:

```bash
docker compose run --rm api python -m app.scripts.seed
```

El seed sólo se permite en `development` o `test`. Agrega dos ONGs pendientes,
sus cuentas, tres capacidades y cuatro recursos. Repetirlo no cambia stock,
contraseñas, habilitaciones ni compromisos existentes. Un login o identificador
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

El recorrido web y los comandos de ambos repositorios se documentan en
`RescueSync/docs/inventario-nacional.md`. Para onboarding fuera del seed,
`POST /ongs` recibe nombre, identificador institucional, email de contacto y
credenciales; el administrador local vincula luego el UUID nacional verificado.

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
