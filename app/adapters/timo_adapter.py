"""TimoAdapter — 对接真实制造决策内核 cnc-ai-brain v12.0.0-fusion.

接线策略 (用户确认: 在线优先, 离线兜底, 两者都要):
  1. ONLINE  : 命中真实 FastAPI :7862 (/api/health /api/conflict-check /api/quote /api/cnc-quick)
  2. OFFLINE : 通过子进程调用引擎自带 .venv python, 直接 import 真实
               src.neuro_core.conflict_check.ConflictChecker + app.main_lite.calc_quote
               —— byte-identical 真实内核, 绝不使用示意系数。

设计原则 (对齐冻结 PRD "Replace the adapters, not the architecture"):
  - LLM 不生成最终数字; 报价/冲突全部来自确定性引擎。
  - 每个结果标注 _source, 离线/在线可区分, 不冒充。
  - 只用 stdlib (urllib/subprocess/json), 不引入 requests/httpx 依赖。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from services.resilience import Resilient, urlopen_json
    _HAS_RESILIENCE = True
except Exception:                      # 独立运行(无 trunk 根 on path)时降级为直连
    _HAS_RESILIENCE = False

_HERE = Path(__file__).resolve().parent
_BRIDGE = _HERE / "_kernel_bridge.py"


class TimoAdapter:
    def __init__(self, cfg: Dict[str, Any]):
        t = cfg.get("timo", cfg)
        self.base_url: str = str(t.get("base_url", "http://127.0.0.1:7862")).rstrip("/")
        self.timeout: int = int(t.get("timeout_s", 25))
        self.health_timeout: int = int(t.get("health_timeout_s", 4))
        # 节点部署 (DGX Spark): 环境变量覆盖 settings.yaml 的 Windows 路径,
        # 免改配置即可把离线内核指向节点上的引擎 venv / OCC 环境.
        self.engine_src: str = str(os.environ.get("CNC_BRAIN_SRC") or t.get("engine_src", ""))
        self.engine_python: str = str(os.environ.get("CNC_BRAIN_PY") or t.get("engine_python", ""))
        self.allow_fallback: bool = bool(t.get("allow_fallback", True))
        self._online: Optional[bool] = None
        # P1 容错: 指数退避重试 + 熔断器 (失败累积→OPEN→直接走离线内核)
        self._rt = Resilient(timeout=self.timeout, max_retries=int(t.get("max_retries", 2)),
                             backoff=float(t.get("backoff_s", 0.2)), fail_threshold=3,
                             reset_after=float(t.get("circuit_reset_s", 20))) if _HAS_RESILIENCE else None

    # ---------------- online probe ----------------
    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/health", timeout=self.health_timeout) as r:
                self._online = r.status == 200
        except Exception:
            self._online = False
        return bool(self._online)

    @property
    def online(self) -> bool:
        if self._online is None:
            self.health()
        return bool(self._online)

    @property
    def kernel_available(self) -> bool:
        """离线内核是否真的在本机 (settings.yaml 可能还是 Windows 路径)."""
        return bool(self.engine_src and os.path.exists(self.engine_src))

    def source_label(self) -> str:
        """真实来源标注.

        引擎缺席时绝不再返回 "vendored-kernel(byte-identical)" ——
        那会让下游把未经验证的路径当成确定性内核结果。
        """
        if self.online:
            return "live:cnc-ai-brain:7862"
        if self.kernel_available:
            return "offline:vendored-kernel(byte-identical)"
        return "offline:kernel-absent(UNVERIFIED)"

    # ---------------- HTTP helper ----------------
    def _post(self, path: str, payload: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}{path}"
        to = timeout or self.timeout

        def _do() -> Dict[str, Any]:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
            with urllib.request.urlopen(req, timeout=to) as r:
                return json.loads(r.read().decode("utf-8"))

        if self._rt is not None:
            import socket
            # 只对瞬时网络错误重试+熔断; HTTP 4xx/5xx(HTTPError) 视为业务错误 fail-fast
            return self._rt.call(_do, name=f"timo{path}",
                                 retry_on=(urllib.error.URLError, socket.timeout, TimeoutError,
                                           ConnectionError, OSError))
        return _do()

    # ---------------- offline bridge (subprocess, real engine venv) ----------------
    def _offline(self, func: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if not (self.engine_src and os.path.exists(self.engine_src)):
            raise RuntimeError(f"engine_src not found: {self.engine_src}")
        py = self.engine_python if (self.engine_python and os.path.exists(self.engine_python)) else sys.executable
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = self.engine_src + os.pathsep + env.get("PYTHONPATH", "")
        req = json.dumps({"func": func, "args": args}, ensure_ascii=False)
        proc = subprocess.run(
            [py, str(_BRIDGE)], input=req.encode("utf-8"),
            capture_output=True, timeout=self.timeout + 30, env=env, cwd=self.engine_src,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"kernel bridge failed: {proc.stderr.decode('utf-8', 'ignore')[-500:]}")
        out = proc.stdout.decode("utf-8", "ignore").strip()
        line = [l for l in out.splitlines() if l.strip().startswith("{")][-1]
        return json.loads(line)

    # ---------------- public API ----------------
    def conflict_check(self, material: str, surface: str, tolerance_grade: str = "") -> Dict[str, Any]:
        """DFM 工艺冲突检测 (辟). 在线优先, 离线兜底, 结果 byte-identical."""
        if self.online:
            try:
                j = self._post("/api/conflict-check",
                               {"material": material, "surface_treatment": surface or "无"})
                j["_source"] = "live:/api/conflict-check"
                return self._norm_conflict(j)
            except Exception:
                if not self.allow_fallback:
                    raise
        j = self._offline("conflict_check", {"material": material, "surface": surface or "无"})
        j["_source"] = "offline:ConflictChecker"
        return self._norm_conflict(j)

    def quote(self, rfq: Dict[str, Any],
              dynamic_adjustments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """确定性报价. 在线 /api/quote (结构化参数), 离线 calc_quote.

        v6.1 飞轮层 (T6.10): 可选 dynamic_adjustments 注入客户级偏好偏移.
          {bias_pct: float, confidence: float, source: str}
          作为参数传给 Timo, Timo 内部决定是否应用.
          不修改 Timo calc_quote 内部确定性逻辑.
        """
        params = self._rfq_to_params(rfq)
        # 飞轮调整作为元数据, 不参与 Timo 数字计算 (铁律①保持)
        if dynamic_adjustments:
            params["_flywheel_bias_pct"] = float(
                dynamic_adjustments.get("bias_pct", 0.0))
            params["_flywheel_bias_confidence"] = float(
                dynamic_adjustments.get("confidence", 0.0))
            params["_flywheel_bias_source"] = str(
                dynamic_adjustments.get("source", "flywheel"))
        if self.online:
            try:
                j = self._post("/api/quote", params)
                j["_source"] = "live:/api/quote"
                if dynamic_adjustments:
                    j["_flywheel_applied"] = True
                return j
            except Exception:
                if not self.allow_fallback:
                    raise
        j = self._offline("calc_quote", params)
        j["_source"] = "offline:calc_quote"
        if dynamic_adjustments:
            j["_flywheel_applied"] = True
        return j

    def quick(self, message: str) -> Dict[str, Any]:
        """在线 /api/cnc-quick 一体化通道 (仅在线可用, 供 demo/对比)."""
        j = self._post("/api/cnc-quick", {"message": message})
        j["_source"] = "live:/api/cnc-quick"
        return j

    # ---------------- STEP 几何 (真实 OCP, 走引擎 .venv) ----------------
    def step_geometry(self, path: str, material: str = "6061") -> Dict[str, Any]:
        """真实 OCP B-rep: bbox + 体积 + 按密度算重量 → 几何驱动报价."""
        j = self._offline("step_geometry", {"path": path, "material": material})
        j["_source"] = "engine:step_parser(OCP B-rep)"
        return j

    def step_features(self, path: str) -> Dict[str, Any]:
        """C1 特征实测 (孔/壁厚/圆角); 大文件可能 partial, 失败不抛."""
        j = self._offline("step_features", {"path": path})
        j["_source"] = "engine:feature_extractor(C1)"
        return j

    # ---------------- helpers ----------------
    @staticmethod
    def _norm_conflict(j: Dict[str, Any]) -> Dict[str, Any]:
        conflicts = j.get("conflicts", []) or []
        warnings = j.get("warnings", []) or []
        valid = j.get("valid", len(conflicts) == 0)
        return {
            "valid": bool(valid),
            "conflicts": conflicts,
            "warnings": warnings,
            "total_issues": j.get("total_issues", len(conflicts) + len(warnings)),
            "_source": j.get("_source", "unknown"),
            "_raw": j,
        }

    @staticmethod
    def _rfq_to_params(rfq: Dict[str, Any]) -> Dict[str, Any]:
        """把 canonical RFQ 映射到引擎 calc_quote / /api/quote 参数名."""
        dims = rfq.get("dimensions_mm") or []
        dims = (list(dims) + [0, 0, 0])[:3]
        p = {
            "material": rfq.get("material", "6061"),
            "surface": rfq.get("surface") or rfq.get("surface_treatment") or "无",
            "surface_treatment": rfq.get("surface") or rfq.get("surface_treatment") or "无",
            "quantity": int(rfq.get("quantity", 1) or 1),
            "weight_kg": float(rfq.get("weight_kg", 0.5) or 0.5),
            "max_dim_mm": float(rfq.get("max_dim_mm", max([d for d in dims if d] or [100]))),
            "tolerance": rfq.get("tolerance") or rfq.get("tolerance_grade") or "IT8",
        }
        if rfq.get("surface_area_dm2") is not None:
            p["surface_area_dm2"] = float(rfq["surface_area_dm2"])
        if rfq.get("thread_count") is not None:
            p["thread_count"] = int(rfq["thread_count"])
        if any(dims):
            p["dim_x"], p["dim_y"], p["dim_z"] = (float(dims[0]), float(dims[1]), float(dims[2]))
        return p


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default=str(_HERE.parent / "config" / "settings.yaml"))
    a = ap.parse_args()
    try:
        import yaml  # type: ignore
        cfg = yaml.safe_load(Path(a.settings).read_text(encoding="utf-8"))
    except Exception:
        cfg = {"timo": {"engine_src": os.environ.get("CNC_BRAIN_SRC", ""),
                        "engine_python": os.environ.get("CNC_BRAIN_PY", "")}}
    t = TimoAdapter(cfg)
    print("online:", t.online, "| source:", t.source_label())
    print(json.dumps(t.conflict_check("304", "阳极氧化"), ensure_ascii=False, indent=2))
    print(json.dumps(t.quote({"material": "6061", "surface": "阳极氧化", "quantity": 50,
                              "weight_kg": 0.5, "max_dim_mm": 100, "tolerance": "IT7"}),
                     ensure_ascii=False, indent=2)[:600])
