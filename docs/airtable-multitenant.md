# Arquitectura Airtable Multi-Tenant

Esta guia aplica a `main` y `develop`. La estructura operativa actual es multi-tenant sobre una sola base compartida de Airtable.

## Objetivo

El bot usa una sola base de Airtable compartida para todos los usuarios. La separacion de datos se hace con `TenantID` en cada tabla financiera.

Reglas principales:

- Cada usuario autorizado tiene un `TenantID`.
- Todas las lecturas y escrituras financieras deben filtrar por `TenantID`.
- No existe modo legacy: si una operacion financiera no recibe `tenant_id`, debe fallar.
- Los usuarios nuevos se crean desde Telegram con `/admin_add_user`.
- Las cuentas, deudas y categorias del usuario se configuran desde Telegram con `/configurar`.
- Gmail y voz quedan apagados para usuarios nuevos: `GmailEnabled=No` y `VoiceEnabled=No`.
- El admin puede mantener Gmail/voz para su usuario principal si las variables globales estan habilitadas.
- Jobs automaticos y webhooks sin usuario Telegram usan `SYSTEM_TENANT_ID`.

## Estado Actual

`main` opera con separacion obligatoria por `TenantID`. No debe quedar codigo financiero leyendo o escribiendo datos sin tenant.

La arquitectura agrega:

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

Antes de desplegar cambios sobre una base nueva, agrega estas tablas y columnas. No elimines ni renombres tus columnas existentes.

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
| `ID` | Number, precision 0 |
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
| `ID` | Number, precision 0 |
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

1. El usuario abre el bot y envia:

```text
/start
```

Si no esta autorizado, el bot envia una solicitud al administrador con botones para aprobar o denegar. El usuario no necesita conocer su Telegram ID.

2. El admin aprueba desde el mensaje recibido en Telegram.

Al aprobar, el bot crea `Tenants` y `Usuarios` con `SetupCompleto=No`, `GmailEnabled=No` y `VoiceEnabled=No`.

Tambien se puede autorizar manualmente:

```text
/admin_add_user <telegram_id> <nombre>
```

3. El usuario revisa su contexto:

```text
/mi_config
```

4. El usuario precarga categorias:

```text
/configurar categorias
```

5. El usuario crea cuentas:

```text
/configurar cuenta BCP Banco PEN 1500 2091
/configurar cuenta AMEX Crédito PEN 0 5630
```

6. El usuario crea deudas si aplica:

```text
/configurar deuda Tarjeta_AMEX Crédito 0 PEN 2026-06-25 AMEX
```

7. El usuario cierra setup:

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

## Reglas De Codigo Sin Legacy

Toda funcion financiera debe recibir `tenant_id` de forma explicita. Esto aplica a:

- lecturas: resumen, balance mensual, categorias, deudas, reportes, pendientes, GmailEstado
- escrituras: gasto, ingreso, pago de deuda, edicion, eliminacion, pendientes, snapshots
- automatizaciones: recordatorios, snapshot diario, renovacion Gmail Watch, webhook Gmail Push

Los comandos de Telegram deben resolver el tenant con `resolve_tenant_context(update.effective_user.id)` y pasar `tenant.tenant_id`.

Los procesos sin usuario Telegram deben usar:

```env
SYSTEM_TENANT_ID=TEN_TG_<telegram_id_admin>
```

No se debe usar un fallback silencioso al admin dentro de `airtable_handler.py`. La capa financiera debe fallar con error claro si falta `tenant_id`.

### Correlativos

Los correlativos deben calcularse por campo logico y por tenant, nunca por posicion de columna. Esto evita saltos cuando Airtable cambia el orden fisico de columnas.

- `Transacciones`: campo `ID`, prefijo `TX`
- `MovimientosPendientes`: campo `ID`, prefijo `MP`
- `Cuentas`: campo `ID`, numerico sin prefijo
- `Deudas`: campo `ID`, numerico sin prefijo
- `SaldosHistoricos`: campo `SnapshotID`, prefijo `SH`

Si `TenantID` existe en la tabla, el generador debe exigir `tenant_id` y buscar el maximo solo dentro de ese tenant.

## Limpieza De Datos Legacy

Despues de agregar `TenantID`, revisa que ninguna tabla financiera tenga registros con `TenantID` vacio o con valores temporales como `TEN00001`.

Tambien revisa `GmailEstado`. Las claves validas son:

- `GMAIL_REFRESH_TOKEN`
- `last_history_id`
- `last_push_at`
- `last_push_message_count`
- `watch_email`
- `watch_expiration`
- `watch_topic`
- `watch_updated_at`

Si aparecen claves que en realidad son valores, por ejemplo un email, un topic, un timestamp o un numero de expiracion, son residuos del esquema anterior y deben eliminarse.

## Riesgos Pendientes

- `airtable_handler.py` se mantiene como servicio financiero principal, pero sus lecturas y escrituras financieras deben recibir `tenant_id` y filtrar por `TenantID`.
- Gmail Push procesa un buzon global; por ahora debe mantenerse solo para admin o usuarios con `GmailEnabled=Si`.
- Voz usa configuracion global del proveedor; por ahora debe mantenerse solo para usuarios con `VoiceEnabled=Si`.
- Los IDs como `TX00001` pueden repetirse entre tenants. Mientras todos los accesos filtren por `TenantID`, esto es aceptable.
