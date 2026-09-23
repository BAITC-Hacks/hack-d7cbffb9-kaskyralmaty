#!/usr/bin/env bash
set -euo pipefail
export LD_LIBRARY_PATH="$(.venv/bin/python -c 'import site; from pathlib import Path; print(":".join(str(p) for d in site.getsitepackages() for p in Path(d).glob("nvidia/*/lib")))'):${LD_LIBRARY_PATH:-}"
exec .venv/bin/python "$@"
