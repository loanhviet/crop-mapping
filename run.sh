#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.13 .venv
  else
    python3 -m venv .venv
  fi
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, torch, rasterio, pyproj, einops, yaml, PIL' >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python --index-strategy unsafe-best-match -r requirements.txt
  else
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi
exec .venv/bin/python -m uvicorn app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
