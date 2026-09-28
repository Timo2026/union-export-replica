"""services.spark_writer — v5.0.0 SparkSkillsHub dashboard 实时注入.

职责:
  - 每次 dispatch 完成后 append_context(dispatch_id, ctx) 写 spark-output/context/*.json
  - update_dashboard() 增量合并所有 done=true 的 context → 重新生成 dashboard.html
  - 提供 get_state() 给 GET /v1/spark/dashboard API
  - atomic write (临时文件 + rename)

模板: spark-output/dashboard.html (已通过验收 v3.0.2)
  占位符: /*__SPARK_STATE_INJECT__*/null
  STATE 形态:
    {
      "project": "...",
      "description": "...",
      "generated_at": "ISO8601",
      "contexts": { "<dispatch_id>": {done, summary, fields} }
    }

铁律:
  - 不阻塞主链 (dispatch 后台写, 失败 log 不抛)
  - spark-output 在 .gitignore (本地产物)
  - 模板破坏时不静默 (返 None)
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# dashboard.html 模板占位符 (从 spark-output/dashboard.html 抽取)
TEMPLATE_PLACEHOLDER = "/*__SPARK_STATE_INJECT__*/null"

# 模板搜索路径优先级
TEMPLATE_PATHS = [
    Path("spark-output") / "dashboard.html",
    Path("docs") / "spark-output" / "dashboard.html",
]


def find_template(root: Optional[Path] = None) -> Optional[Path]:
    """查找 dashboard.html 模板.

    优先级:
      1. root / spark-output/dashboard.html (显式传入)
      2. root / docs/spark-output/dashboard.html (备选)
      3. cwd / spark-output/dashboard.html (项目根, 仅 root 未传时)
      4. services/parent / spark-output/dashboard.html (兜底)

    注: 测试场景必须传 root 避免 fallback 到项目根污染.
    """
    if root is not None:
        for rel in TEMPLATE_PATHS:
            p = root / rel
            if p.exists():
                return p
        return None
    # 无 root: 找项目根
    for rel in TEMPLATE_PATHS:
        p = Path(".") / rel
        if p.exists():
            return p
    return None


def read_template(root: Optional[Path] = None) -> Optional[str]:
    """读 dashboard.html 模板原文."""
    p = find_template(root)
    if p is None:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        log.warning("[spark_writer] read template failed: %r", e)
        return None


def get_context_dir(root: Optional[Path] = None) -> Path:
    """spark-output/context/ 目录."""
    base = Path(root) if root else Path(".")
    d = base / "spark-output" / "context"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_dashboard_path(root: Optional[Path] = None) -> Path:
    """dashboard.html 输出路径."""
    base = Path(root) if root else Path(".")
    return base / "spark-output" / "dashboard.html"


def append_context(dispatch_id: str, ctx: Dict[str, Any],
                   root: Optional[Path] = None) -> Path:
    """写单个 dispatch context 到 spark-output/context/{dispatch_id}.json."""
    d = get_context_dir(root)
    p = d / f"{dispatch_id}.json"
    payload = {
        "dispatch_id": dispatch_id,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **ctx,
    }
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
        log.debug("[spark_writer] wrote context %s", dispatch_id)
        return p
    except Exception as e:
        log.warning("[spark_writer] write context %s failed: %r", dispatch_id, e)
        if tmp.exists():
            try: tmp.unlink()
            except Exception: pass
        return p  # 返路径, 让调用者知道


def list_contexts(root: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """读 spark-output/context/*.json 全部."""
    out: Dict[str, Dict[str, Any]] = {}
    d = get_context_dir(root)
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            did = data.get("dispatch_id") or p.stem
            out[did] = data
        except Exception:
            continue
    return out


def build_state(root: Optional[Path] = None,
                project: str = "Union Export Agent Workbench v5.0.0",
                description: str = "L3 邮件自动驱动 · 18 skills · 自动化率 100% (PASS 路径)",
                ) -> Dict[str, Any]:
    """合并 contexts → STATE."""
    contexts = list_contexts(root)
    # 只保留 done=true 的 (或 done 字段不存在 — 兼容)
    done_contexts = {
        k: {"done": True, "summary": v.get("summary", ""),
            "fields": v.get("fields", {})}
        for k, v in contexts.items()
        if v.get("done", True)
    }
    return {
        "project": project,
        "description": description,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "contexts": done_contexts,
    }


def update_dashboard(root: Optional[Path] = None) -> bool:
    """合并 contexts → 渲染 dashboard.html → atomic write."""
    template = read_template(root)
    if template is None:
        log.warning("[spark_writer] 模板未找到, 跳过 dashboard 写入")
        return False
    if TEMPLATE_PLACEHOLDER not in template:
        log.warning("[spark_writer] 模板缺占位符 %s", TEMPLATE_PLACEHOLDER)
        return False
    state = build_state(root)
    state_json = json.dumps(state, ensure_ascii=False)
    rendered = template.replace(TEMPLATE_PLACEHOLDER, state_json)
    out = get_dashboard_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".html.tmp")
    try:
        tmp.write_text(rendered, encoding="utf-8")
        os.replace(tmp, out)
        log.info("[spark_writer] dashboard updated: %s (%d contexts)", out, len(state["contexts"]))
        return True
    except Exception as e:
        log.warning("[spark_writer] write dashboard failed: %r", e)
        if tmp.exists():
            try: tmp.unlink()
            except Exception: pass
        return False


def ingest_audit_line(audit_line: Dict[str, Any],
                      root: Optional[Path] = None) -> Optional[Path]:
    """从 data/skill_audit.jsonl 单行 → spark context.

    简化版: 仅取 event / consumer / payload.verdict 字段, 其它忽略.
    """
    dispatch_id = audit_line.get("dispatch_id") or audit_line.get("payload", {}).get("dispatch_id")
    if not dispatch_id:
        return None
    ctx = {
        "done": True,
        "summary": f"{audit_line.get('event', 'unknown')} · {audit_line.get('consumer', '?')}",
        "fields": audit_line.get("payload", {}),
    }
    return append_context(dispatch_id, ctx, root)


def get_state(root: Optional[Path] = None) -> Dict[str, Any]:
    """返当前 STATE (给 GET /v1/spark/dashboard)."""
    return build_state(root)
