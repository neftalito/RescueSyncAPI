# Validación transitoria de competencias (T31)

Relacionado con [issue #11](https://github.com/neftalito/RescueSyncAPI/issues/11).

`POST /api/v1/validaciones` recibe directamente el JSON `contratoVersion: 2`
del GET consolidado de T34. Requiere JWT de INTEGRACION de la instalación
indicada por `sistemaOrigen`, o ADMIN_NACIONAL que seleccione un emisor activo.
El token de callbacks locales de Bonita no es un JWT nacional. Una cuenta ONG
no está autorizada para esta operación.

El emisor declara una ronda cerrada, correlacionada con `idEmergencia`, `caseId`,
`convocatoriaId` y `numero`. Bonita debe obtenerla después del timer/cierre local.
La API nacional no accede a las bases de RescueSync o Bonita para verificarla.
La [fixture del contrato](../tests/fixtures/snapshot_t34.json) contiene un ejemplo
completo con identificadores de prueba, que deben reemplazarse por mappings reales.

## Resultado por aporte

La respuesta conserva la correlación y devuelve `evaluadoEn`, `aportes` y
`recursosConsultados`. Cada aporte identifica oferta/version, ítem, lote,
participante y recurso; incluye `capacidadesHabilitadas`,
`nivelesRiesgoPermitidos`, `clasificacion`, `cantidadDisponibleConsultada` y
`motivos` con códigos estables. No es una aprobación binaria.

| Perfil | Significado |
| --- | --- |
| PRINCIPAL | Competencia vigente para capacidad/riesgo del lote y gravedad general. |
| APOYO | Competencia suficiente para el lote, con alcance menor que la gravedad general. |
| SIN_HABILITACION | No se demuestra habilitación para ese aporte/lote; conserva perfiles y motivos. |

En una emergencia CRITICA, una ONG certificada hasta ALTA puede cubrir un lote
MEDIA como APOYO; un lote CRITICA recibe `RIESGO_NO_PERMITIDO`. No se rebaja el
riesgo publicado. Las credenciales de la líder no habilitan a sus miembros.

Competencia y stock son dimensiones distintas: disponibilidad insuficiente
conserva la clasificación y agrega `DISPONIBILIDAD_INSUFICIENTE`. Los errores de
propiedad, capacidad, unidad o fracciones impiden computar el aporte. Referencias
no resolubles devuelven disponibilidad null; cero indica un recurso sin stock libre.

Las cantidades nacionales se leen desde los campos exactos de T34 y se devuelven
como strings con tres decimales. Los números legacy y flags de cobertura o
referencias completas no demuestran competencia, stock ni propiedad.
Estructuras contradictorias reciben `422`. Ofertas históricas sin desglose
generan un resultado por ítem con aporte/recurso null y
`DESGLOSE_NACIONAL_AUSENTE`. Una ronda sin ofertas devuelve listas vacías.
Falta de emisor/cierre no cumple el contrato; faltas por lote/participante se
explican en perfiles. Riesgo o gravedad desconocidos no habilitan adjudicar.

## Consistencia y disponibilidad

Autenticación y evaluación usan una única transacción PostgreSQL REPEATABLE
READ / READ ONLY. Se cargan perfiles y recursos en bloque con un mismo reloj
UTC. Vigencia `[desde,hasta)`, catálogo e institución deben estar habilitados.
No se escriben ofertas, resultados, operaciones, proyectos o reservas.

`recursosConsultados` muestra cada recurso existente una sola vez, su stock y
demanda total del snapshot. Su disponibilidad repetida en distintos aportes es
un mismo presupuesto. El resultado no realiza una asignación global: T36 debe
evitar sumar stock duplicado; T32 revalidará la selección concreta bajo locks.
Presentar y validar una oferta no compromete stock ni garantiza disponibilidad futura.

Respuestas `Cache-Control: no-store`. `401`: JWT inválido/cuenta inactiva;
`403`: rol/emisor denegado; `404`: emisor administrativo inexistente; `422`:
contrato inválido; `503`: fallo temporal de base. No se devuelven SQL, JWT o
cuerpos de ofertas en errores. T35/T36 implementarán los conectores y la
persistencia local de perfiles; T31 no cambia el `.bar`, esquema o configuración.

## Verificación

```bash
docker compose run --rm --no-deps -e APP_ENV=test api pytest tests/test_validaciones.py
docker compose run --rm --no-deps api ruff check .
docker compose run --rm --no-deps api ruff format --check .
```

Las pruebas usan schemas PostgreSQL aislados y cubren participantes, referencias
legacy, riesgos y vigencia, stock y no persistencia, contratos/permisos y una
escritura confirmada desde otra conexión durante la lectura.
