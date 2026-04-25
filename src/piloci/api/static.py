from __future__ import annotations

from pathlib import Path

from starlette.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).parent.parent / "static"


def get_static_app() -> StaticFiles | None:
    """Return StaticFiles app if the web build exists, else None."""
    if _STATIC_DIR.exists() and any(_STATIC_DIR.iterdir()):
        return StaticFiles(directory=str(_STATIC_DIR), html=True)
    return None
