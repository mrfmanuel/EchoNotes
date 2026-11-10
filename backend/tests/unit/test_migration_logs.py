"""#41: `alembic upgrade head` (what the container runs on start) logs JSON lines only.

Runs the real Alembic CLI in a subprocess against a throwaway SQLite file, so it needs no
Docker. The Postgres variant lives in tests/integration/test_migrations.py.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import BACKEND_ENV_VARS

BACKEND_DIR = Path(__file__).resolve().parents[2]
REQUIRED_KEYS = {"timestamp", "level", "logger", "message", "request_id"}


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in BACKEND_ENV_VARS}
    env |= {"DATABASE_URL": database_url, "TRANSCRIBER_PROVIDER": "fake"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_alembic_cli_upgrade_logs_are_json_lines_in_the_app_format(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"

    result = _run_alembic(database_url, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    records = [json.loads(line) for line in lines]  # fails on any plain-text line
    assert records, "expected Alembic to log the migration"
    assert all(record.keys() >= REQUIRED_KEYS for record in records)
    messages = [r["message"] for r in records if r["logger"] == "alembic.runtime.migration"]
    assert any(m.startswith("Context impl") for m in messages)
    assert any(m.startswith("Running upgrade") for m in messages)
    assert database_url not in result.stdout + result.stderr
