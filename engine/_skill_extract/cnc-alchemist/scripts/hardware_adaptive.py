#!/usr/bin/env python3
"""
hardware_adaptive.py - 硬件自适应检测
支持: Windows WMI / Linux / AMD NPU+iGPU+CPU
禁止硬编码，自动检测
"""
import platform
import psutil
import subprocess
import os
from typing import Dict, Optional


def get_cpu_info() -> str:
    """获取CPU信息"""
    try:
        import cpuinfo
        return cpuinfo.get_cpu_info().get('brand_raw', 'Unknown')
    except:
        return platform.processor() or 'Unknown'


def check_wmi() -> bool:
    """检测WMI是否可用"""
    try:
        import wmi
        return True
    except ImportError:
        return False


class AMDHardware:
    """AMD硬件检测器，自动适应各种平台"""

    def __init__(self):
        self.os_type = platform.system()
        self.backend = self._detect_backend()
        self.info = self._collect_info()
        self.guard = self._emergency_guard()

    def _detect_backend(self) -> str:
        """自动检测硬件后端"""
        # 1. 检测NovaStudio/LM Studio本地API
        for port in [11434, 1234, 8080]:
            if self._check_local_api(port):
                return "novastudio"

        # 2. 检测AMD NPU (Windows)
        if self._check_amd_device("AMD IPU") or self._check_amd_device("Ryzen AI"):
            return "npu"

        # 3. 检测AMD GPU (Windows)
        if self._check_amd_device("Radeon"):
            return "igpu"

        return "cpu"

    def _check_local_api(self, port: int) -> bool:
        """检测本地API是否可用"""
        try:
            import requests
            resp = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=1)
            return resp.status_code == 200
        except:
            return False

    def _check_amd_device(self, keyword: str) -> bool:
        """检测AMD设备"""
        if not check_wmi():
            return False
        try:
            import wmi
            # 检测PNP设备
            for dev in wmi.WMI().Win32_PnPEntity():
                name = getattr(dev, 'Name', '') or ''
                if keyword in name:
                    return True
            # 检测显卡
            for gpu in wmi.WMI().Win32_VideoController():
                name = getattr(gpu, 'Name', '') or ''
                if keyword in name:
                    return True
        except:
            pass
        return False

    def _collect_info(self) -> Dict:
        """收集硬件信息"""
        mem = psutil.virtual_memory()
        info = {
            "os": f"{self.os_type} {platform.release()}",
            "cpu": get_cpu_info(),
            "ram_total_gb": round(mem.total / (1024**3), 1),
            "ram_available_gb": round(mem.available / (1024**3), 1),
            "backend": self.backend
        }
        if self.backend == "npu":
            info["accelerator"] = "AMD Ryzen AI NPU"
        elif self.backend == "igpu":
            info["accelerator"] = "AMD Radeon iGPU"
        elif self.backend == "novastudio":
            info["accelerator"] = "NovaStudio/LM Studio"
        else:
            info["accelerator"] = "CPU Only"
        return info

    def _emergency_guard(self) -> str:
        """紧急情况保护"""
        avail_gb = psutil.virtual_memory().available
        if avail_gb < 4 * (1024**3):
            return "critical"
        if psutil.cpu_percent(interval=0.2) > 90:
            return "high_cpu"
        return "safe"

    def get_profile(self) -> Dict:
        """获取硬件配置"""
        return self.info

    def should_restrict(self) -> bool:
        """是否需要限制资源"""
        return self.guard != "safe"

    def get_level(self) -> str:
        """获取资源级别"""
        avail_gb = psutil.virtual_memory().available / (1024**3)
        if avail_gb >= 80:
            return "showcase"
        elif avail_gb >= 40:
            return "standard"
        return "lite"


if __name__ == '__main__':
    hw = AMDHardware()
    print("硬件检测结果:")
    print(f"  后端: {hw.backend}")
    print(f"  加速器: {hw.info.get('accelerator', 'N/A')}")
    print(f"  内存: {hw.info.get('ram_available_gb', 0)}GB / {hw.info.get('ram_total_gb', 0)}GB")
    print(f"  状态: {hw.guard}")
    print(f"  级别: {hw.get_level()}")
