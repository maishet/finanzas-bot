import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _load_dotenv_file(path):
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main():
    _load_dotenv_file(Path(".env"))

    client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        raise SystemExit(
            "Faltan GMAIL_CLIENT_ID o GMAIL_CLIENT_SECRET. Configuralos en .env antes de ejecutar este script."
        )

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )

    creds = flow.run_local_server(
        host="localhost",
        port=0,
        prompt="consent",
        authorization_prompt_message="Abre esta URL en tu navegador: {url}",
        success_message="Autorización completada. Puedes cerrar esta ventana.",
    )

    if not creds.refresh_token:
        raise SystemExit(
            "Google no devolvió refresh token. Repite el flujo y asegúrate de usar prompt=consent y que el usuario no haya autorizado antes sin 'offline access'."
        )

    print("\n=== REFRESH TOKEN ===")
    print(creds.refresh_token)
    print("\nCopia ese valor a GMAIL_REFRESH_TOKEN en tu .env")


if __name__ == "__main__":
    main()