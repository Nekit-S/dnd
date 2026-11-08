import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class PackError(Exception):
    pass


class PackOptionError(PackError):
    pass


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FileRef(_Frozen):
    path: str
    sha256: str


class OptionSpec(_Frozen):
    allowed: tuple[str, ...]
    default: str


class Manifest(_Frozen):
    id: str
    version: str
    title: str
    license: str
    attribution: str
    rounding: Literal["down", "up"]
    files: dict[str, FileRef]
    options: dict[str, OptionSpec] = {}


class RulePack(_Frozen):
    manifest: Manifest
    fingerprint: str
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def rounding(self) -> Literal["down", "up"]:
        return self.manifest.rounding


def _reject_floats(node: Any, where: str) -> None:
    if isinstance(node, float):
        raise PackError(f"float {node} in {where}: use an int or a string like '1/8'")
    if isinstance(node, dict):
        for v in node.values():
            _reject_floats(v, where)
    elif isinstance(node, list):
        for v in node:
            _reject_floats(v, where)


def load_pack(path: Path) -> RulePack:
    raw = path.joinpath("manifest.yaml").read_bytes()
    try:
        manifest = Manifest.model_validate(yaml.safe_load(raw))
    except (ValidationError, yaml.YAMLError) as e:
        raise PackError(f"bad manifest in {path}: {e}") from e
    data: dict[str, Any] = {}
    for name, ref in manifest.files.items():
        f = path.joinpath(ref.path)
        if not f.is_file():
            raise PackError(f"missing file {ref.path}")
        body = f.read_bytes()
        if hashlib.sha256(body).hexdigest() != ref.sha256:
            raise PackError(f"checksum mismatch in {ref.path}")
        data[name] = yaml.safe_load(body)
        _reject_floats(data[name], ref.path)
    return RulePack(manifest=manifest, fingerprint=hashlib.sha256(raw).hexdigest(), data=data)


def resolve_options(pack: RulePack, choices: dict[str, str]) -> dict[str, str]:
    specs = pack.manifest.options
    for name, value in choices.items():
        if name not in specs:
            raise PackOptionError(f"unknown option {name}")
        if value not in specs[name].allowed:
            raise PackOptionError(f"value {value!r} not allowed for option {name}")
    return {n: choices.get(n, s.default) for n, s in specs.items()}
