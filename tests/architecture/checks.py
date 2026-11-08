"""Чистые функции архитектурных проверок: исходный текст -> список нарушений."""

import ast
import re

MODEL_ID_PATTERN = re.compile(r"\b(?:claude-|gpt-|o[0-9]-)[\w.-]*")
STORE_ONLY_WEB = "aidm.store.player_view"


def rules_float_math(source: str) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            bad.append(f"line {node.lineno}: float literal")
        elif isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Div):
            left = node.left if isinstance(node, ast.BinOp) else node.target
            # shortcut: `/` слева от имени `*path*`/`*dir*` считается склейкой Path, не арифметикой
            if isinstance(left, ast.Name) and ("path" in left.id or "dir" in left.id):
                continue
            bad.append(f"line {node.lineno}: true division")
    return bad


def model_ids(text: str, known: set[str]) -> list[str]:
    found = set(MODEL_ID_PATTERN.findall(text))
    found |= {k for k in known if k in text}
    return sorted(found)


def _imported_modules(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.lineno, node.module))
            # `from aidm.store import x` тянет подмодуль x
            out += [(node.lineno, f"{node.module}.{a.name}") for a in node.names]
    return out


def sqlite3_imports(source: str) -> list[str]:
    return [
        f"line {n}: import {m}"
        for n, m in _imported_modules(ast.parse(source))
        if m == "sqlite3" or m.startswith("sqlite3.")
    ]


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else "?"


def sqlite_connect_args(source: str, allowed_attr: str) -> list[str]:
    """Первый аргумент sqlite3.connect: параметр-путь или `<x>.allowed_attr`, не литерал."""
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _dotted(node.func) == "sqlite3.connect"):
            continue
        arg = node.args[0] if node.args else None
        text = ast.unparse(arg) if arg is not None else ""
        if isinstance(arg, ast.Name) or allowed_attr in text:
            continue
        bad.append(f"line {node.lineno}: sqlite3.connect({text})")
    return bad


def attr_uses(source: str, attr: str) -> list[str]:
    return [
        f"line {n.lineno}: .{attr}"
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Attribute) and n.attr == attr
    ]


def web_store_imports(source: str) -> list[str]:
    return [
        f"line {n}: import {m}"
        for n, m in _imported_modules(ast.parse(source))
        if m.startswith("aidm.store.") and not m.startswith(STORE_ONLY_WEB)
    ]
