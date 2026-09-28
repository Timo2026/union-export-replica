# -*- coding: utf-8 -*-
"""硬件环境探测 — 多厂商自动识别（禁止硬编码端口/地址）。

职责：
- 探测 CPU / 内存 / GPU 基础信息（保持原有 detect() 返回结构，向后兼容）。
- 新增硬件厂商探测：nvidia / amd / musa(摩尔线程) / cpu / unknown。
- 输出统一的 hardware_profile（含 vendor 字段），供 model_auto_loader 路由使用。

检测优先级（宁可 unknown 不瞎猜）：
  1. 环境变量显式覆盖  CNC_AI_HARDWARE_VENDOR / HARDWARE_VENDOR
  2. torch 运行时         torch_musa / torch.cuda(is_available + hip)
  3. GPU 名称字符串匹配   wmic / nvidia-smi / rocm-smi 产出
  4. vLLM MUSA 端点探测  环境变量 MUSA_VLLM_ENDPOINTS（逗号分隔，禁止硬编码）
  5. 环境变量标记         MUSA_HOME / CUDA_HOME / ROCM_HOME 等
  6. 无任何 GPU 信号      → cpu（纯 CPU fallback）
  7. 有 GPU 信号但无法判定 → unknown（不瞎猜）
"""
import platform, os, socket, subprocess, json, urllib.request

__all__ = ["EnvironmentDetector", "normalize_vendor", "VENDOR_ALIASES", "VENDOR_DESCRIPTIONS"]


# ── 厂商归一化映射（单一来源，供 model_auto_loader 复用，避免重复）──
VENDOR_ALIASES = {
    # NVIDIA / CUDA
    "nvidia": "nvidia", "cuda": "nvidia", "geforce": "nvidia",
    "rtx": "nvidia", "gtx": "nvidia", "gt": "nvidia",
    "tesla": "nvidia", "quadro": "nvidia", "titan": "nvidia",
    "a100": "nvidia", "h100": "nvidia", "h200": "nvidia",
    "dgx": "nvidia", "t4": "nvidia", "v100": "nvidia",
    # AMD / ROCm
    "amd": "amd", "radeon": "amd", "rocm": "amd", "hip": "amd",
    "firepro": "amd", "instinct": "amd", "mi300": "amd",
    "mi250": "amd", "mi210": "amd",
    # 摩尔线程 / MUSA
    "musa": "musa", "mtt": "musa", "moore": "musa",
    "mthreads": "musa", "mthread": "musa", "moorethreads": "musa",
    "摩尔": "musa", "摩尔线程": "musa",
    # CPU / 其它
    "cpu": "cpu", "none": "cpu", "any": "any",
    "unknown": "unknown", "": "unknown", None: "unknown",
}

VENDOR_DESCRIPTIONS = {
    "nvidia": "NVIDIA CUDA GPU",
    "amd": "AMD ROCm GPU",
    "musa": "摩尔线程 MUSA GPU",
    "cpu": "纯 CPU（无可用加速器）",
    "any": "硬件无关（通用后端）",
    "unknown": "检测到加速器但厂商无法判定",
}

# 允许通过环境变量显式指定硬件厂商（禁止硬编码：优先尊重用户显式配置）
_HARDWARE_VENDOR_ENV_KEYS = ("CNC_AI_HARDWARE_VENDOR", "HARDWARE_VENDOR")

