import subprocess

import pytest


def ruff(path: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ruff", "check", "--stdin-filename", path, "-"],
        input=code,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("sdk", ["anthropic", "openai", "ollama"])
def test_sdk_banned_outside_providers(sdk: str) -> None:
    assert ruff("src/aidm/web/x.py", f"import {sdk}\n\nx = {sdk}.x\n").returncode != 0


def test_sdk_allowed_in_providers() -> None:
    assert ruff("src/aidm/providers/x.py", "import anthropic\n\nx = anthropic.x\n").returncode == 0


def test_print_banned() -> None:
    assert ruff("src/aidm/web/x.py", "print(1)\n").returncode != 0


def test_bare_except_banned() -> None:
    code = "try:\n    pass\nexcept:\n    pass\n"
    assert ruff("src/aidm/web/x.py", code).returncode != 0
