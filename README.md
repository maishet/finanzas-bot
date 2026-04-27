# Finanzas Bot

Bot de Telegram para registrar gastos e ingresos, sincronizar movimientos con Google Sheets, controlar deudas de tarjetas de crédito y recibir recordatorios automáticos de vencimiento.

## Resumen

Este proyecto permite llevar un control financiero personal desde Telegram, guardando cada transacción en una hoja de Google Sheets y actualizando automáticamente:

- saldos de cuentas
- deuda asociada a tarjetas de crédito
- historial de transacciones
- balances mensuales
- recordatorios de vencimiento de deudas

El flujo está pensado para que puedas escribir algo tan simple como:

```text
/gasto 123.53 supermercado almuerzo tarjeta AMEX
```

y el bot se encargue de:

- detectar la cuenta AMEX
- reconocer que es una cuenta de tipo Crédito
- asignar el DeudaID correcto
- sumar el gasto a la deuda activa
- actualizar el saldo de la cuenta

## Características principales

- Registro de gastos e ingresos desde Telegram.
- Detección automática de cuenta en el texto del mensaje.
- Soporte para cuentas de tipo `Efectivo`, `Banco`, `Crédito` y `Debito`.
- Actualización automática de saldos en Google Sheets.
- Asociación de gastos a deudas activas mediante `DeudaID`.
- Cálculo de deuda pendiente usando `MontoTotal`, `MontoPagado` y `FechaVencimiento`.
- Comandos para resumen, balance mensual, categorías y deudas activas.
- Edición y eliminación de transacciones ya registradas.
- Registro de pagos de deuda desde cuentas de tipo Banco.
- Recordatorios automáticos de deudas próximas a vencer.
- Comando manual de recordatorios para usar cuando el servidor está en sleep.
- Exporte en PDF del cierre mensual con gráficos y KPIs.
- Manejo correcto de montos con formato regional, como `1.314,13`.
- Notas de voz con transcripción y confirmación antes de ejecutar.
- Interpretación de lenguaje natural para comandos generales: resumen, reporte, mes, deudas, categorías, pago, edición y eliminación.
- Keep-alive opcional para Render Free mediante cron-job.org.

## Arquitectura

```mermaid
flowchart TD
	A[Usuario en Telegram] --> B[bot.py]
	B --> C[Parseo del comando]
	C --> D[Detectar monto, categoría, cuenta y nota]
	D --> E[sheets_handler.py]
	E --> F[Google Sheets]
	F --> G[Transacciones]
	F --> H[Cuentas]
	F --> I[Deudas]
	E --> J[Actualizar saldo]
	E --> K[Actualizar deuda]
	E --> L[Calcular reportes]
	E --> M[Enviar recordatorios]
	M --> A
```

## Flujo de trabajo

```mermaid
sequenceDiagram
	participant U as Usuario
	participant T as Telegram
	participant B as Bot
	participant S as Google Sheets

	U->>T: /gasto 123.53 supermercado almuerzo tarjeta AMEX
	T->>B: Mensaje
	B->>B: Detecta cuenta AMEX y tipo Crédito
	B->>S: Guarda transacción en Transacciones
	B->>S: Actualiza saldo de AMEX en Cuentas
	B->>S: Busca deuda activa vinculada a AMEX
	B->>S: Suma el gasto al MontoTotal de la deuda
	B-->>T: Confirma registro y DeudaID
```

## Estructura del proyecto

```text
finanzas-bot/
├── .env
├── .gitignore
├── bot.py
├── config.py
├── credentials.json
├── README.md
├── requirements.txt
└── sheets_handler.py
```

## Archivos principales

### `bot.py`

Contiene la lógica del bot de Telegram:

- comandos disponibles
- parseo de mensajes
- validación de usuario autorizado
- envío de respuestas
- recordatorios automáticos con `JobQueue`

### `sheets_handler.py`

Contiene toda la lógica de negocio y acceso a Google Sheets:

- lectura y escritura de transacciones
- normalización de números y fechas
- búsqueda de cuentas
- actualización de saldos
- asociación de deudas
- edición y eliminación de transacciones
- generación de resúmenes y reportes
- consulta de recordatorios de deudas

### `config.py`

Carga variables de entorno y centraliza configuración:

