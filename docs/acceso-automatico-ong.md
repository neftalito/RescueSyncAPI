# Cuentas técnicas por ONG

Cada ONG puede tener una cuenta `TECNICA_ONG`, con rol `ONG`, además de sus
cuentas personales. Su secreto aleatorio se guarda como hash Argon2. No cambia
el estado institucional ni las certificaciones. Una ONG `PENDIENTE` puede usar
las consultas y operaciones de inventario que ya permitía la API; `SUSPENDIDA`
y `BAJA` no pueden operar.

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
