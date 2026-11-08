import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def lint(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["lint-imports", "--config", str(ROOT / "pyproject.toml")],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(cwd / "src"), "PATH": os.environ["PATH"]},
    )


def test_contracts_hold_on_clean_copy(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    result = lint(tmp_path)
    assert result.returncode == 0, result.stdout


def test_contract_breaks_on_forbidden_import(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "src" / "aidm" / "rules" / "bad.py").write_text("import aidm.gateway\n")
    result = lint(tmp_path)
    assert result.returncode != 0, result.stdout