- `TELEGRAM_TOKEN`
- `USER_ID`
- `SPREADSHEET_ID`
- `GOOGLE_CREDENTIALS_FILE`
- `BASE_CURRENCY`
- `EXCHANGE_RATE`
- `VOICE_ENABLED`
- `VOICE_LOCALE`
- `VOICE_LANGUAGE`
- `GROQ_API_KEY`
- `GROQ_TRANSCRIPTION_MODEL`
- `KEEPALIVE_ENABLED`
- `KEEPALIVE_INTERVAL_MINUTES`

### `credentials.json`

Archivo JSON de la cuenta de servicio de Google.

**Importante:** no debe subirse a GitHub.

### `.env`

Archivo local con variables sensibles del entorno.

**Importante:** no debe subirse a GitHub.

### `requirements.txt`

Lista de dependencias Python necesarias para el proyecto.

## Instalación

### 1. Crear y activar el entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Instalar dependencias

```powershell
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

#### Opción recomendada (rápida)

1. Copia el archivo de ejemplo:

```powershell
Copy-Item .env.example .env
```

2. Abre `.env` y reemplaza los valores placeholder.

3. Define el modo de ejecución según tu entorno:

- Local: `BOT_MODE=polling`
- Render: `BOT_MODE=webhook` y configura `WEBHOOK_URL`

#### Opción manual

Crear un archivo `.env` con algo similar a esto:

```env
TELEGRAM_TOKEN=tu_token_de_telegram
USER_ID=123456789
SPREADSHEET_ID=tu_id_de_google_sheets
EXCHANGE_RATE=3.44
```

### 4. Agregar credenciales de Google

Coloca el archivo `credentials.json` en la raíz del proyecto.

## Cómo obtener `credentials.json` (Google Cloud Console)

Este paso es obligatorio para que el bot pueda leer y escribir en Google Sheets.

### 1. Crear o elegir un proyecto en Google Cloud

1. Ve a Google Cloud Console.
2. Crea un proyecto nuevo o selecciona uno existente.

### 2. Habilitar APIs necesarias

1. En el proyecto, entra a APIs y servicios.
2. Habilita estas APIs:
- Google Sheets API
- Google Drive API

### 3. Crear una cuenta de servicio

1. Ve a IAM y administración > Cuentas de servicio.
2. Crea una cuenta de servicio (ejemplo: `finanzas-bot-sa`).
3. Finaliza la creación.

### 4. Generar la clave JSON

1. Abre la cuenta de servicio creada.
2. Ve a la pestaña Claves.
3. Agrega una nueva clave.
4. Selecciona tipo JSON.
5. Descarga el archivo.

Renombra ese archivo a `credentials.json` y colócalo en la raíz del proyecto.

### 5. Compartir tu Google Sheet con la cuenta de servicio

1. Abre el archivo JSON descargado.
2. Copia el valor de `client_email`.
3. Ve a tu Google Sheet.
4. Pulsa Compartir y agrega ese correo como Editor.

Si no haces este paso, el bot fallará con errores de permisos aunque el JSON sea válido.

### 6. Configurar el ID del Sheet

1. Abre tu Google Sheet en el navegador.
2. Copia el ID desde la URL:

```text
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=0
```

3. Coloca ese valor en `SPREADSHEET_ID` en tu `.env`.

### Seguridad recomendada

1. Nunca subas `credentials.json` a GitHub.
2. Verifica que `.gitignore` incluya `credentials.json`.
3. En producción (Render), usa Secret File o variable segura para manejar credenciales.

## Dependencias

Las principales librerías usadas son:

- `python-telegram-bot[job-queue]` para el bot y recordatorios programados.
- `gspread` para trabajar con Google Sheets.
- `google-auth` para autenticación con cuenta de servicio.
- `python-dotenv` para cargar variables del archivo `.env`.
- `pytz` y `APScheduler` como soporte de tareas programadas.
- `oauth2client` por compatibilidad con autenticación en Google APIs.
- `groq` para transcripción de notas de voz.
- `reportlab` para generación de PDFs con gráficos y KPIs.

## Estado actual del proyecto

### Ya implementado

- ~~Registro de gastos e ingresos desde Telegram.~~
- ~~Detección automática de cuenta en el texto del mensaje.~~
- ~~Soporte para cuentas de tipo `Efectivo`, `Banco`, `Crédito` y `Debito`.~~
- ~~Actualización automática de saldos en Google Sheets.~~
- ~~Asociación de gastos a deudas activas mediante `DeudaID`.~~
- ~~Cálculo de deuda pendiente usando `MontoTotal`, `MontoPagado` y `FechaVencimiento`.~~
- ~~Comandos para resumen, balance mensual, categorías y deudas activas.~~
- ~~Edición y eliminación de transacciones ya registradas.~~
- ~~Registro de pagos de deuda desde cuentas de tipo Banco.~~
- ~~Recordatorios automáticos de deudas próximas a vencer.~~
- ~~Comando manual de recordatorios para usar cuando el servidor está en sleep.~~
- ~~Exporte en PDF del cierre mensual con gráficos y KPIs.~~
- ~~Manejo correcto de montos con formato regional, como `1.314,13`.~~
- ~~Notas de voz con transcripción y confirmación antes de ejecutar.~~
- ~~Interpretación de lenguaje natural para comandos generales: resumen, reporte, mes, deudas, categorías, pago, edición y eliminación.~~
- ~~Keep-alive opcional para Render Free mediante cron-job.org.~~

### Pendientes recomendados

1. Persistir un historial de comandos de voz fallidos para afinar el parser sin guardar transcripciones completas.
2. Agregar un comando `/recalcular` para reconstruir saldos y deudas desde transacciones históricas.
3. Exponer un endpoint de healthcheck dedicado para monitoreo externo.
4. Añadir alertas por errores operativos críticos en Sheets o webhook.
5. Mejorar el soporte de conversación guiada para edición de transacciones complejas.
6. Incorporar gráficos históricos o comparativos por varios meses en el PDF.
7. Evaluar un panel web liviano de consulta rápida sin salir de Telegram.

## Comandos del bot

### Registro de movimientos

#### `/gasto`

Registra un gasto y lo asocia automáticamente a la cuenta detectada.

Ejemplo:

```text
/gasto 123.53 supermercado almuerzo tarjeta AMEX
```

#### `/ingreso`

Registra un ingreso.

Ejemplo:

```text
/ingreso 1500 sueldo quincena BCP
```

### Consulta

#### `/resumen`

Muestra el saldo de cada cuenta, total de activos, total de pasivos y patrimonio neto.

#### `/mes [MM/AAAA]`

Muestra ingresos, gastos y ahorro de un mes específico.

Ejemplo:

```text
/mes 04/2026
```

#### `/reporte [MM/AAAA]`

Genera un PDF de cierre mensual con indicadores y visualizaciones.

Ejemplo:

```text
/reporte 04/2026
```

Si no envías fecha, usa el mes actual.

El reporte incluye:

- Ingreso total del mes
- Gasto total del mes
- Ahorro total del mes
- Total de transacciones
- Categoría con mayor gasto
- Transacción más alta
- Gráfico de barras (ingresos, gastos, ahorro)
- Gráfico circular de gastos por categoría
- Ranking gráfico de cuentas con mayor uso
- Fecha y hora de generación

#### `/categoria <nombre>`

Muestra el gasto acumulado de una categoría en el mes actual.

#### `/deudas`

Lista las deudas activas con su pendiente, vencimiento y cuenta asociada.

#### `/recordatorios`

Muestra alertas manuales de deudas por vencer (ventana de 7 días).

Ejemplo:

```text
/recordatorios
```

#### `/pagar <deuda_id> <monto> <cuenta_banco> [nota]`

Registra un pago de deuda usando una cuenta de tipo Banco.

Qué hace internamente:

- aumenta `MontoPagado` de la deuda
- reduce saldo de la cuenta banco
- crea una transacción tipo `Gasto` asociada al `DeudaID`
- recalcula estado de deuda (`Activa`, `Pagada`, `Vencida`)
- avanza `FechaVencimiento` un mes en cada pago registrado (aplica para tarjetas y servicios)

Ejemplo:

```text
/pagar 1 250 BCP pago quincena
```

#### `/categorias`

Muestra categorías de gasto e ingreso, junto con sus subcategorías si existen.

### Mantenimiento de transacciones

#### `/editar <ID> <campo> <valor>`

Edita una transacción ya registrada.

Campos soportados:

- `monto`
- `moneda`
- `categoria`
- `subcategoria`
- `cuenta`
- `metodo`
- `nota`
- `fecha`

Ejemplo:

```text
/editar TX00012 monto 150.75
```

#### `/eliminar <ID>`

Elimina una transacción y revierte su impacto en saldo y deuda.

Ejemplo:

```text
/eliminar TX00012
```

## Cómo funciona el manejo de cuentas

El bot reconoce cuentas dentro del texto del mensaje y las cruza con la hoja `Cuentas`.

Tipos de cuenta soportados:

- `Efectivo`
- `Banco`
- `Crédito`
- `Debito`

La lógica de método de pago se asigna así:

- `Efectivo` → `Efectivo`
- `Banco` → `Transferencia`
- `Crédito` → `Tarjeta de Crédito`
- `Debito` → `Tarjeta de Débito`

## Cómo funciona el manejo de deudas

Cada cuenta de crédito puede estar vinculada a una deuda activa en la hoja `Deudas`.

El sistema usa:

- `CuentaAsociada` para enlazar la deuda con la cuenta
- `FechaVencimiento` para decidir si está vigente o vencida
- `Estado` para marcar `Activa`, `Vencida` o `Pagada`
- `MontoTotal` como el total consumido/acumulado en la deuda
- `MontoPagado` como lo ya abonado

Para deudas recurrentes (por ejemplo servicios básicos), al registrar un pago se avanza `FechaVencimiento` en +1 mes automáticamente.

### Lógica de deuda

```mermaid
flowchart TD
	A[Gasto en cuenta de crédito] --> B{Existe deuda activa asociada?}
	B -- Sí --> C[Incrementar MontoTotal]
	C --> D[Guardar DeudaID en la transacción]
	D --> E[Actualizar saldo de la cuenta]
	B -- No --> F[Guardar transacción sin deuda asociada]
