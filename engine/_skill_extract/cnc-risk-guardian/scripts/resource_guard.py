#!/usr/bin/env python3
"""
resource_guard.py - GPU/CPU资源守护守护进程
来源: PLLM六级状态机简化为四级 + paperverse GPU ResourceLease
功能: 监控训练进程 -> 自动暂停/恢复Ollama推理服务

状态机:
  ACTIVE    -> Ollama正常运行, 无训练
  YIELDING  -> 检测到训练进程, 等待推理完成
  HIBERNATED -> Ollama已停止, 训练独占资源
  RESTORING -> 训练结束, 正在恢复Ollama

用法: python3 resource_guard.py [--daemon] [--interval 30]
"""
import os
import sys
import time
import subprocess
import json
import signal
from datetime import datetime
from typing import Optional

class ResourceGuard:
    """资源守护 - 四态状态机"""
    
    # 状态
    ACTIVE = "ACTIVE"
    YIELDING = "YIELDING"
    HIBERNATED = "HIBERNATED"
    RESTORING = "RESTORING"
    
    def __init__(self, interval=30, ollama_path="ollama"):
        self.interval = interval  # 检查间隔(秒)
        self.ollama_path = ollama_path
        self.state = self.ACTIVE
        self.state_since = time.time()
        self.last_training_pid = None
        self.cooldown = 30  # 训练结束后30秒缓冲
        
        # 训练进程检测模式
        self.training_patterns = [
            "train_minicpm",
            "train_qwen",
            "train_lora",
            "torch.distributed",
        ]
    
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{self.state}] {msg}")
    
    def _find_training_process(self) -> Optional[int]:
        """查找训练进程PID"""
        try:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split('\n'):
                for pattern in self.training_patterns:
                    if pattern in line and 'grep' not in line and 'resource_guard' not in line:
                        parts = line.split()
                        if len(parts) > 1:
                            return int(parts[1])
        except Exception:
            pass
        return None
    
    def _ollama_running(self) -> bool:
        """检查Ollama是否在运行"""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "ollama serve"],
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _stop_ollama(self):
        """停止Ollama"""
        self._log("停止Ollama推理服务...")
        try:
            subprocess.run(["ollama", "stop"], timeout=10, capture_output=True)
            # 如果ollama stop不work，用pkill
            time.sleep(2)
            if self._ollama_running():
                subprocess.run(["pkill", "-f", "ollama serve"], timeout=5, capture_output=True)
            self._log("Ollama已停止")
        except Exception as e:
            self._log(f"停止Ollama失败: {e}")
    
    def _start_ollama(self):
        """启动Ollama"""
        self._log("启动Ollama推理服务...")
        try:
            # 后台启动
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            # 等待启动
            time.sleep(5)
            if self._ollama_running():
                self._log("Ollama已启动")
            else:
                self._log("⚠️ Ollama启动失败, 稍后重试")
        except Exception as e:
            self._log(f"启动Ollama失败: {e}")
    
    def _transition(self, new_state: str):
        """状态转换"""
        old_state = self.state
        self.state = new_state
        self.state_since = time.time()
        self._log(f"状态转换: {old_state} -> {new_state}")
    
    def step(self):
        """执行一次状态机循环"""
        training_pid = self._find_training_process()
        ollama_up = self._ollama_running()
        
        if self.state == self.ACTIVE:
            if training_pid:
                self.last_training_pid = training_pid
                self._log(f"检测到训练进程 PID={training_pid}")
                self._transition(self.YIELDING)
        
        elif self.state == self.YIELDING:
            # 等待推理请求完成, 然后停止Ollama
            if training_pid:
                if ollama_up:
                    # 给5秒让当前推理完成
                    elapsed = time.time() - self.state_since
                    if elapsed > 5:
                        self._stop_ollama()
                        self._transition(self.HIBERNATED)
                else:
                    self._transition(self.HIBERNATED)
            else:
                # 训练进程消失, 回到ACTIVE
                self._transition(self.ACTIVE)
        
        elif self.state == self.HIBERNATED:
            if not training_pid:
                self._log("训练进程消失, 准备恢复Ollama")
                self._transition(self.RESTORING)
            else:
                self.last_training_pid = training_pid
                # 训练仍在进行, 保持休眠
                if int(time.time()) % 300 == 0:  # 每5分钟报告一次
                    self._log(f"训练进行中 PID={training_pid}")
        
        elif self.state == self.RESTORING:
            elapsed = time.time() - self.state_since
            if elapsed < self.cooldown:
                # 冷却中
                return
            
            if not ollama_up:
                self._start_ollama()
                time.sleep(3)
            
            if self._ollama_running():
                self._log("Ollama恢复成功")
                self._transition(self.ACTIVE)
            else:
                self._log("Ollama恢复失败, 重试中...")
                # 60秒后放弃
                if elapsed > 60:
                    self._log("⚠️ Ollama恢复超时, 请手动检查")
                    self._transition(self.ACTIVE)
    
    def run_daemon(self):
        """守护进程主循环"""
        self._log(f"ResourceGuard启动, 间隔={self.interval}s")
        self._log(f"初始状态: {self.state}")
        
        while True:
            try:
                self.step()
            except KeyboardInterrupt:
                self._log("收到中断信号, 退出")
                break
            except Exception as e:
                self._log(f"异常: {e}")
            
            time.sleep(self.interval)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GPU/CPU Resource Guard")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式")
    parser.add_argument("--interval", type=int, default=30, help="检查间隔(秒)")
    parser.add_argument("--status", action="store_true", help="查看当前状态")
    args = parser.parse_args()
    
    guard = ResourceGuard(interval=args.interval)
    
    if args.status:
        training = guard._find_training_process()
        ollama = guard._ollama_running()
        print(f"状态: {guard.state}")
        print(f"训练进程: {'PID=' + str(training) if training else '无'}")
        print(f"Ollama: {'运行中' if ollama else '已停止'}")
    elif args.daemon:
        guard.run_daemon()
    else:
        # 单次检查
        guard.step()
        print(f"状态: {guard.state}")
