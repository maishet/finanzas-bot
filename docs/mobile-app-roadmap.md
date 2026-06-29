# Roadmap App Movil y API

Este documento registra el plan acordado para evolucionar `finanzas-bot` desde un bot de Telegram hacia una plataforma financiera visual con app movil, API propia y migracion futura a base relacional.

## Decisiones Confirmadas

- La app movil se construira con React Native, Expo y TypeScript desde el inicio.
- La app debe quedar lista para Android e iOS, aunque el primer uso real sea Android.
- El proyecto movil vivira separado en `E:\Personal proyects\finanzas-mobile`.
- El backend actual `finanzas-bot` seguira siendo el backend principal.
- Telegram se mantiene como canal operativo existente, no se reemplaza.
- Airtable se mantiene como base operativa inicial.
- La migracion a Supabase/Postgres se hara despues de estabilizar API y app.
- La autenticacion inicial para la app sera OTP enviado por Telegram.
- OTP sera una primera version, no la arquitectura final de autenticacion.
- Render Free seguira siendo el hosting del backend.
- El keep-alive actual cada 10 minutos se mantiene para evitar que Render duerma.

## Arquitectura Objetivo Progresiva

```text
finanzas-mobile
  React Native + Expo + TypeScript
  |
  | HTTPS / JSON API
  v
finanzas-bot
  API movil + Telegram bot + Gmail Push + jobs
  |
  | servicios de negocio
  v
storage
  Airtable inicialmente
  Supabase/Postgres a futuro
```

La app movil nunca debe conectarse directo a Airtable. Toda operacion debe pasar por el backend para aplicar autenticacion, tenant, validaciones y reglas de negocio.

## Fase 1: API Backend Minima

Objetivo: exponer datos read-only del bot por HTTP sin romper Telegram.

Tareas:

1. Agregar una API movil al backend actual.
2. Mantener Telegram, Gmail Push y jobs funcionando.
3. Proteger temporalmente la API con una API key mientras llega OTP/JWT.
4. Requerir `TenantID` para todas las lecturas financieras.
5. Exponer endpoints iniciales:
   - `GET /healthz`
   - `GET /api/version`
   - `GET /api/me`
   - `GET /api/accounts`
   - `GET /api/summary`
   - `GET /api/transactions`
   - `GET /api/debts`
   - `GET /api/pending-movements`
6. Preparar estructura para FastAPI y modelos Pydantic.
7. Mantener compatibilidad con el servidor actual de Render.

Notas de seguridad de Fase 1:

- Los endpoints financieros deben exigir `X-Mobile-Api-Key`.
- Los endpoints financieros deben exigir `X-Tenant-ID`.
- `MOBILE_API_KEY` debe estar definido en Render antes de exponer la API a la app.
- Esta API key es temporal y sera reemplazada por JWT en Fase 2.

## Fase 2: Autenticacion OTP Por Telegram

Objetivo: permitir login movil sin contrasenas.

Flujo:

```text
App -> POST /api/auth/request-code
Backend -> valida usuario activo
Backend -> genera OTP temporal
Backend -> envia OTP por Telegram
Usuario -> ingresa OTP en app
App -> POST /api/auth/verify-code
Backend -> devuelve JWT
App -> guarda JWT en SecureStore
```

Endpoints:

- `POST /api/auth/request-code`
- `POST /api/auth/verify-code`
- `POST /api/auth/logout`

Implementacion acordada para esta fase:

- `request-code` usa `X-Mobile-Api-Key` como proteccion temporal contra abuso.
- `verify-code` usa `X-Mobile-Api-Key` y devuelve un JWT.
- Los endpoints financieros aceptan `Authorization: Bearer <jwt>`.
- Mientras la app termina de migrar a JWT, los endpoints financieros tambien pueden aceptar `X-Mobile-Api-Key` + `X-Tenant-ID`.
- La tabla `AuthCodes` vive temporalmente en Airtable.
- Cuando se migre a Supabase, `AuthCodes` pasara a Postgres o se reemplazara por Supabase Auth.

Datos del JWT:

- `tenant_id`
- `telegram_user_id`
- `rol`
- `exp`

Tabla sugerida inicial en Airtable:

```text
AuthCodes
- TenantID
- TelegramUserID
- CodeHash
- ExpiresAt
- UsedAt
- CreatedAt
- Attempts
```

