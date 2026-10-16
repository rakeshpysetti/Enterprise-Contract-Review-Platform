import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def test_upgrade_preserves_legacy_contracts_and_schema_matches(tmp_path):
    root = Path(__file__).resolve().parents[2]
    database = tmp_path / "migration.db"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}"}

    def alembic(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=root,
            env=environment,
            check=True,
            capture_output=True,
        )

    alembic("upgrade", "c2b09b0030df")
    identifier = uuid4().hex
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO contracts "
            "(id,title,filename,status,parties,created_at,updated_at) "
            "VALUES (?,?,?,'pending','[]',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (identifier, "Existing agreement", "existing.pdf"),
        )
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT title,tenant_id,analysis_attempt_id FROM contracts WHERE id=?",
            (identifier,),
        ).fetchone()
        assert row == ("Existing agreement", "legacy", None)
    alembic("downgrade", "c2b09b0030df")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT title FROM contracts").fetchone() == (
            "Existing agreement",
        )
    alembic("upgrade", "head")
