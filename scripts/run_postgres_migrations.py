import argparse
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config


def connect(database_url):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg to run Postgres migrations: pip install psycopg[binary]") from exc
    return psycopg.connect(database_url)


def main():
    parser = argparse.ArgumentParser(description="Run Fint Postgres migrations in lexical order.")
    parser.add_argument("--database-url", default=config.SUPABASE_DATABASE_URL, help="Postgres connection URL. Defaults to SUPABASE_DATABASE_URL/DATABASE_URL.")
    parser.add_argument("--migrations-dir", default="database/migrations", help="Directory containing .sql migrations.")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("SUPABASE_DATABASE_URL or DATABASE_URL is required.")

    migrations = sorted(Path(args.migrations_dir).glob("*.sql"))
    if not migrations:
        raise SystemExit(f"No migrations found in {args.migrations_dir}")

    with connect(args.database_url) as conn:
        with conn.cursor() as cursor:
            for migration in migrations:
                print(f"Applying {migration}")
                cursor.execute(migration.read_text(encoding="utf-8"))
        conn.commit()

    print(f"Applied {len(migrations)} migrations.")


if __name__ == "__main__":
    main()
