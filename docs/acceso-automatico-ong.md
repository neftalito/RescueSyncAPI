# Cuentas técnicas por ONG

Cada ONG puede tener una cuenta `TECNICA_ONG`, con rol `ONG`, además de sus
cuentas personales. Su secreto aleatorio se guarda como hash Argon2. No cambia
el estado institucional ni las certificaciones. Una ONG `PENDIENTE` puede usar
las consultas y operaciones de inventario que ya permitía la API; `SUSPENDIDA`
y `BAJA` no pueden operar.

## Alta automática desde RescueSync

Las ONG nuevas creadas en el frontend local se aprovisionan mediante
`PUT /api/v1/integraciones/ongs/{referenciaLocal}`. Requiere JWT de una cuenta
`INTEGRACION` y un sistema de origen activo. No permite reclamar una ONG anterior
ni adjuntar un UUID nacional elegido por el navegador.

El backend local genera un secreto aleatorio de al menos 32 caracteres y conserva
su versión cifrada antes del primer envío. El request contiene `nombre`,
`password` y `emailContacto` opcional (omitido o `null` para no informar correo).
La API genera el identificador institucional
`rs:<UUID del emisor sin guiones>:<referencia sin guiones>`. El navegador no elige
ese identificador ni conoce la contraseña técnica.

La respuesta `200` contiene `ong: {id, nombre, estado}`, `cuentaId` e
`identificadorLogin`, con `Cache-Control: no-store` y sin secretos. Institución,
cuenta `TECNICA_ONG` y correlación se crean en una misma transacción. El alta
`PENDIENTE` permite inventario propio; la habilitación y las certificaciones
requieren su revisión habitual.

La clave durable es `(sistemaOrigen autenticado, referenciaLocal UUID)`. Se
serializan solicitudes del mismo emisor mediante PostgreSQL. Mismos datos y
secreto devuelven la misma identidad; contenido distinto produce `409`. Un
reintento no rota claves, no reactiva cuentas ni revierte suspensiones. Otro
emisor recibe su propia identidad. Se guarda una huella del request, nunca el
secreto en texto plano ni ofertas.

### Preparación única del emisor

Aplicar `alembic upgrade head`. Con acceso al entorno nacional:

```bash
python -m app.scripts.bootstrap_integracion --login alta-rescuesync --sistema-origen rescuesync-local
```

El comando solicita una contraseña (mínimo 12 caracteres), crea la cuenta y el
emisor si faltaba y nunca sustituye identidades ni reactiva emisores. Si ya existe
una cuenta `INTEGRACION` de ese emisor, puede utilizarse sin crear otra. Configurar
su login/contraseña en `NACIONAL_APROVISIONAMIENTO_LOGIN` y
`NACIONAL_APROVISIONAMIENTO_PASSWORD` del backend local, junto con su clave
Fernet estable. Estos secretos se configuran una vez por instalación.

Desplegar la API y su migración antes del cambio de RescueSync. No ejecutar
bootstrap ni importar archivos por cada ONG nueva. El onboarding público
`POST /ongs` conserva su contrato de cuentas personales para otros consumidores.

La migración permite `ong.email_contacto = NULL` y añade `aprovisionamiento_ong`.
Su downgrade elimina la correlación y reemplaza contactos ausentes por
`no-informado+<UUID>@example.invalid` para satisfacer el esquema anterior sin
eliminar instituciones. Ese dominio es un marcador de ausencia. Un rollback
requiere conservar las referencias/secretos en el emisor para reconciliar las
altas; no reaprovisionar a ciegas después de descartar la correlación nacional.

## Aprovisionamiento administrativo

Aplicar primero `alembic upgrade head`. Con una cuenta `ADMIN_NACIONAL` activa,
ejecutar dentro del contenedor nacional:

```bash
python -m app.scripts.cuentas_tecnicas --login admin@example.org crear --ong UUID_ONG --salida /tmp/credencial-ong.json
```

El comando pide la contraseña administrativa por terminal. Genera un secreto de
32 bytes, crea un archivo JSON privado (`0600`) y nunca imprime la credencial.
La ruta debe ser nueva; no se sobrescriben archivos existentes. Transferir el
archivo por un canal seguro al operador del backend local. No versionarlo ni
colocarlo en capturas, correos o logs. Eliminar las copias tras importarlo.

Para reemplazar un secreto, usar `rotar` con una ruta de salida nueva y volver a
importar en RescueSync. Para retirar el acceso:

```bash
python -m app.scripts.cuentas_tecnicas --login admin@example.org revocar --ong UUID_ONG
```

Crear dos veces se rechaza. Rotar conserva la cuenta, aumenta su versión y puede
reactivar una cuenta revocada. Rotar y revocar invalidan inmediatamente todos los
JWT técnicos anteriores. Las cuentas personales no se modifican. El acceso de
otras ONG permanece independiente. Si se pierde el archivo, rotar; no se puede
recuperar el secreto desde su hash.

## Contratos y compatibilidad

- `POST /api/v1/login` conserva `identificadorLogin` y `password` y devuelve
  `access_token`, `token_type=bearer`, `expires_in`. Para cuentas técnicas, la
  duración es 300 segundos, sin refresh token.
- `GET /api/v1/me` agrega `proposito` (`PERSONAL` o `TECNICA_ONG`).
- Los JWT técnicos incluyen `ver`; cada petición comprueba su versión contra la
  cuenta actual, además de firma, issuer, audience, expiración y estado vigente.
- Los permisos son los del rol ONG sobre su propio inventario. Estas cuentas no
  tienen los permisos del rol `INTEGRACION` usado por Bonita.

La migración agrega propósito y versión sin cambiar cuentas existentes. Un
downgrade desactiva las cuentas técnicas antes de quitar esos campos, para no
convertirlas en cuentas personales activas. El rollback requiere volver a
aprovisionar el acceso automático después de un nuevo upgrade.

Desplegar este soporte antes del backend local. Las pruebas usan PostgreSQL
aislado, cubren rotación/revocación y verifican el archivo de exportación.


## Escenario de desarrollo con seeds

El seed nacional crea también las cuentas `TECNICA_ONG` demo; el seed local
prepara sus accesos cifrados con la misma referencia. Ejecutar los dos seeds con
las migraciones aplicadas y `NACIONAL_ENCRYPTION_KEY` configurada en RescueSync.
No se requieren archivos de importación ni la cuenta emisora de aprovisionamiento
para estas dos ONG. Ver [el escenario de inventario](./inventario.md).
Repetir los seeds conserva contraseñas rotadas, revocaciones y accesos importados.
