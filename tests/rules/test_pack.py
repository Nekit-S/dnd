import shutil
from pathlib import Path

import pytest

from aidm.rules.pack import PackError, PackOptionError, load_pack, resolve_options

MINI = Path(__file__).parent / "fixtures" / "mini-pack"


def copy_pack(tmp_path: Path) -> Path:
    dst = tmp_path / "pack"
    shutil.copytree(MINI, dst)
    return dst


def test_loads_mini_pack() -> None:
    pack = load_pack(MINI)
    assert pack.id == "mini"
    assert pack.rounding == "down"
    assert pack.data["tables"]["xp"]["2"] == 300
    assert pack.data["tables"]["cr_eighth"] == "1/8"


def test_wrong_checksum_names_file(tmp_path: Path) -> None:
    d = copy_pack(tmp_path)
    (d / "tables.yaml").write_text("xp: {}\n")
    with pytest.raises(PackError, match="tables.yaml"):
        load_pack(d)


def test_missing_file(tmp_path: Path) -> None:
    d = copy_pack(tmp_path)
    (d / "tables.yaml").unlink()
    with pytest.raises(PackError, match="tables.yaml"):
        load_pack(d)


def test_float_rejected(tmp_path: Path) -> None:
    import hashlib

    d = copy_pack(tmp_path)
    body = b"x: [1, {y: 0.5}]\n"
    (d / "tables.yaml").write_bytes(body)
    m = (d / "manifest.yaml").read_text()
    old = hashlib.sha256((MINI / "tables.yaml").read_bytes()).hexdigest()
    (d / "manifest.yaml").write_text(m.replace(old, hashlib.sha256(body).hexdigest()))
    with pytest.raises(PackError, match="float"):
        load_pack(d)


def test_fingerprint(tmp_path: Path) -> None:
    assert load_pack(MINI).fingerprint == load_pack(MINI).fingerprint
    d = copy_pack(tmp_path)
    (d / "manifest.yaml").write_text((d / "manifest.yaml").read_text() + "\n")
    assert load_pack(d).fingerprint != load_pack(MINI).fingerprint


def test_option_defaults_and_override() -> None:
    pack = load_pack(MINI)
    assert resolve_options(pack, {}) == {"crits": "standard", "flanking": "off"}
    assert resolve_options(pack, {"crits": "max_dice"})["crits"] == "max_dice"


def test_bad_options() -> None:
    pack = load_pack(MINI)
    with pytest.raises(PackOptionError):
        resolve_options(pack, {"nope": "x"})
    with pytest.raises(PackOptionError):
        resolve_options(pack, {"crits": "bogus"})
