#!/usr/bin/env bash
# Проверка как в CI: чистая копия коммита и зависимости строго по uv.lock, поэтому ловит и незакоммиченные файлы
set -euo pipefail
root=$(git rev-parse --show-toplevel)
ref=${PRE_COMMIT_TO_REF:-${1:-HEAD}}
tmp=$(mktemp -d)
trap 'git -C "$root" worktree remove --force "$tmp" >/dev/null 2>&1; rm -rf "$tmp"' EXIT
git -C "$root" worktree add --detach --quiet "$tmp" "$ref"
cd "$tmp"
uv sync --locked --quiet
uv run ruff check
uv run ruff format --check
uv run mypy src
uv run lint-imports
uv run pytest -q
