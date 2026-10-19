# CORS para despliegues y nuevos dominios

Los dominios permitidos se definen en **`CORS_ORIGINS` del `.env` de RescueSyncAPI**.
Es una lista JSON de orígenes web, no una lista de URLs de endpoints. Compose la
transmite a la API. En cloud se configura la misma variable en el servicio, sin
modificar ni reconstruir código para agregar dominios.

## Agregar un consumidor web

1. Editar el `.env`, agregando el origen nuevo y conservando los que sigan activos:

   ```dotenv
   CORS_ORIGINS=["http://localhost:5173","https://app.example.org","https://admin.example.org"]
   ```

   Se permite el **origen del navegador**: protocolo, dominio y puerto si no es
   el predeterminado. La URL de la API desplegada no reemplaza los dominios de
   las apps que la consumen. `https://app.example.org` y
   `https://www.app.example.org` deben agregarse por separado cuando se usen ambos.

2. Recrear el servicio local para aplicar las variables:

   ```bash
   docker compose up -d --no-deps --force-recreate api
   ```

   `docker compose restart api` no carga cambios del `.env` en un contenedor
   existente. En cloud, editar la variable y reiniciar/redeployar el servicio
   para que todas las réplicas reciban la configuración. En el panel del
   proveedor ingresar el JSON directamente, sin agregar comillas que envuelvan
   toda la lista. No se requiere un cambio de imagen para este ajuste.

3. Verificar el preflight de la API usando el origen habilitado:

   ```bash
   curl -i -X OPTIONS http://localhost:8001/api/v1/login \
     -H 'Origin: https://app.example.org' \
     -H 'Access-Control-Request-Method: POST' \
     -H 'Access-Control-Request-Headers: authorization,content-type,idempotency-key'
   ```

   Esperado: 200, `Access-Control-Allow-Origin: https://app.example.org` y
   `Vary: Origin`. Repetir sobre la URL HTTPS de la API desplegada. Un origen
   ajeno responde 400 en el preflight y no recibe permiso CORS.

Se normalizan mayúsculas del host, puerto predeterminado, espacios exteriores y
barra final, eliminando duplicados. Se rechazan rutas (`/api/v1`), query,
fragmentos, credenciales en la URL, protocolos distintos de HTTP/HTTPS y
comodines (`*`, `*.example.org`). Las variables del proceso tienen prioridad
sobre el `.env` leído por Python.

## JWT e integración distribuida

Esta API usa JWT Bearer, sin cookies: el middleware no habilita credenciales de
sesión. El navegador puede enviar `Authorization: Bearer ...` y JSON; las
operaciones idempotentes admiten `Idempotency-Key` en el preflight. No usar
`credentials: "include"` para esta API. La autenticación y los permisos siguen
siendo obligatorios aunque el origen esté permitido.

El frontend de RescueSync accede a su backend local. Las peticiones de ese backend
y de Bonita hacia la API nacional son **servidor a servidor** y no están sujetas
a CORS. Para un despliegue exclusivamente de integración puede usarse:

```dotenv
CORS_ORIGINS=[]
```

Swagger servido por la propia API funciona en el mismo origen. Si se publica
una interfaz web externa que accede directamente a la API nacional, agregar
el origen de esa interfaz. CORS no sustituye JWT, permisos ni controles de red.

## Diagnóstico del despliegue

- **400 en OPTIONS:** comparar `Origin`, método y cabeceras de DevTools con
  los permitidos. HTTP/HTTPS, puerto y cada subdominio cambian el origen.
- **La configuración sigue vieja:** recrear/redeployar; comprobar solo esta
  variable con `docker compose exec api python -c 'from app.core.config import get_settings; print(get_settings().cors_origins)'`.
- **401/403:** revisar JWT, expiración y rol; CORS no corrige autenticación.
- **500 de la aplicación:** el origen permitido recibe CORS también en ese
  error, para que el navegador no oculte el problema real.
- **502/503 generado por el proveedor o proxy:** revisar disponibilidad; estas
  respuestas no atraviesan el middleware de FastAPI.
- **Dos headers Allow-Origin:** evitar duplicar la configuración en el proxy y
  FastAPI. El preflight debe llegar a la API sin exigirle JWT previamente.

El backend local tiene su propia
[configuración CORS y de cookies](../../RescueSync/docs/cors.md).

Referencias: [CORS en FastAPI](https://fastapi.tiangolo.com/tutorial/cors/) y
[CORS sobre respuestas de error en Starlette](https://starlette.dev/middleware/#corsmiddleware-global-enforcement).
