"""#9: Alembic reads DATABASE_URL from settings; no URL is hard-coded in alembic.ini."""

from configparser import ConfigParser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_alembic_ini_has_no_hard_coded_database_url() -> None:
    parser = ConfigParser()
    parser.read(BACKEND_DIR / "alembic.ini", encoding="utf-8")

    assert not parser.has_option("alembic", "sqlalchemy.url")


def test_alembic_env_takes_the_url_from_settings() -> None:
    source = (BACKEND_DIR / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "get_settings().sqlalchemy_url" in source
