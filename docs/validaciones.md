# Evaluación de consistencia y perfiles informativos

`POST /api/v1/validaciones` requiere JWT de INTEGRACION del emisor autenticado o
ADMIN_NACIONAL. Recibe el snapshot cerrado contrato 2; no admite cuentas ONG.
Conserva correlación de sistema, emergencia, caso, ronda, oferta/versiones,
participantes, ítems, lotes y aportes. Estructuras contradictorias dan 422.

Devuelve contrato 3, perfiles de inventario por ONG, stock consultado y motivos
de consistencia. No clasifica PRINCIPAL/APOYO ni evalúa acreditaciones o permisos
por riesgo. Las referencias nacionales, la pertenencia de recursos, el estado
operativo, capacidad, unidad y cantidades siguen verificándose. Sin desglose
nacional devuelve un diagnóstico por ítem; no inventa asociaciones históricas.

Autenticación y evaluación comparten REPEATABLE READ / READ ONLY. No se persisten
ofertas ni resultados ni se reserva stock. `recursosConsultados` identifica cada
recurso una sola vez con su demanda agregada. La cobertura local evita reutilizar
esa disponibilidad y el compromiso revalida la selección bajo locks.

La falta de stock informa `DISPONIBILIDAD_INSUFICIENTE`; se permite seleccionar
una cantidad parcial dentro del stock disponible. Las respuestas llevan
`Cache-Control: no-store`; los fallos técnicos no confirman ninguna reserva.

Ver [perfiles y actualización coordinada](./perfiles-competencia.md),
[fixture del snapshot](../tests/fixtures/snapshot_t34.json) y
[OpenAPI publicado](./generated/openapi.json).
