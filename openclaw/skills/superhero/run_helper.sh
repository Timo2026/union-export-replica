#!/usr/bin/env bash
# Entry script invoked by OpenClaw. Resolves the OpenClaw profile dir from its
# own location, picks a Python environment with `requests`, and runs the helper.
#
# Layout (this profile):
#   /home/Developer/.openclaw/skills/superhero/run_helper.sh
#   → OPENCLAW_HOME = <script_dir>/../..  (= /home/Developer/.openclaw)
#
# venv selection order:
#   1. $COMFYUI_VENV (explicit override)
#   2. $WORKSHOP_DIR/comfyui-app/comfyui-env (workshop bundle layout)
#   3. system python3 if it already has `requests`
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPENCLAW_HOME="$(cd "$SCRIPT_DIR/../.." && pwd)"
export OPENCLAW_HOME
export WORKSHOP_DIR="${WORKSHOP_DIR:-$OPENCLAW_HOME}"
export COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:${COMFYUI_PORT:-8200}}"
export HF_HOME="${HF_HOME:-$WORKSHOP_DIR/hf-cache}"

VENV="${COMFYUI_VENV:-}"
if [ -z "$VENV" ] && [ -f "$WORKSHOP_DIR/comfyui-app/comfyui-env/bin/activate" ]; then
    VENV="$WORKSHOP_DIR/comfyui-app/comfyui-env"
fi

if [ -n "$VENV" ] && [ -f "$VENV/bin/activate" ]; then
    cd "$WORKSHOP_DIR/comfyui-app" 2>/dev/null || cd "$WORKSHOP_DIR"
    # shellcheck source=/dev/null
    source "$VENV/bin/activate"
elif ! python3 -c "import requests" 2>/dev/null; then
    echo "ERROR: no usable Python env with 'requests'." >&2
    echo "Set COMFYUI_VENV to a venv that has requests (e.g. the ComfyUI bundle venv)," >&2
    echo "or install requests for system python3." >&2
    exit 1
fi

exec python3 "$SCRIPT_DIR/superhero_helper.py" "$@"
