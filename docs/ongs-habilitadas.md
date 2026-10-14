# Consulta de ONGs habilitadas (T29)

`GET /api/v1/ongs/habilitadas` exige JWT de una cuenta vigente ONG,
ADMIN_NACIONAL o INTEGRACION. Devuelve `evaluadoEn` UTC y `ongs`, con identidad,
nombre, estado institucional, capacidades acreditadas y motivos del perfil.
No expone contactos, credenciales administrativas ni inventario individual.

Sólo incluye instituciones HABILITADAS. Sin filtros, una institución sin
competencias vigentes aparece con perfil vacío y `SIN_COMPETENCIAS_VIGENTES`.
La habilitación institucional y el onboarding no acreditan todas las capacidades.

Filtros opcionales: `capacidadId` UUID y `nivelRiesgo` BAJA/MEDIA/ALTA/CRITICA.
Ambos deben coincidir en la misma capacidad; cada institución conserva su perfil
completo. La vigencia usa `[desde, hasta)`, excluye revocadas, revisiones y
capacidades inactivas, y toma el mayor riesgo acreditado por capacidad.
La consulta comparte ese cálculo con T28 en una sola lectura SQL, sin N+1.

```http
GET /api/v1/ongs/habilitadas?nivelRiesgo=ALTA
Authorization: Bearer <JWT_NACIONAL>
```

Sin coincidencias responde 200 con `ongs: []`; filtros inválidos reciben 422.
Cuenta/JWT inválidos reciben 401 y consultantes institucionales deshabilitados
403. Responde `Cache-Control: no-store`. El stock no interviene en el perfil:
esta lectura no acredita disponibilidad futura ni reserva recursos.

No requiere migración. Verificar en PostgreSQL real:

```bash
docker compose run --rm -e APP_ENV=test api pytest tests/test_ongs_habilitadas.py tests/test_certificaciones.py
```

Relacionado con [issue #8](https://github.com/neftalito/RescueSyncAPI/issues/8).
