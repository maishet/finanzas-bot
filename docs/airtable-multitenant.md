# Arquitectura Airtable Multi-Tenant

Esta guia aplica a `develop`. `main` todavia conserva la estructura operativa sin separacion por tenant, por lo que antes de pasar `develop` a `main` hay que preparar Airtable.

## Objetivo

El bot usa una sola base de Airtable compartida para todos los usuarios. La separacion de datos se hace con `TenantID` en cada tabla financiera.

Reglas principales:

- Cada usuario autorizado tiene un `TenantID`.
- Todas las lecturas y escrituras financieras deben filtrar por `TenantID`.
- Los usuarios nuevos se crean desde Telegram con `/admin_add_user`.
- Las cuentas, deudas y categorias del usuario se configuran desde Telegram con `/configurar`.
- Gmail y voz quedan apagados para usuarios nuevos: `GmailEnabled=No` y `VoiceEnabled=No`.
- El admin puede mantener Gmail/voz para su usuario principal si las variables globales estan habilitadas.

## Diferencia Contra `main`

`main` opera como bot personal monousuario. Las tablas financieras no dependen de `TenantID`.

`develop` agrega:

- Tabla `Tenants`.
- Tabla `Usuarios`.
- Columna `TenantID` en tablas financieras.
- Capa `storage/airtable_store.py` que exige `tenant_id`.
- Servicio `tenant_setup_service.py` para crear categorias, cuentas y deudas desde el bot.
- Comandos admin y setup:
  - `/admin_add_user`
  - `/admin_users`
  - `/admin_block_user`
  - `/mi_config`
  - `/configurar`

## Preparacion Manual En Airtable

Antes de desplegar `develop`, agrega estas tablas y columnas en la base actual. No elimines ni renombres tus columnas existentes.

### `Tenants`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `Nombre` | Single line text |
| `Estado` | Single select: `Activo`, `Pendiente`, `Bloqueado` |
| `Plan` | Single select: `Personal`, `Free`, `Pro` |
| `CreatedAt` | Date time |
| `UpdatedAt` | Date time |

### `Usuarios`

| Campo | Tipo |
| --- | --- |
| `UserID` | Single line text |
| `TenantID` | Single line text |
| `TelegramUserID` | Single line text |
| `Nombre` | Single line text |
| `Estado` | Single select: `Pendiente`, `Activo`, `Bloqueado` |
| `Rol` | Single select: `Admin`, `Owner`, `Member` |
| `SetupCompleto` | Single select: `No`, `Si` |
| `GmailEnabled` | Single select: `No`, `Si` |
| `VoiceEnabled` | Single select: `No`, `Si` |
| `CreatedAt` | Date time |
| `UpdatedAt` | Date time |

### Columnas Nuevas En Tablas Financieras

Agrega `TenantID` como `Single line text` en estas tablas:

- `Transacciones`
- `Cuentas`
- `Categorias`
- `Deudas`
- `MovimientosPendientes`
- `GmailEstado`
- `SaldosHistoricos`

Para tus registros actuales, rellena `TenantID` con el tenant del admin:

```text
TEN_TG_<tu_telegram_id>
```

Ejemplo:

```text
TEN_TG_123456789
```

Ese valor debe coincidir con `USER_ID` o `ADMIN_TELEGRAM_USER_ID` en el `.env`.

## Tipos De Columnas Financieras

### `Cuentas`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `ID` | Single line text |
| `Nombre` | Single line text |
| `NumeroCuenta` | Single line text |
| `Tipo` | Single select: `Efectivo`, `Banco`, `Credito`, `Crédito`, `Debito` |
| `Moneda` | Single select: `PEN`, `USD` |
| `SaldoActual` | Number, precision 2 |
| `LimiteCredito` / `LímiteCrédito` | Number, precision 2 |
| `DiaCorte` / `DíaCorte` | Number, precision 0 |
| `DiaPago` / `DíaPago` | Number, precision 0 |

### `Categorias`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `Nombre` | Single line text |
| `Tipo` | Single select: `Gasto`, `Ingreso` |
| `Subcategorias` / `Subcategorías` | Long text |

### `Transacciones`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `ID` | Single line text |
| `Fecha` | Date time |
| `Tipo` | Single select: `Gasto`, `Ingreso` |
| `Monto` | Number, precision 2 |
| `Moneda` | Single select: `PEN`, `USD` |
| `Categoria` / `Categoría` | Single line text |
| `Subcategoria` / `Subcategoría` | Single line text |
| `Cuenta` | Single line text |
| `Metodo` / `Método` | Single select: `Efectivo`, `Transferencia`, `Tarjeta de Crédito`, `Tarjeta de credito`, `Tarjeta de Débito` |
| `Nota` | Long text |
| `DeudaID` | Single line text |

