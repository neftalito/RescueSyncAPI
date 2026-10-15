# Capacidades y unidades nacionales

El catálogo de capacidades puede ampliarse mediante una cuenta `ADMIN_NACIONAL`
activa. Las unidades son datos de referencia instalados por migración; ninguna
cuenta de la API puede crearlas, editarlas ni eliminarlas.

## Catálogo base en desarrollo y producción

`alembic upgrade head` instala **56 capacidades** mediante la revisión
`20261015_0005`, además de las 31 unidades existentes. Los cuatro tipos de recurso
son valores del enum `tipo_recurso`, instalado por la migración inicial; no
requieren un seed separado. Estos datos de referencia se cargan en todos los
entornos, sin cuentas, ONGs, inventario ni certificaciones demo.

| Tipo | Cantidad | Necesidades contempladas |
| --- | --- | --- |
| `PERSONAL` | 12 | Paramédicos, médicos, enfermería, bomberos, rescate urbano, acuático y en altura, psicología, veterinaria, logística, comunicaciones y voluntariado de apoyo general. |
| `VEHICULO` | 9 | Ambulancias, camionetas 4x4, camiones de carga y cisterna de agua, minibuses, lanchas, botes sin motor, excavadoras y autobombas. |
| `EQUIPAMIENTO` | 18 | Generadores, motobombas, potabilizadores, tanques de agua, radios, teléfonos satelitales, iluminación, camillas, desfibriladores, botiquines, carpas, catres, colchones, baños portátiles, cocinas de campaña, rescate hidráulico, cuerdas y chalecos salvavidas. |
| `SUMINISTRO` | 17 | Agua, alimentos no perecederos, raciones, mantas, abrigos, calzado, kits de higiene y limpieza, pañales de adultos e infantiles, barbijos, guantes, alcohol, desinfectante, diésel, nafta y bolsas de arena. |

Cada capacidad define una unidad canónica. El personal se cuenta en `personas`
y los vehículos en `vehículos`, siempre enteros. Agua, alcohol, desinfectante y
combustibles se miden en `litros`; alimentos no perecederos en `kg`; cuerdas en
`metros`. Esas cantidades admiten fracciones. El resto se cuenta sin fracciones
en `equipos`, `unidades`, `kits`, `pares`, `raciones` o `bolsas`, según el caso.
El detalle completo está en `GET /capacidades` y en el snapshot de la migración.

La migración sólo agrega códigos faltantes. Si una instalación ya tiene `AGUA`,
`PARAMEDICOS`, `AMBULANCIAS` u otro código del catálogo, conserva su UUID, nombre,
tipo, unidad, fraccionamiento y estado activo/inactivo. No convierte stock ni
reactiva capacidades. Las capacidades nuevas reciben UUID deterministas; los
consumidores deben seguir consultando sus IDs en el catálogo de cada entorno.
El downgrade conserva los datos porque pueden tener stock, acreditaciones o
referencias en RescueSync. Volver a aplicar la revisión no los duplica.

El seed `app.scripts.seed` reutiliza este catálogo para el escenario de
demostración y sigue restringido a `development` y `test`. Dar de alta una
capacidad, sea por migración o por administración, no habilita automáticamente
a ninguna ONG ni agrega stock o alcances de certificaciones existentes.

## Casos no contemplados y opción «Otro»

No se incluye una capacidad genérica `OTRO`: la disponibilidad se agrupa por
capacidad y la competencia se valida por su identificador. Dos recursos
registrados como `OTRO` compartirían ese significado aunque sus nombres o
descripciones fueran diferentes. Una certificación de `OTRO` también abarcaría
ambos casos y una única unidad no podría expresar necesidades incompatibles.
Incluso separar «Otro personal» y «Otro equipamiento» conservaría la ambigüedad
dentro de cada grupo.

Para un caso nuevo, la administración crea una capacidad específica con tipo,
unidad y fraccionamiento definidos; después se incorpora al inventario y se
acredita a las ONGs que corresponda. El formulario de RescueSync ya permite
esa alta desde **Catálogo nacional → Gestionar capacidades**. Una futura opción
«Otro / solicitar capacidad» debería iniciar ese circuito y resolver la
capacidad concreta antes de usarla en lotes, validaciones o compromisos.

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
  "codigo": "ALIMENTOS_SIN_GLUTEN",
  "nombre": "Alimentos sin gluten",
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
vacía; ejecutar `app.scripts.seed` sigue siendo opcional y exclusivo de desarrollo
y pruebas.

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
