---
name: union-export
description: |
  Use when the user asks to quote, price, or process an export manufacturing RFQ
  (CNC / STEP / sheet-metal parts), run a deterministic quotation, check an order
  for conflicts or DFM feasibility, or drive the union-export agent pipeline.
  This skill is a thin bridge: it forwards the request to the local union-export
  livekernel, which performs deterministic, sha256-locked pricing. Iron-rule-1:
  the LLM never emits the final price - it is always computed by the deterministic
  kernel and sha-verified.
license: Apache-2.0
allowed-tools: Read Bash(curl *)
compatibility: |
  Requires the union-export livekernel HTTP service running on the local node
  (default http://127.0.0.1:8888; override with env UEA_LIVEKERNEL_URL) and curl.
  No credentials are needed - the livekernel is loopback-only on the node.
metadata:
  version: "6.3.2"
  author: "Union Export Agent"
  tags:
    - union-export
    - manufacturing
    - quotation
    - rfq
    - cnc
    - bridge
---

# union-export

Thin bridge from OpenClaw to the local **union-export livekernel** (v6.3.2). The
livekernel owns all business logic: intent routing, deterministic quotation via
the Timo CNC engine, conflict checking, iron-rule-1 sha256 locking, and
draft-only reply generation. This skill does NOT compute prices - it forwards the
request and relays the verified result.

## When to use

- The user wants a price / quotation for a manufactured part (CNC, STEP, sheet metal).
- The user pastes an RFQ (request for quotation) email or text and asks to process it.
- The user asks to check an order for conflicts, feasibility (DFM), or margin.
- The user asks to draft (never auto-send) a quotation reply.

Do NOT use this skill to compute a price yourself. Always forward to the
livekernel; iron-rule-1 forbids LLM-authored final prices.

## Prerequisites

- livekernel reachable at `${UEA_LIVEKERNEL_URL:-http://127.0.0.1:8888}`.
- `curl` available.

## Instructions

Set the base URL once:

    BASE="${UEA_LIVEKERNEL_URL:-http://127.0.0.1:8888}"

1. Health check - confirm the livekernel and the deterministic engine are live:

       curl -s "$BASE/health"

   Expect `"status":"ok"` and `"engine":"live:cnc-ai-brain:..."`. A `mock:` engine
   means the deterministic kernel is down - tell the user quoting is unavailable
   rather than guessing a number.

2. Forward the request. Put the user's full request text in `intent` and set
   `driver` to `agent`. Optionally add structured fields (`material`, `quantity`,
   `surface`, `tolerance_grade`, `destination_country`, `incoterm`,
   `shipping_mode`, `customer`); the livekernel merges them into its args:

       curl -s -X POST "$BASE/v1/agent/task" \
         -H "Content-Type: application/json" \
         -d '{"intent":"<USER REQUEST TEXT>","driver":"agent"}'

   For an explicit structured quote you may send the fields directly:

       -d '{"intent":"quote","driver":"agent","material":"6061","quantity":100,"surface":"anodized","tolerance_grade":"IT7"}'

   A file-backed RFQ (e.g. a STEP path) may be passed via `"files":["<path>"]`.

3. Relay the result. Read the JSON response and report these verified fields:

   - `result.final_price` and `result.quote.unit_price` - the deterministic price.
   - `result.quote._source` (expect `live:/api/quote`) and `result._source`
     (expect `live:cnc-ai-brain:<port>`) - proves the price came from the
     deterministic engine, not the LLM.
   - `result.iron_rule` (expect `deterministic`), `result.state` (expect `DONE`),
     `result.verification_status` (expect `PASS`), `result.dfm_valid`.
   - `route.model` and `route.source` - which model planned the route.
   - `executed_skills` - the skills that ran.
   - `iron_rule_override_blocked.allowed` - the iron-rule-1 guard. `false` means
     an attempt to rewrite the deterministic output was BLOCKED. That is the
     guarantee working, not an error. The matching `expected_sha256` is locked in
     `trace[].output_sha256`.
   - `result.reply.mode` (expect `draft_only`) and `result.reply.auto_send`
     (expect `false`) - replies are drafts; nothing is auto-sent.
   - `hitl_required` / `hitl_reasons` - whether a human must approve.

## Output format

Report a short summary: final price and unit price, lead time, the provenance
(`_source`), the iron-rule status (deterministic + sha256 lock + override
blocked), verification / DFM status, and whether HITL approval or a draft-only
reply is pending. Never restate the price as your own computation - attribute it
to the deterministic engine.

## Iron-rule-1 guarantees (do not violate)

- The final price is ALWAYS computed by the deterministic Timo kernel and locked
  by sha256 (`trace[].output_sha256`). The LLM only plans/routes and drafts text.
- Any attempt to override the deterministic output is blocked
  (`iron_rule_override_blocked.allowed:false`).
- Outbound replies are `draft_only` with `auto_send:false` - no email or other
  egress is ever sent automatically.
- If the engine reports `mock:` or the sha guard fails, surface that honestly;
  do not fabricate a price.
