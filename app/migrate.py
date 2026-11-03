"""Apply ordered, transactional SQL migrations, including on existing volumes."""

import logging
from pathlib import Path

from app.database import connect


def migrate() -> None:
    with connect() as connection:
        # Serialize concurrent startup attempts; a failed migration rolls back.
        connection.execute("SELECT pg_advisory_xact_lock(72646601)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            if path.name not in applied:
                connection.execute(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,)
                )
                logging.info("Applied migration %s", path.name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