```

## Recordatorios automáticos

El bot puede enviar recordatorios automáticos de deudas próximas a vencer.

Comportamiento actual:

- se ejecuta al iniciar el bot
- se ejecuta diariamente a las 12:00 en tres ventanas: 7, 3 y 1 día antes del vencimiento
- detecta deudas activas y vencidas próximas
- alerta por consola y por Telegram al usuario autorizado

Si el entorno no tiene `JobQueue`, el bot avisa que los recordatorios automáticos quedaron desactivados.

## Render Free: limitaciones y mitigaciones

En plan gratuito de Render, el servicio puede entrar en reposo. Cuando eso ocurre:

- el primer mensaje después de inactividad puede demorar (cold start)
- Telegram reintenta el webhook, pero puede sentirse como "no responde"
- tareas programadas de recordatorio pueden no ejecutarse de forma confiable 24/7

Mitigaciones prácticas en free plan:

1. Priorizar comandos manuales para validar estado:
- `/deudas`
- `/resumen`
- `/recordatorios`

2. Usar recordatorio manual como respaldo operativo:
- Revisar deudas al menos una vez al día con `/deudas` o `/recordatorios`.

3. Mantener tiempos de espera realistas:
- tras inactividad, el primer request puede tardar en despertar el servicio.

4. Evitar depender de eventos críticos solo en scheduler gratuito:
- tratar alertas automáticas como ayuda, no como única fuente.

5. Mantener el servicio despierto con una tarea externa opcional:
- configura `KEEPALIVE_ENABLED=true`
- define `WEBHOOK_URL=https://tu-app.onrender.com`
- crea un cron-job en cron-job.org para hacer una petición HTTP GET a esa URL cada 10 minutos
- cuando migres a un plan de pago, cambia `KEEPALIVE_ENABLED=false` y elimina el cron-job

