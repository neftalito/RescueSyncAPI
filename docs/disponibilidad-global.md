# Disponibilidad global de recursos (T30)

`GET /api/v1/recursos/disponibilidad` exige JWT vigente de ONG, administración o
integración y devuelve `consultadoEn` UTC y `recursos`. Cada grupo identifica
capacidad y unidad, con total, comprometida, disponible y desglose resumido por
ONG. No existe un total que mezcle capacidades o unidades distintas.

Se incluyen recursos y capacidades activos de ONGs HABILITADAS, aun sin
certificaciones. El resultado describe stock institucional; la competencia para
una capacidad/riesgo se evalúa por separado. Recurso agotado permanece con cero.

La cantidad comprometida suma sólo ítems de compromisos ACTIVO. LIBERADO aporta
cero, sin eliminar historia. `disponible = total - comprometida`. La consulta
preagrega por recurso y construye totales/desglose desde una sola sentencia SQL,
sin multiplicación por joins ni locks de escritura. No reserva stock.

Filtros opcionales `capacidadId` y `ongId` (UUID), combinados por intersección.
Sin coincidencias responde 200 con `recursos: []`; formatos inválidos 422.
JWT/cuentas inválidos reciben 401 y instituciones/emisores consultantes
deshabilitados 403. Cantidades son strings con tres decimales, incluso cero y
sumas superiores al límite individual Numeric(14,3). No expone inventario
interno, contactos ni referencias de proyectos de otras instituciones.

Responde `Cache-Control: no-store`. El siguiente GET refleja operaciones
confirmadas de inventario, compromiso/liberación. El compromiso definitivo
requiere revalidar disponibilidad en su propia transacción (T32).

No requiere migración. Verificación en PostgreSQL real:

```bash
docker compose run --rm -e APP_ENV=test api pytest tests/test_disponibilidad.py tests/test_inventario.py
```

Las fixtures de compromisos reproducen transacciones válidas; no representan
endpoints T32/T33 implementados. Relacionado con [issue #9](https://github.com/neftalito/RescueSyncAPI/issues/9).