# 环境变量标记（各厂商 SDK 安装时通常会设置）
_MUSA_ENV_MARKERS = (
    "MUSA_HOME", "MUSA_PATH", "MUSA_VISIBLE_DEVICES",
    "MTT_VISIBLE_DEVICES", "MOFFETT_VISIBLE_DEVICES",
)
_CUDA_ENV_MARKERS = ("CUDA_HOME", "CUDA_PATH", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES")
_ROCM_ENV_MARKERS = ("ROCM_HOME", "ROCM_PATH", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES")


def normalize_vendor(value):
    """把任意厂商字符串归一化为 nvidia/amd/musa/cpu/any/unknown（小写）。

    无法识别时返回 "unknown"（不瞎猜）。
    """
    if value is None:
        return "unknown"
    if not isinstance(value, str):
        return "unknown"
    key = value.strip().lower()
    return VENDOR_ALIASES.get(key, "unknown")


class EnvironmentDetector:
    def __init__(self, project_root):
        self.project_root = project_root

    # ── 基础信息（保持原有行为，向后兼容）──
    def _cpu_brand(self):
        try:
            import psutil
            freq = psutil.cpu_freq()
            if freq:
                return platform.processor() or "CPU"
            return "CPU"
        except Exception:
            pass
        return platform.processor() or platform.machine()

    def _cores(self):
        try:
            import psutil
            return psutil.cpu_count(logical=False) or os.cpu_count() or 1
        except Exception:
            return os.cpu_count() or 1

    def _memory_gb(self):
        try:
            import psutil
            return round(psutil.virtual_memory().total / (1024**3), 1)
        except Exception:
            return 0.0

    def _gpu(self):
        """原有探测：返回 [{name: str}, ...]，供 UI 展示（保持结构不变）。"""
        gpus = []
        # best effort on Windows via wmic, then nvidia-smi / rocm-smi
        try:
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=8)
            for line in out.stdout.splitlines():
                line = line.strip()
                if line and line.lower() != "name":
                    gpus.append({"name": line})
        except Exception:
            pass
        if not gpus:
            for cmd in (["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                        ["rocm-smi", "--showproductname"]):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                    for line in out.stdout.splitlines():
                        line = line.strip()
                        if line:
                            gpus.append({"name": line})
                    if gpus:
                        break
                except Exception:
                    continue
        return gpus

    # ── 厂商探测（新增）──
    def _collect_gpu_names(self):
        """收集所有可获得的 GPU 名称（wmic + nvidia-smi + rocm-smi），用于厂商判定。

        与 _gpu() 不同：这里更积极，即使 wmic 命中也继续查 smi，以便交叉验证厂商。
        """
        names = []
        try:
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=8)
            for line in out.stdout.splitlines():
                line = line.strip()
                if line and line.lower() != "name":
                    names.append(line)
        except Exception:
            pass
        for cmd in (["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    ["rocm-smi", "--showproductname"]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
                for line in out.stdout.splitlines():
                    line = line.strip()
                    if line:
                        names.append(line)
            except Exception:
                continue
        # 去重保序
        seen, deduped = set(), []
        for n in names:
            if n and n.lower() not in seen:
                seen.add(n.lower())
                deduped.append(n)
        return deduped

    def _collect_torch_caps(self):
        """通过 torch 运行时判断 CUDA / ROCm(hip) / MUSA 能力。

        任何异常（未装 torch、无 GPU 驱动等）都吞掉，返回全 False，不影响 CPU fallback。
        """
        caps = {"cuda": False, "hip": False, "musa": False}
        try:
            import torch
            if torch.cuda.is_available():
                caps["cuda"] = True
                try:
                    caps["hip"] = bool(torch.version.hip)
                except Exception:
                    caps["hip"] = False
        except Exception:
            pass
        # 摩尔线程 MUSA 运行时（独立于 torch.cuda）
        try:
            import torch_musa  # noqa: F401
            caps["musa"] = True
        except Exception:
            pass
        return caps

    def _collect_env_markers(self):
        """根据 SDK 环境变量标记判断厂商。"""
        markers = {"nvidia": False, "amd": False, "musa": False}
        for k in _MUSA_ENV_MARKERS:
            if os.environ.get(k):
                markers["musa"] = True
                break
        for k in _CUDA_ENV_MARKERS:
            if os.environ.get(k):
                markers["nvidia"] = True
                break
        for k in _ROCM_ENV_MARKERS:
            if os.environ.get(k):
                markers["amd"] = True
                break
        return markers

    def _check_musa_endpoint(self):
        """探测环境变量 MUSA_VLLM_ENDPOINTS（逗号分隔）指定的 vLLM MUSA 端点。

        端点为配置/环境变量驱动，代码中不写死任何地址。任一端点可达即认为 MUSA 存在。
        """
        raw = os.environ.get("MUSA_VLLM_ENDPOINTS", "")
        if not raw:
            return False
        for ep in raw.split(","):
            ep = ep.strip().rstrip("/")
            if not ep:
                continue
            # 尝试常见健康检查路径（OpenAI 兼容 /models、/health）
            for suffix in ("/models", "/health"):
                url = ep + suffix
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        if 200 <= resp.status < 500:
                            return True
                except Exception:
                    continue
        return False

    def _vendor_from_name(self, name):
        """从单个 GPU 名称字符串判断厂商，返回归一化 vendor 或 None。"""
        if not name:
            return None
        low = name.lower()
        # 精确子串匹配（长关键词优先，避免误判）
        if any(k in low for k in ("musa", "mthread", "moore", "moorethreads", "mtt ", "mtt s", " mtt")):
            return "musa"
        if any(k in low for k in ("nvidia", "geforce", "quadro", "tesla", "rtx ", "rtx-", "gtx ", "gtx-", "titan")):
            return "nvidia"
        if any(k in low for k in ("amd ", "radeon", "firepro", "instinct", "rocm", "mi300", "mi250", "mi210")):
            return "amd"
        return None

    def _decide_vendor(self, signals):
        """根据聚合的探测信号决定最终 vendor。

        优先级：torch 运行时 > GPU 名称 > vLLM MUSA 端点 > 环境变量标记。
        无任何 GPU 信号 → cpu；有信号但无法判定 → unknown（不瞎猜）。
        """
        torch_caps = signals.get("torch", {})
        gpu_names = signals.get("gpu_names", [])
        markers = signals.get("env_markers", {})
        musa_endpoint = signals.get("musa_endpoint", False)

        # 1) torch 运行时最权威
        if torch_caps.get("musa"):
            return "musa"
        if torch_caps.get("cuda"):
            return "amd" if torch_caps.get("hip") else "nvidia"

        # 2) GPU 名称字符串
        for name in gpu_names:
            v = self._vendor_from_name(name)
            if v in ("musa", "nvidia", "amd"):
                return v

        # 3) vLLM MUSA 端点
        if musa_endpoint:
            return "musa"

        # 4) 环境变量标记
        if markers.get("musa"):
            return "musa"
        if markers.get("nvidia"):
            return "nvidia"
        if markers.get("amd"):
            return "amd"

        # 5) 无任何 GPU 信号 → 纯 CPU
        any_gpu_signal = bool(gpu_names) or bool(torch_caps.get("cuda")) or \
            bool(torch_caps.get("hip")) or musa_endpoint or \
            bool(markers.get("nvidia")) or bool(markers.get("amd"))
        if not any_gpu_signal:
            return "cpu"

        # 6) 有 GPU 信号但无法判定厂商 → unknown
        return "unknown"

    def detect_vendor(self):
        """对外接口：只返回归一化 vendor 字符串（nvidia/amd/musa/cpu/unknown）。

        可用于单测与 model_auto_loader 路由。
        """
        # 显式环境变量覆盖优先级最高（用户意图）
        for key in _HARDWARE_VENDOR_ENV_KEYS:
            val = os.environ.get(key)
            if val:
                v = normalize_vendor(val)
                if v != "unknown":
                    return v
        signals = {
            "gpu_names": self._collect_gpu_names(),
            "torch": self._collect_torch_caps(),
            "env_markers": self._collect_env_markers(),
            "musa_endpoint": self._check_musa_endpoint(),
        }
        return self._decide_vendor(signals)

    def detect(self):
        """返回完整环境信息（保持原有字段，向后兼容），并新增 hardware_profile。"""
        gpu = self._gpu()
        torch_caps = self._collect_torch_caps()
        env_markers = self._collect_env_markers()
        musa_endpoint = self._check_musa_endpoint()
        gpu_names = [g["name"] for g in gpu]
        signals = {
            "gpu_names": gpu_names,
            "torch": torch_caps,
            "env_markers": env_markers,
            "musa_endpoint": musa_endpoint,
        }
        vendor = self._decide_vendor(signals)

        profile = {
            "vendor": vendor,
            "capabilities": {
                "cuda": bool(torch_caps.get("cuda")),
                "hip": bool(torch_caps.get("hip")),
                "musa": bool(torch_caps.get("musa") or env_markers.get("musa") or musa_endpoint),
            },
            "gpu_names": gpu_names,
            "detail": VENDOR_DESCRIPTIONS.get(vendor, vendor),
            "evidence": {
                "torch_cuda": bool(torch_caps.get("cuda")),
                "torch_hip": bool(torch_caps.get("hip")),
                "torch_musa": bool(torch_caps.get("musa")),
                "env_musa": bool(env_markers.get("musa")),
                "env_cuda": bool(env_markers.get("nvidia")),
                "env_rocm": bool(env_markers.get("amd")),
                "musa_endpoint": bool(musa_endpoint),
            },
        }

        return {
            "hostname": socket.gethostname(),
            "cpu": {"brand": self._cpu_brand(), "cores_physical": self._cores()},
            "memory_gb": self._memory_gb(),
            "gpu": gpu,
            "hardware_profile": profile,
        }