Además del cron externo, el bot ejecuta un ping interno periódico a `WEBHOOK_URL/healthz` cuando está en `BOT_MODE=webhook`.
Verás trazas como `Keep-alive ping | url=... status=...` en logs.

### Keep-alive opcional con cron-job.org

Si usas Render Free y quieres evitar que el servicio se duerma, puedes automatizar una petición HTTP a la URL raíz del bot.

Configuración recomendada:

1. En tu `.env` o variables del entorno, define:

```env
KEEPALIVE_ENABLED=true
WEBHOOK_URL=https://tu-app.onrender.com
KEEPALIVE_INTERVAL_MINUTES=10
```

2. En cron-job.org, crea un nuevo cron job.
3. Usa método `GET`.
4. Apunta la URL a `WEBHOOK_URL/healthz` (por ejemplo, `https://tu-app.onrender.com/healthz`).
5. Programa la ejecución cada 10 minutos.
6. Si más adelante migras a un plan pago, desactiva la variable:

```env
KEEPALIVE_ENABLED=false
```

7. Elimina o pausa el cron job para no dejar tráfico innecesario.

Diagnóstico rápido en Render:

1. Verifica que aparezca `Keep-alive activo | cada ... min | url=...` al iniciar.
2. Verifica pings periódicos `Keep-alive ping | url=... status=...`.
3. Si no aparece, revisa que `BOT_MODE=webhook`, `KEEPALIVE_ENABLED=true` y `WEBHOOK_URL` estén definidos.

