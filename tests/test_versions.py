"""The four CLIs ship in one wheel and must report the same version."""

import importlib
import io
import re
from contextlib import redirect_stdout

import pytest

from vmtools.download import _format_eta


def _project_version() -> str:
    text = open("pyproject.toml", encoding="utf-8").read()
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


@pytest.mark.parametrize("name", ["windowsvm", "linuxvm", "androidvm", "vmtools"])
def test_cli_version_matches_the_package(name):
    cli = importlib.import_module(f"{name}.cli")
    parser = cli.build_parser()
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    assert buf.getvalue().strip() == f"{name} {_project_version()}"


def test_eta_handles_nan_inf_and_negative():
    assert _format_eta(float("nan")) == "--:--"
    assert _format_eta(float("inf")) == "--:--"
    assert _format_eta(-1) == "--:--"
    assert _format_eta(75) == "01:15"
    assert _format_eta(3725) == "01:02:05"
