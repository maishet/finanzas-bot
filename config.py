import os
from dotenv import load_dotenv

# Cargar variables desde .env si existe
load_dotenv()


def _parse_csv_env(name):
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]

# Token del bot de Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("No se encontró TELEGRAM_TOKEN en variables de entorno")

# ID de usuario autorizado (para restringir comandos)
USER_ID = int(os.getenv("USER_ID", "123456789"))

# ID de la hoja de cálculo de Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise ValueError("No se encontró SPREADSHEET_ID en variables de entorno")

# Archivo de credenciales de la cuenta de servicio
GOOGLE_CREDENTIALS_FILE = "credentials.json"

# Moneda base
BASE_CURRENCY = "PEN"

# Tipo de cambio USD a PEN (puedes actualizarlo manualmente o más adelante consumir una API)
EXCHANGE_RATE = float(os.getenv("EXCHANGE_RATE", "3.44"))

# Voz a texto
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").strip().lower() in ["1", "true", "yes", "on"]
# Mantener es-PE como idioma funcional; motores STT suelen recibir "es".
VOICE_LOCALE = os.getenv("VOICE_LOCALE", "es-PE")
VOICE_LANGUAGE = os.getenv("VOICE_LANGUAGE", "es")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_TRANSCRIPTION_MODEL = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3").strip() or "whisper-large-v3"

# Modo de ejecución: polling (local) o webhook (servidor)
BOT_MODE = os.getenv("BOT_MODE", "polling").strip().lower()

# Configuración para Webhook (Render u otro hosting)
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/telegram-webhook").strip()
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = f"/{WEBHOOK_PATH}"

# URL pública del servicio (prioriza WEBHOOK_URL y luego RENDER_EXTERNAL_URL)
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip() or None

# Keep-alive opcional para Render Free. Cron-job.org puede pegarle a la URL raíz
# cada N minutos para evitar que el servicio entre en reposo.
KEEPALIVE_ENABLED = os.getenv("KEEPALIVE_ENABLED", "true").strip().lower() in ["1", "true", "yes", "on"]
if WEBHOOK_BASE_URL:
    KEEPALIVE_URL = f"{WEBHOOK_BASE_URL.rstrip('/')}/healthz"
else:
    KEEPALIVE_URL = None
KEEPALIVE_INTERVAL_MINUTES = int(os.getenv("KEEPALIVE_INTERVAL_MINUTES", "10"))

# Gmail Push (Gmail API + Pub/Sub)
GMAIL_PUSH_ENABLED = os.getenv("GMAIL_PUSH_ENABLED", "false").strip().lower() in ["1", "true", "yes", "on"]
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "").strip()
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
GMAIL_USER_EMAIL = os.getenv("GMAIL_USER_EMAIL", "").strip()
GMAIL_PUSH_TOPIC_NAME = os.getenv("GMAIL_PUSH_TOPIC_NAME", "").strip()
GMAIL_PUSH_VERIFY_TOKEN = os.getenv("GMAIL_PUSH_VERIFY_TOKEN", "").strip() or None
GMAIL_WATCH_LABEL_IDS = _parse_csv_env("GMAIL_WATCH_LABEL_IDS") or ["INBOX"]
GMAIL_WATCH_RENEW_BUFFER_HOURS = int(os.getenv("GMAIL_WATCH_RENEW_BUFFER_HOURS", "24"))
GMAIL_ALLOWED_SENDERS = [x.lower() for x in _parse_csv_env("GMAIL_ALLOWED_SENDERS")]

if GMAIL_PUSH_ENABLED and (not GMAIL_CLIENT_ID or not GMAIL_CLIENT_SECRET or not GMAIL_REFRESH_TOKEN or not GMAIL_PUSH_TOPIC_NAME):
    raise ValueError(
        "GMAIL_PUSH_ENABLED=true requiere GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN y GMAIL_PUSH_TOPIC_NAME."
    )

if WEBHOOK_BASE_URL:
    WEBHOOK_BASE_URL = WEBHOOK_BASE_URL.rstrip("/")
    FULL_WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
else:
    FULL_WEBHOOK_URL = None