Reglas:

- No guardar OTP plano; guardar hash.
- Expiracion corta.
- Limitar intentos.
- Invalidar codigo al usarlo.

## Fase 3: Proyecto Movil Expo

Objetivo: crear `finanzas-mobile` como app visual moderna.

Stack:

- React Native
- Expo
- TypeScript
- Expo Router
- TanStack Query
- React Hook Form
- Zod
- Expo SecureStore
- NativeWind o Tamagui
- React Native SVG
- Libreria simple de graficos

Estructura propuesta:

```text
finanzas-mobile/
├── app/
│   ├── _layout.tsx
│   ├── index.tsx
│   ├── login.tsx
│   ├── verify.tsx
│   └── (tabs)/
│       ├── _layout.tsx
│       ├── dashboard.tsx
│       ├── accounts.tsx
│       ├── movements.tsx
│       ├── debts.tsx
│       └── settings.tsx
├── src/
│   ├── api/
│   ├── auth/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── theme/
│   ├── types/
│   └── utils/
├── app.json
├── package.json
└── tsconfig.json
```

## Fase 4: MVP Visual Solo Lectura

Pantallas:

- Login
- Verificacion OTP
- Dashboard
- Cuentas
- Movimientos
- Deudas
- Pendientes Gmail
- Configuracion basica

Dashboard inicial:

- Patrimonio neto.
- Total activos.
- Total pasivos.
- Ingresos del mes.
- Gastos del mes.
- Ahorro del mes.
- Deudas proximas.
- Ultimos movimientos.
- Pendientes por confirmar.

## Fase 5: Acciones Desde La App

Objetivo: que la app permita operar, no solo consultar.

Endpoints futuros:

- `POST /api/transactions`
- `PATCH /api/transactions/{id}`
- `DELETE /api/transactions/{id}`
- `POST /api/debts/{id}/pay`
- `POST /api/pending-movements/{id}/confirm`
- `POST /api/pending-movements/{id}/discard`
- `POST /api/snapshots`

Regla critica:

- La app no calcula impacto financiero critico. Solo envia intenciones. El backend aplica reglas de negocio.

## Fase 6: Refactor Progresivo Del Backend

Objetivo: preparar migracion futura a Supabase/Postgres sin reescribir todo.

Estructura objetivo:

```text
services/
├── account_service.py
├── transaction_service.py
├── debt_service.py
├── pending_service.py
├── report_service.py
└── auth_service.py

repositories/
├── interfaces.py
├── airtable_repository.py
└── future_supabase_repository.py

domain/
└── finance_models.py

utils/
└── finance_format.py
```

Reglas:

- Nuevos endpoints deben usar servicios, no detalles de Airtable directamente.
- Telegram y app deben compartir la misma logica de negocio.
- El refactor debe ser incremental.
- No introducir modo legacy sin tenant.
- La arquitectura relacional objetivo queda documentada en `docs/database-architecture.md`.
- Tablas, columnas y valores normalizados internos deben estar en ingles y `snake_case`.
- La API movil puede mantener payloads actuales temporalmente, pero repositories y migracion futura deben mapear hacia entidades normalizadas en ingles.
- Categorias usadas no se borran fisicamente; se ocultaran con `is_active = false` en el modelo relacional.
- Utilidades neutrales de formato/fechas/numeros viven fuera de `airtable_handler`.
- Los services pueden convertir entidades internas normalizadas a payloads legacy/mobile hasta completar la migracion de contratos.

## Fase 7: Supabase/Postgres

Objetivo: migrar a base relacional cuando API y app esten estables.

Tablas futuras:

```text
tenants
users
accounts
categories
transactions
debts
pending_movements
gmail_state
balance_snapshots
auth_codes
audit_logs
```

Tareas:

1. Disenar schema SQL.
2. Crear migraciones.
3. Crear repositorio Postgres/Supabase.
4. Crear script Airtable -> Supabase.
5. Validar conteos y totales por tenant.
6. Probar backend contra Supabase.
7. Cortar trafico a Supabase.
8. Mantener Airtable como backup temporal.

## Arquitectura Objetivo De Largo Plazo

Decision estrategica: `Fint` debe evolucionar de un bot con app movil a una plataforma financiera personal completa. Telegram sera una integracion opcional o historica, no el nucleo del producto.

