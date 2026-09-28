# Union CNC AI Brain — Project Specification

> Version: 12.0.0-fusion ("Industrial Fusion") · Author: timo.cao · 2026
> This document is the canonical English specification for the Union·由你 CNC AI Brain.

## 1. Overview

Union·由你 (Union CNC AI Brain) is an AI-driven CNC machining quoting and process
planning system. A user uploads a drawing (PDF / DWG / DXF / XLSX / ZIP) or describes
a part in natural language; the system automatically performs:

1. **Intent recognition** — MTClaw Function Router keyword pre-filter + LLM routing.
2. **3D generation** — Tree-of-Thought (TOT) three-pipeline competition; the winner
   produces a formal STEP/STL via OCC (fallback trimesh).
3. **Conflict detection** — DFM feasibility check (material × surface × tolerance ×
   heat-treatment forbidden matrix).
4. **Quoting** — 8 materials × 9 surface treatments, with precision / 5-axis /
   wire-EDM surcharges auto-calculated.
5. **One-click packaging** — STEP + STL + XLSX quote sheet + JSON spec → ZIP export.

**Design philosophy**: offline-first, multi-model adaptive, rule-engine fallback —
the system still runs with no network.

## 2. Architecture

The codebase lives under `src/` and is divided into six modules. The FastAPI entry
points are `app/main.py` (full) and `app/main_lite.py` (zero-AI offline).

```
src/
├── ai_engine/        # LLM abstraction layer
│   ├── engine.py             # AIEngine base + EngineError
│   ├── ollama_engine.py      # Local Ollama backend
│   └── openai_engine.py      # OpenAI-compatible cloud backend
├── core/             # Platform / model orchestration
│   ├── environment_detector.py  # ROCm / MUSA / Ollama auto-detect (rocm-smi)
│   ├── model_auto_loader.py     # Discover 12+ cloud APIs + local models
│   ├── model_registry.py        # Rank by quality_score
│   └── skill_auto_loader.py     # Tool/skill registration
├── neuro_core/       # Reasoning & expert orchestration
│   ├── serial_expert.py     # 5-expert serial meeting (process/material/quote/DFM/audit)
│   ├── conflict_check.py    # DFM conflict checker (forbidden matrix)
│   ├── schema_validator.py  # I/O schema validation
│   └── reasoning_chain.py   # SHA-256 audit chain
├── runtime/          # CAD / quote / packaging runtime
│   ├── step_generator.py        # Parametric STEP generators (OCC/trimesh)
│   ├── step_generator_dual.py   # TOT three-pipeline competition
│   ├── step_parser.py           # BBOX / volume / density extraction
│   ├── cad_pipeline_tot.py      # CAD pipeline orchestrator
│   ├── quote_adapter.py         # Quote engine (8 materials × 9 surfaces)
│   ├── quote_xlsx_generator.py  # XLSX quote sheet
│   ├── export_bundler.py        # ZIP bundler
│   ├── history_lookup.py        # SQLite history semantic match
│   ├── skill_caller.py          # Function-calling dispatcher
│   ├── progress_reporter.py     # Progress events
│   └── event_bus.py             # Internal event bus
├── data/             # RAG / persistence
│   └── rag_engine.py        # SQLite RAG for history reuse
└── safety/           # Audit & safety
    └── audit_logger.py      # Tamper-evident audit log
```

## 3. Capability Matrix

| Capability | Status | Evidence |
|------------|--------|----------|
| TOT three-pipeline competition | Implemented | `runtime/step_generator_dual.py` |
| 5-expert serial meeting | Implemented | `neuro_core/serial_expert.py` |
| SHA-256 audit chain | Implemented | `neuro_core/reasoning_chain.py` |
| DFM conflict detection | Implemented | `neuro_core/conflict_check.py` |
| Quote engine (8 mat × 9 surf) | Implemented | `runtime/quote_adapter.py` |
| STEP generation (OCC + trimesh) | Implemented | `runtime/step_generator.py` |
| One-click ZIP export | Implemented | `runtime/export_bundler.py` |
| Model auto-discovery | Implemented | `core/model_auto_loader.py` |
| ROCm native inference | Planned | Current backend: MUSA M1000; ROCm target below |
| 24+ material library | Planned | Current 8 materials (alias-normalized) |

## 4. API Overview

Full service listens on `:7862` (configurable). Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/` | Web UI (Three.js 3D preview) |
| GET  | `/api/health` | Health check |
| GET  | `/api/dashboard` | Dashboard metrics |
| GET  | `/api/status` | Mode / version / parts / materials / surfaces |
| GET  | `/api/version` | Version + codename |
| POST | `/api/generate-step` | TOT three-pipeline STEP generation |
| POST | `/api/quote` | Quote calculation |
| POST | `/api/cnc-quick` | Conflict + quote in one call (<50ms, rule-only) |
| POST | `/api/cnc-intent` | Intent recognition (for MTClaw FR) |
| POST | `/api/upload` | Multi-format parse (PDF/DWG/DXF/XLSX/ZIP) |
| POST | `/api/export` | ZIP bundle export |

## 5. Model Configuration

`config/models.json` declares all backends. Secrets are referenced via `${VAR}`
placeholders resolved from environment variables (see `.env.example`):

- `STEPFUN_API_KEY` — StepFun cloud API key.
- `OPC_API_KEY` — OPC industrial platform key.
- `SHADOW_MODE` — 1 = AI suggestions carry disclaimer + human confirm.

Models are ranked by `quality_score`; the auto-loader picks the highest available
backend at runtime (cloud → local Ollama → rule engine fallback).

## 6. ROCm Deployment

The current production inference backend is the **Moore Threads MUSA M1000**
(vLLM MUSA, ports 32102 / 8000 in `config/models.json`). The AMD ROCm target stack
is provided for AMD RYZEN AI MAX+ 395 + Radeon 8060S 64GB unified-memory hosts:

```bash
docker run --device=/dev/kfd --device=/dev/dri --group-add video \
  -p 8000:8000 union-cnc-ai-brain
```

The environment detector `src/core/environment_detector.py` auto-invokes `rocm-smi`
to detect ROCm devices and wires the runtime accordingly. See `Dockerfile` for the
ROCm 6.4 base image build.

## 7. Testing

Smoke tests live in `tests/test_smoke.py`:

```bash
python -m pytest tests/test_smoke.py -v
# or, without pytest:
python tests/test_smoke.py
```

## 8. License

MIT License © 2026 timo.cao. See `LICENSE` for the full text.