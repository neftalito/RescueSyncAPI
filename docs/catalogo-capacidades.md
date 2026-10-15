# Capacidades y unidades nacionales

El catálogo de capacidades puede ampliarse mediante una cuenta `ADMIN_NACIONAL`
activa. Las unidades son datos de referencia instalados por migración; ninguna
cuenta de la API puede crearlas, editarlas ni eliminarlas.

## Endpoints

Todas las rutas usan `/api/v1` y requieren JWT nacional vigente.

| Método y ruta | Permiso | Resultado |
| --- | --- | --- |
| `GET /unidades` | Cuenta activa | Unidades predefinidas: `codigo`, `nombre`. |
| `GET /capacidades` | Cuenta activa | Capacidades activas y sus unidades canónicas. |
| `POST /capacidades` | `ADMIN_NACIONAL` | Crea una capacidad activa con unidad existente. |

Ejemplo de alta:

```json
{
  "codigo": "ALIMENTOS",
  "nombre": "Alimentos no perecederos",
  "tipo": "SUMINISTRO",
  "unidad": "kg",
  "admiteFracciones": true
}
```

El código es único, de hasta 80 caracteres: comienza con una letra mayúscula y
continúa con mayúsculas, números o guion bajo. El nombre admite hasta 160
caracteres. Los tipos son `PERSONAL`, `VEHICULO`, `EQUIPAMIENTO` y `SUMINISTRO`.
Personal y vehículos requieren cantidades enteras. `unidad` es el código exacto
devuelto por `GET /unidades`, no un objeto que permita crear otra unidad.

Respuestas: `201` con el mismo DTO de capacidad que usa el listado, `401` sin
cuenta vigente, `403` para ONG/integración, `409` por código duplicado y `422`
por datos o unidad inválidos. El código único se exige en PostgreSQL incluso
ante altas concurrentes. Crear una capacidad no acredita ONGs ni crea stock.

## Unidades instaladas en desarrollo y producción

La revisión `20261014_0002` carga 31 unidades sin depender de `APP_ENV` ni del
seed de demostración:

| Uso | Códigos disponibles |
| --- | --- |
| Conteo y agrupación | `unidades`, `personas`, `vehículos`, `equipos`, `kits`, `pares`, `juegos` |
| Presentación de suministros | `paquetes`, `cajas`, `bolsas`, `bidones`, `botellas`, `raciones`, `dosis` |
| Alojamiento | `camas`, `plazas` |
| Volumen | `litros`, `mililitros`, `metros cúbicos` |
| Masa | `kg`, `gramos`, `toneladas` |
| Longitud y superficie | `metros`, `kilómetros`, `metros cuadrados`, `hectáreas` |
| Tiempo y servicios | `horas`, `días`, `viajes`, `servicios`, `turnos` |

La migración conserva como referencias adicionales las unidades históricas ya
usadas por capacidades existentes, sin convertir cantidades ni alterar su
semántica. Una FK impide insertar capacidades con unidades ajenas al catálogo.
El downgrade elimina el catálogo y la FK, conservando capacidades y sus textos.
Ampliar unidades en el futuro requiere otra migración revisada, no una pantalla
administrativa ni un endpoint de escritura.

Aplicar antes de ejecutar la API actualizada:

```bash
docker compose build api migrate
docker compose run --rm migrate
```

Los datos de referencia se cargan también al migrar una instalación de producción
vacía; ejecutar `app.scripts.seed` sigue siendo opcional y exclusivo de desarrollo.

## Administración desde RescueSync

El administrador local accede desde **Catálogo nacional → Gestionar capacidades**.
El navegador llama únicamente al backend de RescueSync, que exige sesión local
de administrador y CSRF para el alta. El servidor usa `NACIONAL_CATALOGO_LOGIN`
y `NACIONAL_CATALOGO_PASSWORD` y verifica el rol nacional vigente. Para crear,
esa cuenta debe ser `ADMIN_NACIONAL`; `INTEGRACION` sólo puede consultar.
Las contraseñas y JWT nacionales no se envían al navegador.

El formulario permite elegir exclusivamente unidades devueltas por el catálogo,
normaliza el código a mayúsculas y actualiza los listados de capacidades tras
crear. Las nuevas capacidades quedan disponibles para lotes y recursos de ONG.
