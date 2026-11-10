"""EchoNotes backend."""

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "echonotes-backend"

try:
    # pyproject.toml is the single source of truth for the version.
    __version__ = version(PACKAGE_NAME)
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled tree
    __version__ = "0.0.0"
