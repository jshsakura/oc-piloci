import tomllib
from importlib import metadata
from pathlib import Path
from typing import cast

_DISTRIBUTION_NAME = "oc-piloci"


def _version_from_pyproject() -> str:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.exists():
            continue

        with pyproject.open("rb") as fp:
            data = cast(dict[str, object], tomllib.load(fp))

        raw_project = data.get("project")
        if not isinstance(raw_project, dict):
            raise RuntimeError("pyproject.toml is missing a [project] table")

        project = cast(dict[str, object], raw_project)
        version = project.get("version")
        if not isinstance(version, str):
            raise RuntimeError("pyproject.toml is missing a string [project].version")

        return version

    raise RuntimeError("Could not resolve piLoci version from package metadata or pyproject.toml")


try:
    __version__ = metadata.version(_DISTRIBUTION_NAME)
except metadata.PackageNotFoundError:
    __version__ = _version_from_pyproject()
