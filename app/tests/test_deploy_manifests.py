"""test_deploy_manifests.py — D-P2 部署代码化结构验证 (K8s/NIM 清单不启硬件, 静态校验)。

覆盖: manifest 可解析 / kind 齐备 / HPA 与 Deployment 名称联动 / NIM GPU 预留 /
API key 只走 ${ENV} 引用不留真值 (铁律 data-stays-local)。
真实 GPU 起服验证仍需硬件环境 (SER E-11 标注), 本测试锁"代码化"正确性。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_DEP = Path(__file__).resolve().parent.parent / "deploy"


def _docs(rel: str):
    return [d for d in yaml.safe_load_all((_DEP / rel).read_text(encoding="utf-8")) if d]


def test_k8s_manifest_kinds_and_wiring():
    docs = _docs("k8s.yaml")
    kinds = [d["kind"] for d in docs]
    assert {"ConfigMap", "Deployment", "Service"} <= set(kinds), kinds
    dep = next(d for d in docs if d["kind"] == "Deployment")
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert "readinessProbe" in c and "livenessProbe" in c
    assert c["resources"]["requests"] and c["resources"]["limits"]
    assert any(e.get("configMapRef", {}).get("name") == "uea-config"
               for e in c["envFrom"])
    # volume 与 mount 名称联动
    vol_names = {v["name"] for v in dep["spec"]["template"]["spec"]["volumes"]}
    assert {m["name"] for m in c["volumeMounts"]} <= vol_names


def test_hpa_targets_deployment_and_bounds():
    docs = _docs("hpa.yaml")
    hpa = next(d for d in docs if d["kind"] == "HorizontalPodAutoscaler")
    assert hpa["spec"]["scaleTargetRef"]["name"] == "union-export-agent-api"
    assert 1 <= hpa["spec"]["minReplicas"] <= hpa["spec"]["maxReplicas"]
    assert {"ServiceMonitor", "PrometheusRule"} <= {d["kind"] for d in docs}


def test_compose_services_present():
    top = yaml.safe_load((_DEP / "docker-compose.yml").read_text(encoding="utf-8"))
    assert top.get("services"), "顶层 compose 必须有 services"
    nim = yaml.safe_load((_DEP / "nim" / "docker-compose.yml").read_text(encoding="utf-8"))
    # v2 (2026-09-20): Nemotron 全家族替换 Llama 单服务 (nim-llm 已 deprecated, 仅注释保留)
    assert {"nim-nano-4b", "nim-lightning", "nim-omni", "nim-embed"} <= set(nim["services"])
    # 每个推理服务都必须声明 NVIDIA GPU 预留
    for svc_name in ("nim-nano-4b", "nim-lightning", "nim-omni", "nim-embed"):
        gpu = nim["services"][svc_name]["deploy"]["resources"]["reservations"]["devices"][0]
        assert gpu["driver"] == "nvidia" and "gpu" in gpu["capabilities"], svc_name


def test_nim_secrets_env_only_no_hardcoded_keys():
    txt = (_DEP / "nim" / "docker-compose.yml").read_text(encoding="utf-8")
    # API key 必须形如 ${NGC_API_KEY} 环境引用, 不允许直接赋值字面量
    assert re.search(r"NGC_API_KEY=\$\{NGC_API_KEY\}", txt)
    assert not re.search(r"NGC_API_KEY=(?!\$\{)[A-Za-z0-9_\-]{20,}", txt)
    env_ex = (_DEP / "nim" / ".env.example").read_text(encoding="utf-8")
    assert "\x00" not in env_ex, ".env.example 疑似 UTF-16 (docker compose env-file 不兼容)"
    assert "NGC_API_KEY" in env_ex
    _SENSITIVE = ("KEY", "TOKEN", "PASSWORD", "SECRET", "AUTH")
    for line in env_ex.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, val = line.split("=", 1)
            if not any(s in key.upper() for s in _SENSITIVE):
                continue  # 非敏感键 (镜像名/端口等) 不参检
            val = val.strip()
            assert val == "" or "${" in val or "your-" in val.lower() or "placeholder" in val.lower(), \
                f"敏感键疑似真值: {key}"


def test_grafana_dashboard_valid_json():
    d = json.loads((_DEP / "grafana-dashboard.json").read_text(encoding="utf-8"))
    assert isinstance(d.get("panels", d.get("rows", [])), list)


def test_deploy_no_hardcoded_secret_assignments():
    """deploy/ 全目录: 任何 *_KEY/*_TOKEN/*_PASSWORD 赋值右侧不得是真值 (只许 ${ENV}/占位)。"""
    pat = re.compile(r"(?:API_KEY|TOKEN|PASSWORD|AUTH)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?")
    for p in _DEP.rglob("*"):
        if not p.is_file() or p.suffix == ".pyc":
            continue
        for m in pat.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            val = m.group(1)
            ok = ("DISABLED" in val or "your-" in val.lower()
                  or val.lower().startswith("paste-") or "placeholder" in val.lower())
            assert ok, f"疑似硬编码凭据 {p.name}: {val[:6]}..."