## Roadmap recomendado

### Fase actual (Render Free)

1. ~~Consolidar confiabilidad básica de comandos (`/gasto`, `/ingreso`, `/pagar`, `/deudas`).~~
2. ~~Fortalecer comando manual de chequeo de recordatorios (`/recordatorios`) con filtros por días.~~
3. Añadir snapshots diarios en Google Sheets (hoja histórica simple) para auditoría.
4. Implementar comando `/recalcular` para reconstruir saldos/deudas desde transacciones.
5. Añadir modo opcional de keep-alive con variable de entorno para Render Free.
6. Ajustar el parser de voz con frases reales del usuario para reducir ambigüedad.

### Fase siguiente (cuando migres a plan pago)

1. ~~Servicio always-on sin reposo para webhook estable.~~
2. ~~Recordatorios automáticos realmente confiables por cron interno.~~
3. ~~Múltiples horarios de notificación (ejemplo: 7 días, 3 días y 1 día antes del vencimiento).~~
4. Endpoint de healthcheck y monitoreo externo.
5. Alertas por error operativo (fallos de Sheets, credenciales, webhook).
6. Futuro panel web básico (resumen, deudas, bitácora) sin dejar Telegram.
7. Desactivar keep-alive externo cuando ya no sea necesario.

### Ideas futuras de producto

1. Soporte multimoneda más robusto con tipo de cambio automático por API.
2. Usar notas de voz que se transcriban a texto y que se interpreten a comandos.
3. Respuestas proactivas con resúmenes semanales y mensuales por Telegram.
4. Exportación de reportes comparativos entre varios meses.
5. Panel web de solo lectura para consultar estados desde el móvil.

## Formato de números

El proyecto ya está preparado para manejar formatos regionales como:

- `1.314,13`
- `33.879,91`
- `25,50`
- `123.53`

Esto evita errores al leer montos y saldos desde Google Sheets, especialmente si la hoja está configurada con formato latinoamericano.

## Ejemplo de uso completo

1. Registras un gasto:

```text
/gasto 123.53 supermercado almuerzo tarjeta AMEX
```

2. El bot detecta:

- monto: `123.53`
- categoría: `supermercado`
- cuenta: `AMEX`
- método: `Tarjeta de Crédito`

3. Guarda en Google Sheets:

- fila en `Transacciones`
- saldo actualizado en `Cuentas`
- deuda incrementada en `Deudas`
- `DeudaID` asociado

## Recomendaciones

- Mantén `credentials.json` y `.env` fuera del repositorio.
- No edites manualmente montos formateados como texto en Google Sheets; deja que el bot los actualice.
- Si cambias la estructura de las hojas, revisa también `sheets_handler.py`.
- Si agregas nuevas cuentas, asegúrate de que el tipo sea uno de los soportados.

## Solución de problemas

### El bot no inicia recordatorios

Verifica que tengas instaladas las dependencias del scheduler:

```powershell
pip install "python-telegram-bot[job-queue]==22.7"
```

### Los montos salen mal

Revisa que la hoja esté usando formato numérico y que no hayas mezclado texto con números en columnas de saldo o deuda.

### No detecta una cuenta

Confirma que el nombre de la cuenta en la hoja `Cuentas` coincida con lo que escribes en el mensaje, ignorando tildes y mayúsculas.

## Licencia

Proyecto personal sin licencia pública definida.

