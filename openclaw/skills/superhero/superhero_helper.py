#!/usr/bin/env python3
"""Superhero skill helper (registered on spark-388d profile).

Pipeline:
  1. Upload face photo to ComfyUI's input folder.
  2. Patch face_workflow.json with the uploaded filename and a random seed.
  3. Submit the workflow to ComfyUI's HTTP API.
  4. Poll /api/history until completion and locate the output image.
  5. Publish the result into OpenClaw's workspace boundary.
  6. Print `MEDIA:<absolute_path>` so the OpenClaw web UI renders it inline.

Layout (this profile):
  /home/Developer/.openclaw/skills/superhero/superhero_helper.py
  → OPENCLAW_HOME (profile/config dir) = parents[1] of this file
  → skill dir = parents[0]

Environment overrides (all optional):
  OPENCLAW_HOME   — profile dir; default: parents[1] of this script
  WORKSHOP_DIR    — bundle root (where comfyui-app/ lives); default: OPENCLAW_HOME
  COMFYUI_URL     — default http://127.0.0.1:8200
  COMFYUI_OUTPUT  — ComfyUI output dir; default $WORKSHOP_DIR/comfyui-app/ComfyUI/output
  OLLAMA_URL      — default http://127.0.0.1:11434 (used to unload LLMs before generation)
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

import requests

# Layout-independent resolution. In this profile the skill lives at
#   <config-dir>/skills/superhero/superhero_helper.py
# so one parent up is the skill dir, two up is the config dir (OPENCLAW_HOME).
_SKILL_DIR = Path(__file__).resolve().parent
OPENCLAW_HOME = Path(
    os.environ.get("OPENCLAW_HOME", _SKILL_DIR.parents[1])
).resolve()

WORKSHOP_DIR = Path(
    os.environ.get("WORKSHOP_DIR", OPENCLAW_HOME)
).resolve()

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8200")
COMFYUI_OUTPUT = Path(
    os.environ.get("COMFYUI_OUTPUT", WORKSHOP_DIR / "comfyui-app" / "ComfyUI" / "output")
)
WORKFLOW_FILE = _SKILL_DIR / "face_workflow.json"

# Where ComfyUI output files are republished so OpenClaw's media boundary
# accepts them. Must be an ABSOLUTE path inside the OpenClaw workspace.
PUBLISH_DIR = OPENCLAW_HOME / "workspace" / "outputs"


def log(msg: str) -> None:
    print(f"[superhero] {msg}", file=sys.stderr, flush=True)


def upload_image(path: str) -> str:
    fname = Path(path).name
    with open(path, "rb") as fh:
        resp = requests.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (fname, fh, "image/png")},
            data={"overwrite": "true"},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json().get("name", fname)


def unload_ollama_models() -> None:
    """Tell Ollama to drop any loaded LLMs from GPU memory.

    DGX Spark uses unified memory, so a 23 GB Qwen3.6 sitting in GPU memory
    starves ComfyUI's VAE decode and can deadlock. We explicitly request unload
    before kicking off generation. Best-effort — ignore failures.
    """
    ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        # Empty-prompt + keep_alive=0 means "unload now"
        for model in ("qwen3.6:35b",):
            requests.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=10,
            )
        log("ollama models unloaded (free GPU memory for ComfyUI)")
    except Exception as e:
        log(f"ollama unload skipped: {e}")


def submit_prompt(workflow: dict) -> str:
    resp = requests.post(
        f"{COMFYUI_URL}/api/prompt", json={"prompt": workflow}, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return data["prompt_id"]


def wait_for_completion(prompt_id: str, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        try:
            resp = requests.get(
                f"{COMFYUI_URL}/api/history/{prompt_id}", timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue
        if prompt_id not in data:
            continue
        entry = data[prompt_id]
        status = entry.get("status", {})
        if status.get("completed") or status.get("status_str") == "success":
            return entry.get("outputs", {})
        for msg in status.get("messages", []):
            if isinstance(msg, list) and msg[0] == "execution_error":
                raise RuntimeError(f"ComfyUI error: {msg[1]}")
    raise TimeoutError(f"Prompt {prompt_id} did not finish within {timeout}s")


def extract_first_image(outputs: dict) -> Path:
    for node_out in outputs.values():
        for img in node_out.get("images", []) or []:
            sub = img.get("subfolder") or ""
            fname = img.get("filename") or ""
            if not fname:
                continue
            return COMFYUI_OUTPUT / sub / fname if sub else COMFYUI_OUTPUT / fname
    raise RuntimeError("No output image in ComfyUI history")


def publish_for_openclaw(src: Path) -> Path:
    """Hardlink (or copy) the ComfyUI output into the OpenClaw media boundary.

    OpenClaw's `assertLocalMediaAllowed()` resolves paths via fs.realpath and
    rejects anything outside the configured workspace/media roots. ComfyUI's
    output dir lives outside that boundary, so we republish into
    `$OPENCLAW_HOME/workspace/outputs/` and return the new absolute path.
    """
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    dst = (PUBLISH_DIR / src.name).resolve()
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)        # cheap hardlink when on same filesystem
    except OSError:
        shutil.copy2(src, dst)   # fallback if cross-fs
    return dst


def latest_inbound_image() -> Path | None:
    """Find the most recently uploaded image in OpenClaw's inbound boundary.

    OpenClaw stores user-attached images under `$OPENCLAW_HOME/media/inbound/`.
    The agent rarely knows this path verbatim, so we fall back to "newest file
    in inbound" when the caller did not supply a usable path.
    """
    inbound = OPENCLAW_HOME / "media" / "inbound"
    if not inbound.is_dir():
        return None
    candidates = [
        p for p in inbound.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> int:
    image_path: str | None = sys.argv[1] if len(sys.argv) >= 2 else None

    if not image_path or not Path(image_path).is_file():
        if image_path:
            log(f"argument {image_path!r} is not a file — falling back to inbound/")
        else:
            log("no argument supplied — using latest inbound image")
        latest = latest_inbound_image()
        if latest is None:
            print(
                "ERROR: no face image given and inbound/ is empty. "
                "Ask the user to attach a portrait photo.",
                file=sys.stderr,
            )
            return 1
        image_path = str(latest)
        log(f"resolved face image -> {image_path}")

    workflow = json.loads(WORKFLOW_FILE.read_text(encoding="utf-8"))

    log(f"OPENCLAW_HOME = {OPENCLAW_HOME}")
    log(f"WORKSHOP_DIR  = {WORKSHOP_DIR}")
    log(f"COMFYUI_URL   = {COMFYUI_URL}")

    # GPU/unified memory hygiene: free Ollama's LLM before ComfyUI claims VRAM
    unload_ollama_models()

    log(f"uploading {image_path}")
    workflow["5"]["inputs"]["image"] = upload_image(image_path)
    workflow["11"]["inputs"]["seed"] = random.randint(1, 2**32)

    log("submitting workflow…")
    prompt_id = submit_prompt(workflow)
    log(f"prompt_id = {prompt_id}, waiting (~1 min)")

    outputs = wait_for_completion(prompt_id, timeout=600)
    src = extract_first_image(outputs)
    media = publish_for_openclaw(src)

    log(f"done: {media}")
    print(f"MEDIA:{media}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
