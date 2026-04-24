from importlib import import_module
import tomllib
from pathlib import Path
from typing import cast


def test_package_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"

    with pyproject.open("rb") as fp:
        data = cast(dict[str, object], tomllib.load(fp))

    raw_project = data["project"]
    assert isinstance(raw_project, dict)
    project = cast(dict[str, object], raw_project)
    expected = project.get("version")
    assert isinstance(expected, str)

    imported_version = getattr(import_module("piloci"), "__version__", None)

    assert imported_version == expected
