"""Local web API for the bulk interface (ADR 0007). Imports the pipeline, never the reverse.

Needs the `ui` extra: `uv sync --extra ui`.
"""

from .app import ApiSettings, create_app

__all__ = ["ApiSettings", "create_app"]