`Cuenta`, `Categoria` y `Subcategoria` no deben ser select. Son texto porque dependen de la configuracion de cada tenant.

### `Deudas`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `ID` | Single line text |
| `Descripcion` | Single line text |
| `Tipo` | Single select: `Credito`, `Crédito`, `Servicio` |
| `MontoTotal` | Number, precision 2 |
| `Moneda` | Single select: `PEN`, `USD` |
| `MontoPagado` | Number, precision 2 |
| `FechaVencimiento` | Date |
| `Estado` | Single select: `Activa`, `Pagada`, `Vencida` |
| `CuentaAsociada` | Single line text |
| `Periodo` | Single line text |
| `FechaCorte` | Date |

`CuentaAsociada` no debe ser select. Es texto porque las cuentas se crean por tenant.

### `MovimientosPendientes`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `ID` | Single line text |
| `FechaDetectada` | Date time |
| `Fuente` | Single select: `GmailPush`, `ManualTelegram`, `Manual` |
| `Cuenta` | Single line text |
| `Tipo` | Single select: `Gasto`, `Ingreso` |
| `Monto` | Number, precision 2 |
| `Moneda` | Single select: `PEN`, `USD` |
| `Descripcion` | Long text |
| `Referencia` | Single line text |
| `Estado` | Single select: `Pendiente`, `Confirmado`, `Descartado` |
| `Confianza` | Number, precision 2 |
| `TXID` | Single line text |
| `FechaResolucion` | Date time |
| `Observacion` | Long text |

`Cuenta` no debe ser select.

### `GmailEstado`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `Clave` | Single line text |
| `Valor` | Single line text |
| `ActualizadoEn` | Date time |

### `SaldosHistoricos`

| Campo | Tipo |
| --- | --- |
| `TenantID` | Single line text |
| `SnapshotID` | Single line text |
| `FechaHora` | Date time |
| `Cuenta` | Single line text |
| `TipoCuenta` | Single select: `Banco`, `Crédito`, `Efectivo` |
| `Moneda` | Single select: `PEN`, `USD` |
| `Saldo` | Number, precision 2 |
| `SaldoPEN` | Number, precision 2 |
| `Origen` | Single select: `Manual`, `Automatico` |

`Cuenta` no debe ser select.

## Flujo Para Un Usuario Nuevo

1. El admin autoriza al usuario:

```text
/admin_add_user <telegram_id> <nombre>
```

2. El usuario revisa su contexto:

```text
/mi_config
```

3. El usuario precarga categorias:

```text
/configurar categorias
```

4. El usuario crea cuentas:

```text
/configurar cuenta BCP Banco PEN 1500 2091
/configurar cuenta AMEX Crédito PEN 0 5630
```

5. El usuario crea deudas si aplica:

```text
/configurar deuda Tarjeta_AMEX Crédito 0 PEN 2026-06-25 AMEX
```

6. El usuario cierra setup:

```text
/configurar finalizar
```

## Validaciones Antes De Pasar A `main`

1. Hacer backup/export de Airtable.
2. Agregar `TenantID` a todas las tablas financieras.
3. Rellenar todos los registros existentes con `TEN_TG_<USER_ID>`.
4. Crear `Tenants` y `Usuarios`, o dejar que `/admin_add_user` cree usuarios nuevos.
5. Verificar que las columnas dinamicas de cuenta/categoria/deuda sean texto, no select.
6. Ejecutar pruebas:

```powershell
python -m unittest tests.airtable_store_tests tests.tenant_context_tests tests.tenant_setup_service_tests
```

7. Probar en `develop`:

```text
/mi_config
/admin_users
/configurar categorias
/configurar cuentas
```

8. Solo despues hacer merge de `develop` a `main`.

## Riesgos Pendientes

- Varios comandos financieros legacy todavia usan `airtable_handler.py`; deben migrarse gradualmente para filtrar por tenant antes de abrirlos a mas usuarios.
- Gmail Push procesa un buzon global; por ahora debe mantenerse solo para admin o usuarios con `GmailEnabled=Si`.
- Voz usa configuracion global del proveedor; por ahora debe mantenerse solo para usuarios con `VoiceEnabled=Si`.
- Los IDs como `TX00001` pueden repetirse entre tenants. Mientras todos los accesos filtren por `TenantID`, esto es aceptable.
