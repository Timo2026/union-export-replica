"""tests/test_queue_hardening.py — D-P0.4 文件态队列加固.

覆盖:
  1. fail_with_retry: 每次失败 attempts+1, 未超限 → 重回 NEW
  2. fail_with_retry: 达到 max_attempts → DEAD (死信), 不再重回 NEW
  3. reclaim_stale: PROCESSING 租约超时 → 重新可认领 (NEW)
  4. reclaim_stale: 未超时的 PROCESSING 不动
  5. claim_batch: max_per_cycle 上限生效
  6. 向后兼容: 旧 pending 行 (无 attempts 字段) from_dict 默认 attempts=0
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from services.mail_puller import (
    MailPuller,
    PendingEntry,
    STATE_DEAD,
    STATE_NEW,
    STATE_PROCESSING,
)


def _puller(tmp_root: Path, **kw) -> MailPuller:
    return MailPuller(root=tmp_root, interval_s=0.5, limit=10, **kw)


def _seed(puller: MailPuller, mail_id: str, **kw) -> None:
    puller._append_pending([PendingEntry(mail_id=mail_id, **kw)])


# ---- 1. 失败重试: attempts+1, 重回 NEW ----
def test_fail_with_retry_requeues_below_cap(tmp_root: Path) -> None:
    p = _puller(tmp_root)
    _seed(p, "M-1", state=STATE_PROCESSING, started_at=time.time())
    new_state = p.fail_with_retry("M-1", error="boom", max_attempts=3)
    assert new_state == STATE_NEW
    entries = {e.mail_id: e for e in p._read_pending()}
    assert entries["M-1"].attempts == 1
    assert entries["M-1"].error == "boom"


# ---- 2. 达到上限 → DEAD ----
def test_fail_with_retry_dead_at_cap(tmp_root: Path) -> None:
    p = _puller(tmp_root)
    _seed(p, "M-2", state=STATE_PROCESSING, started_at=time.time())
    # 前 2 次重回 NEW
    assert p.fail_with_retry("M-2", error="e1", max_attempts=3) == STATE_NEW
    p.mark_state("M-2", STATE_PROCESSING)
    assert p.fail_with_retry("M-2", error="e2", max_attempts=3) == STATE_NEW
    p.mark_state("M-2", STATE_PROCESSING)
    # 第 3 次 → DEAD
    final = p.fail_with_retry("M-2", error="e3", max_attempts=3)
    assert final == STATE_DEAD
    entries = {e.mail_id: e for e in p._read_pending()}
    assert entries["M-2"].attempts == 3
    assert entries["M-2"].state == STATE_DEAD
    assert entries["M-2"].finished_at is not None


# ---- 3. 租约超时回收 ----
def test_reclaim_stale_releases_expired_lease(tmp_root: Path) -> None:
    p = _puller(tmp_root)
    # started_at 远在过去 (超过 lease)
    _seed(p, "M-STALE", state=STATE_PROCESSING, started_at=time.time() - 1000)
    reclaimed = p.reclaim_stale(lease_timeout_s=300)
    assert "M-STALE" in reclaimed
    entries = {e.mail_id: e for e in p._read_pending()}
    assert entries["M-STALE"].state == STATE_NEW


# ---- 4. 未超时 PROCESSING 不动 ----
def test_reclaim_stale_keeps_fresh_lease(tmp_root: Path) -> None:
    p = _puller(tmp_root)
    _seed(p, "M-FRESH", state=STATE_PROCESSING, started_at=time.time())
    reclaimed = p.reclaim_stale(lease_timeout_s=300)
    assert "M-FRESH" not in reclaimed
    entries = {e.mail_id: e for e in p._read_pending()}
    assert entries["M-FRESH"].state == STATE_PROCESSING


# ---- 5. claim_batch max_per_cycle 上限 ----
def test_claim_batch_respects_max_per_cycle(tmp_root: Path) -> None:
    p = _puller(tmp_root, max_per_cycle=2)
    for i in range(5):
        _seed(p, f"M-{i}", state=STATE_NEW)
    claimed = p.claim_batch(consumer="orchestrator")
    assert len(claimed) == 2
    assert all(e.state == STATE_PROCESSING for e in claimed)
    # 剩余 3 个仍 NEW
    assert len(p.list_by_state(STATE_NEW)) == 3


# ---- 6. 向后兼容: 旧行无 attempts ----
def test_from_dict_defaults_attempts_zero(tmp_root: Path) -> None:
    p = _puller(tmp_root)
    # 手写一条旧格式行 (无 attempts 字段)
    p.puller_dir.mkdir(parents=True, exist_ok=True)
    legacy = {"mail_id": "M-LEGACY", "state": STATE_NEW, "queued_at": time.time()}
    with p.pending_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(legacy) + "\n")
    entries = {e.mail_id: e for e in p._read_pending()}
    assert entries["M-LEGACY"].attempts == 0
