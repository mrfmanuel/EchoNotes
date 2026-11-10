"""The backend version has a single source: pyproject.toml."""

import tomllib
from pathlib import Path

from app import __version__

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_version_is_read_from_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert __version__ == project["version"]


def test_version_string_is_not_duplicated_in_app_package() -> None:
    app_dir = PYPROJECT.parent / "app"
    for source in app_dir.rglob("*.py"):
        assert f'"{__version__}"' not in source.read_text(encoding="utf-8"), source
