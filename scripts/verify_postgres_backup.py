"""Verify pg_dump/pg_restore using a temporary database in the local Compose stack."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import BinaryIO

ROOT = Path(__file__).resolve().parents[1]


def verify_backup(docker: str, compose_file: Path) -> dict[str, object]:
    prefix = [docker, "compose", "-f", str(compose_file), "exec", "-T", "postgres"]
    restore_database = f"restore_verify_{uuid.uuid4().hex[:12]}"

    def execute(
        shell: str,
        *arguments: str,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | int = subprocess.PIPE,
    ) -> bytes:
        result = subprocess.run(
            [*prefix, "sh", "-c", shell, "backup-check", *arguments],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=True,
            cwd=ROOT,
            timeout=300,
        )
        return result.stdout or b""

    with (
        tempfile.TemporaryDirectory() as temporary_directory,
        (Path(temporary_directory) / "database.dump").open("w+b") as backup,
    ):
        execute(
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom',
            stdout=backup,
        )
        if backup.tell() == 0:
            raise RuntimeError("pg_dump produced an empty backup")
        execute('exec createdb -U "$POSTGRES_USER" -- "$1"', restore_database)
        try:
            backup.seek(0)
            execute(
                'exec pg_restore -U "$POSTGRES_USER" -d "$1" '
                "--exit-on-error --no-owner",
                restore_database,
                stdin=backup,
            )
            query = (
                "SELECT json_build_object("
                "'migration', (SELECT version_num FROM alembic_version), "
                "'contracts', (SELECT count(*) FROM contracts), "
                "'chunks', (SELECT count(*) FROM contract_chunks), "
                "'obligations', (SELECT count(*) FROM obligations), "
                "'clauses', (SELECT count(*) FROM clauses), "
                "'risks', (SELECT count(*) FROM risks))"
            )
            restored = execute(
                'exec psql -U "$POSTGRES_USER" -d "$1" '
                '-v ON_ERROR_STOP=1 -A -t -c "$2"',
                restore_database,
                query,
            )
            report = json.loads(restored)
            if not isinstance(report, dict) or not report.get("migration"):
                raise RuntimeError("Restored database has no migration version")
            return report
        finally:
            execute(
                'exec dropdb -U "$POSTGRES_USER" --if-exists -- "$1"',
                restore_database,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default="docker")
    parser.add_argument(
        "--compose-file", type=Path, default=ROOT / "docker-compose.prod.yml"
    )
    args = parser.parse_args()
    report = verify_backup(args.docker, args.compose_file.resolve())
    print("PostgreSQL backup and isolated restore passed")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
