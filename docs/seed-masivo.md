# Seed nacional masivo

El comando `app.scripts.seed_masivo` agrega ONGs habilitadas, cuentas personales y
técnicas, inventario y acreditaciones sintéticas. Es independiente del seed demo.
Usa [Faker](https://faker.readthedocs.io/) en español argentino, como dependencia
de desarrollo. No crea ofertas, proyectos ni compromisos nacionales.

Desde la raíz de RescueSyncAPI, con PostgreSQL iniciado y migraciones al día:

```bash
docker compose build api
docker compose run --rm api python -m app.scripts.seed_masivo --dry-run
docker compose run --rm api python -m app.scripts.seed_masivo
```

Sólo admite `APP_ENV=development` o `test`. Escribe en la base configurada para
la API y no requiere acceso a RescueSync ni Bonita.

## Parámetros

| Opción | Predeterminado | Efecto |
| --- | ---: | --- |
| `--seed` | 2026 | Identidad del conjunto; 0–2.147.483.647 |
| `--ongs` | 1.000 | Objetivo total de ONGs |
| `--recursos-por-ong` | 20 | Objetivo de recursos por ONG; mínimo 4 |
| `--batch-size` | 250 | Tamaño de tandas; 1–1.000 |
| `--dry-run` | desactivado | Muestra el volumen sin conectar a la base |

Por defecto se crean **1.000 ONGs, 2.001 cuentas, 20.000 recursos y 1.000
acreditaciones**, más una certificación de prueba con cuatro alcances. Los
recursos alternan agua, raciones, paramédicos y ambulancias. Reutilizan el catálogo
base y sus unidades canónicas; no modifican capacidades oficiales. Las cantidades
son enteras y positivas, compatibles con recursos discretos.

```bash
docker compose run --rm api python -m app.scripts.seed_masivo \
  --seed 2026 --ongs 2000 --recursos-por-ong 50 --batch-size 100
```

El ejemplo apunta a 100.000 recursos. Tanto las ONGs como los recursos se
procesan por tandas para limitar la memoria. Se confirma una única transacción;
un fallo revierte la ejecución completa y devuelve código 1. El progreso se
imprime antes del commit y el resumen final informa las filas nuevas confirmadas.

## Idempotencia y cuentas

Una repetición con el mismo seed agrega sólo filas faltantes. Aumentar ONGs o
recursos por ONG amplía el conjunto; disminuirlos conserva las filas existentes.
El comando no restaura stock, reactiva ONGs/cuentas, rota contraseñas ni renueva
acreditaciones existentes. Una colisión de identidad aborta sin reemplazarla.
Un advisory lock por seed serializa ejecuciones concurrentes.

Los UUIDs y códigos son deterministas, por lo que la unicidad no depende de los
valores aleatorios de Faker ni del tamaño de las tandas. Faker puede cambiar los
textos entre versiones; las identidades existentes siguen siendo las mismas.

Las cuentas de prueba con seed 2026 son:

| Propósito | Login | Contraseña de fixture |
| --- | --- | --- |
| Administración nacional | `masivo-2026-admin@example.test` | `CargaMasiva2026!` |
| Cuenta personal ONG | `masivo-2026-ong-1@example.test` | `CargaMasiva2026!` |
| Cuenta técnica ONG | `masivo-2026-tecnica-1` | `CargaMasivaTecnica2026!` |

El índice de ONG empieza en 1. Son credenciales públicas de desarrollo y se
guardan como hashes Argon2; los hashes de fixtures se reutilizan durante la carga
para evitar que el costo de miles de cálculos domine la generación de datos.

## Correspondencia con RescueSync

Ejecutar este seed antes del seed masivo local, con **el mismo `--seed` y al
menos tantas ONGs como en RescueSync**. La aplicación local requiere su clave
`NACIONAL_ENCRYPTION_KEY` estable y la integración HTTP nacional configurada.

Cada referencia usa `uuid5(NAMESPACE_URL, "rescuesync-masivo:{seed}:{referencia}")`:

| Referencia | Contenido |
| --- | --- |
| `ong:{i}` | Identidad nacional de la ONG local i |
| `cuenta-tecnica:{i}` | Cuenta usada por el acceso cifrado local |
| `recurso:{i}:{j}` | Recurso j de la ONG i |

Los primeros cuatro recursos de cada ONG coinciden con los aportes de las ofertas
masivas locales. Las capacidades usan los UUIDs del catálogo base instalado por
migraciones. Las cuentas técnicas y sus accesos permiten consultar Mis recursos;
las bases siguen siendo independientes.

Esta carga sirve para medir directorios, inventario, disponibilidad, consultas y
pantallas con muchos registros. No ejecuta una prueba de concurrencia HTTP ni el
flujo BPM. Para descartar el conjunto sin afectar otros datos, usar de antemano
una base o volumen de prueba dedicado; el comando no elimina filas.

Las pruebas de idempotencia, ampliación, colisiones, credenciales y rollback usan
PostgreSQL con las migraciones reales:
`docker compose run --rm -e APP_ENV=test api pytest tests/test_seed_masivo.py`.
