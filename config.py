import os
from dotenv import load_dotenv

# Cargar variables desde .env si existe
load_dotenv()

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