Objetivo final:

```text
apps/
  mobile/        Expo + React Native
  web/           Next.js/React futuro

backend/
  api/           TypeScript, Hono/Fastify/Nest
  workers/       TypeScript jobs e integraciones
  integrations/  Gmail, Outlook, bancos, Telegram opcional

packages/
  shared-types/  contratos compartidos
  validation/    Zod schemas
  design-system/ componentes compartidos futuro

database/
  migrations/    Supabase/Postgres
  seed/
```

Lineamientos:

- Python se mantiene solo como backend de transicion durante mobile real, acciones y migracion a Supabase.
- A largo plazo no se mantendra Python como legacy permanente.
- El backend moderno sera TypeScript para tener un solo lenguaje entre app, web y API.
- Supabase/Postgres reemplazara Airtable como base principal, pero no reemplaza la API de negocio.
- La app enviara intenciones; el backend aplicara reglas financieras, auditoria e impacto en saldos/deudas.
- Telegram, Gmail y Outlook seran integraciones, no arquitectura central.
- La migracion Python -> TypeScript debe ser gradual, endpoint por endpoint, despues de estabilizar contratos y datos.

Stack objetivo sugerido:

- API: Hono o Fastify; Nest solo si la complejidad lo justifica.
- DB: Supabase Postgres.
- Auth: Supabase Auth.
- Validacion: Zod.
- ORM/query: Drizzle o Prisma.
- Jobs: Trigger.dev, Inngest, BullMQ o workers propios.
- Observabilidad: Sentry y logs estructurados.
- Hosting: Fly.io, Railway, Render Pro o infraestructura equivalente.

Orden recomendado para llegar ahi:

1. Completar app movil real contra backend actual.
2. Completar acciones desde la app.
3. Terminar separacion services/repositories en Python.
4. Migrar Airtable a Supabase/Postgres.
5. Crear backend TypeScript con contratos compartidos.
6. Migrar endpoints criticos uno por uno.
7. Retirar Python cuando el backend TypeScript cubra API, jobs e integraciones necesarias.

## Evolucion De Autenticacion

Ruta futura:

1. OTP Telegram + JWT.
2. Vinculacion de email.
3. Supabase Auth con magic link o Google.
4. Relacion `SupabaseUserID -> TenantID`.
5. Revocacion de sesiones.
6. Refresh tokens.
7. Roles mas finos por tenant.

## Push Notifications Futuras

Decision: no usar push notifications para feedback inmediato dentro de la app. Las acciones que el usuario ejecuta mirando la pantalla deben usar toast in-app temporal: movimiento creado, pendiente confirmado, pago registrado o error al guardar.

Push notifications se evaluaran despues de estabilizar servicios, jobs y migracion progresiva de almacenamiento. Deben usarse para eventos asincronicos o externos al usuario:

- Movimientos detectados desde Gmail, Outlook u otras fuentes.
- Pendientes importantes por revisar.
- Alertas de deuda por vencer.
- Alertas de pago vencido.
- Gasto inusual o comportamiento fuera de patron.
- Resumen semanal o mensual.
- Fallos de sincronizacion de fuentes conectadas.
- Eventos de seguridad como nuevo login.

Requisitos antes de implementarlas:

- Solicitud explicita de permisos al usuario.
- Registro de token push por dispositivo.
- Endpoint backend para registrar y revocar dispositivos.
- Jobs o workers para disparar notificaciones.
- Politica anti-spam por tenant y tipo de alerta.
- Soporte Android/iOS con Expo Notifications, FCM/APNs o equivalente.

## Render

Render Free se mantiene.

Requisitos:

- `/healthz` debe seguir respondiendo.
- El cron externo debe seguir pegando cada 10 minutos.
- Telegram webhook y API deben convivir.
- Gmail Push debe conservar `/gmail/push`.
- La app movil usara la URL publica de Render.
- CORS debe estar habilitado para desarrollo con Expo.

## Orden De Ejecucion

1. API read-only protegida por API key.
2. OTP Telegram + JWT.
3. Crear `finanzas-mobile` con Expo.
4. Login conectado.
5. Dashboard conectado.
6. Cuentas, movimientos y deudas read-only.
7. Acciones financieras desde app.
8. Refactor a servicios.
9. Preparacion Supabase.
10. Migracion relacional.
