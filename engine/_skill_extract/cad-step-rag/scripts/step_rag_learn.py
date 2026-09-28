#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD STEP RAG Learning - 优化版
专为 qwen2.5:3b / llama3.2:3b 优化
解决超时、提取精准、JSON格式稳定
"""

import os
import sys
import json
import time
import hashlib
import urllib.request
import urllib.error
import signal
import re
from datetime import datetime
from pathlib import Path

HOME = Path.home()
SKILL_DIR = HOME / ".openclaw/skills/cad-step-rag"
KB_DIR = SKILL_DIR / "knowledge"
STATS_FILE = SKILL_DIR / "learn_stats.json"
LOG_FILE = HOME / ".openclaw/workspace/cad_step_rag.log"

KB_DIR.mkdir(parents=True, exist_ok=True)

# Ollama 配置
OLLAMA_HOST = "http://localhost:11434"
MODELS = ["qwen2.5:3b", "llama3.2:3b"]

# 学习来源
LEARN_SOURCES = [
    HOME / "STEP",
    Path("/media/timo/CE18065718063F49"),
]

# ========== 优化Prompt ==========

# 核心主Prompt - 精准JSON输出
PROMPT_CORE = """你是专业的CAD零件解析专家，仅处理.step格式的3D模型文件。
任务要求：
1. 仅提取核心信息，禁止输出多余文字、解释、markdown
2. 严格输出标准JSON格式，无任何额外内容
3. 提取字段必须包含：
 - path：文件完整路径
 - part_type：零件类型（仅限box/tube/cylinder/flange/other）
 - dimensions：尺寸参数（键名仅限W/H/D/R/inner_r/outer_r，无则留空对象）
 - geometry：几何特征描述（简短文字）
 - process：推荐制造工艺（简短文字）
4. 适配3B小模型，简洁精准，不占用过多算力

输入：CAD STEP模型文件
输出：仅返回标准JSON字符串"""

# 3B精简Prompt
PROMPT_MINI = """你是CAD解析器，只输出JSON。
提取：path、part_type、dimensions、geometry、process。
格式：纯JSON，无其他内容。"""

# 知识增强Prompt - 报价相关
PROMPT_QUOTE = """解析CAD STEP零件，输出标准JSON，新增报价相关参数：
基础字段：path、part_type、dimensions、geometry、process
增强字段：material(推荐材质)、weight(估算重量)、quote_level(报价等级：低/中/高)
仅输出JSON，无其他内容。"""

# 错误重试Prompt
PROMPT_RETRY = """重新解析此STEP文件，修复上一次解析失败问题。
严格输出标准JSON，字段完整，无格式错误，无多余内容。
专注提取零件核心参数，不添加任何无关信息。"""

# 断点续传Prompt
PROMPT_BATCH = """批量解析STEP零件，快速提取结构化数据。
规则：
- 只输出标准JSON数组（多个文件）/单个JSON（单个文件）
- 尺寸、类型、工艺精准提取，无冗余描述
- 快速响应，不做复杂推理，适配批量处理
- 中断后可无缝接续，不重复解析"""

# 一键极简Prompt
PROMPT_SIMPLE = """专家，解析STEP文件，输出纯JSON：path,part_type,dimensions,geometry,process。无多余内容。"""

# ========== 状态 ==========
RUNNING = True

def signal_handler(signum, frame):
    global RUNNING
    print("\n⚠️ 收到停止信号...")
    RUNNING = False

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

class CADStepRAG:
    def __init__(self, prompt_type="core"):
        self.prompt_type = prompt_type
        self.prompt = self._get_prompt(prompt_type)
        self.stats = self.load_stats()
        self.model_index = 0
        self.learned = 0
        self.failed = 0
        self.retry_count = 0
        self.batch_num = 0
        self.session_start = datetime.now()
        
    def _get_prompt(self, ptype):
        prompts = {
            "core": PROMPT_CORE,
            "mini": PROMPT_MINI,
            "quote": PROMPT_QUOTE,
            "retry": PROMPT_RETRY,
            "batch": PROMPT_BATCH,
            "simple": PROMPT_SIMPLE,
        }
        return prompts.get(ptype, PROMPT_SIMPLE)
    
    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        with open(LOG_FILE, 'a') as f:
            f.write(line + "\n")
    
    def load_stats(self):
        if STATS_FILE.exists():
            with open(STATS_FILE) as f:
                return json.load(f)
        return {
            "total_learned": 0,
            "ollama_calls": 0,
            "failed_count": 0,
            "last_learn": None,
            "models_used": [],
        }
    
    def save_stats(self):
        self.stats["ollama_calls"] += self.stats.get("ollama_calls", 0) + self.learned
        self.stats["total_learned"] += self.learned
        self.stats["failed_count"] = self.failed
        self.stats["last_learn"] = datetime.now().isoformat()
        with open(STATS_FILE, 'w') as f:
            json.dump(self.stats, f, indent=2)
    
    def get_file_hash(self, fpath):
        try:
            with open(fpath, 'rb') as f:
                return hashlib.md5(f.read(8192)).hexdigest()[:12]
        except:
            return None
    
    def is_learned(self, fpath):
        fhash = self.get_file_hash(fpath)
        if not fhash:
            return True
        hashes = self.stats.get("learned_hashes", {})
        return fhash in hashes
    
    def mark_learned(self, fpath, fhash=None):
        if not fhash:
            fhash = self.get_file_hash(fpath)
        if fhash:
            if "learned_hashes" not in self.stats:
                self.stats["learned_hashes"] = {}
            self.stats["learned_hashes"][fhash] = {
                "path": str(fpath),
                "at": datetime.now().isoformat()
            }
    
    def get_next_model(self):
        model = MODELS[self.model_index % len(MODELS)]
        self.model_index += 1
        if model not in self.stats.get("models_used", []):
            self.stats.setdefault("models_used", []).append(model)
        return model
    
    def parse_step_content(self, fpath):
        """从STEP文件提取内容"""
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(6000)
            
            # 提取文件名中的尺寸信息
            fname = fpath.name
            dims_from_name = {}
            
            # 盒子: 80x60x10, 100x50x30
            box_match = re.search(r'(\d+)x(\d+)x(\d+)', fname)
            if box_match:
                dims_from_name = {"W": int(box_match.group(1)), "H": int(box_match.group(2)), "D": int(box_match.group(3))}
            
            # 圆柱: r20h60, r50h12
            cyl_match = re.search(r'r(\d+\.?\d*)h(\d+\.?\d*)', fname, re.IGNORECASE)
            if cyl_match:
                dims_from_name = {"R": float(cyl_match.group(1)), "H": float(cyl_match.group(2))}
            
            # 管材: or40ir17.5h70
            tube_match = re.search(r'or(\d+\.?\d*)ir(\d+\.?\d*)h(\d+\.?\d*)', fname, re.IGNORECASE)
            if tube_match:
                dims_from_name = {"outer_r": float(tube_match.group(1)), "inner_r": float(tube_match.group(2)), "H": float(tube_match.group(3))}
            
            return content, dims_from_name, fname
        except Exception as e:
            return None, {}, fpath.name
    
    def ollama_learn(self, fpath, retry=False):
        """Ollama学习"""
        try:
            model = self.get_next_model()
            content, dims_from_name, fname = self.parse_step_content(fpath)
            
            if not content:
                return None
            
            # 构建prompt
            prompt = self.prompt
            
            if dims_from_name:
                dim_str = ", ".join([f"{k}:{v}" for k, v in dims_from_name.items()])
                prompt += f"\n\n文件名提示尺寸: {fname}\n已提取尺寸: {dim_str}\n内容摘要:\n{content[:2000]}"
            else:
                prompt += f"\n\n文件名: {fname}\n内容摘要:\n{content[:2000]}"
            
            # 调用Ollama
            req_data = json.dumps({
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 300}  # 限制输出
            }).encode('utf-8')
            
            req = urllib.request.Request(
                f"{OLLAMA_HOST}/api/generate",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            
            start = time.time()
            with urllib.request.urlopen(req, timeout=45) as resp:  # 45秒超时
                result = json.loads(resp.read().decode('utf-8'))
            duration = time.time() - start
            
            raw = result.get("response", "")
            
            # 解析JSON
            info = self.parse_json_response(raw, fpath, dims_from_name)
            
            if info:
                info["learned_at"] = datetime.now().isoformat()
                info["ollama_model"] = model
                info["learn_duration"] = round(duration, 1)
                return info
            
            return None
            
        except urllib.error.Timeout:
            self.log(f"  ⏰ 超时: {fpath.name}")
            self.retry_count += 1
        except Exception as e:
            self.log(f"  ❌ 失败: {fpath.name} - {e}")
            self.failed += 1
        
        return None
    
    def parse_json_response(self, raw, fpath, dims_hint):
        """解析JSON响应"""
        # 清理markdown
        raw = raw.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        
        # 尝试提取JSON对象
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                
                info = {
                    "path": str(fpath),
                    "name": fpath.name,
                    "type": ".step",
                    "size": fpath.stat().st_size if fpath.exists() else 0,
                }
                
                # 标准化字段
                info["part_type"] = data.get("part_type", data.get("type", "other"))
                info["geometry"] = data.get("geometry", data.get("description", ""))
                info["process"] = data.get("process", data.get("manufacturing", "CNC"))
                
                # 尺寸
                dims = data.get("dimensions", {})
                if not dims and dims_hint:
                    dims = dims_hint
                info["dimensions"] = dims
                
                # 从文件名补充尺寸
                if not info["dimensions"] and dims_hint:
                    info["dimensions"] = dims_hint
                
                return info
                
            except json.JSONDecodeError:
                pass
        
        # 备用：从文件名解析
        if dims_hint:
            return {
                "path": str(fpath),
                "name": fpath.name,
                "type": ".step",
                "size": fpath.stat().st_size if fpath.exists() else 0,
                "part_type": "box" if "x" in fpath.name else "cylinder",
                "dimensions": dims_hint,
                "geometry": f"STEP file: {fpath.name}",
                "process": "CNC",
            }
        
        return None
    
    def save_knowledge(self, info):
        """保存知识"""
        if not info:
            return False
        
        fhash = self.get_file_hash(info["path"])
        
        fname = fhash + ".json" if fhash else hashlib.md5(info["path"].encode()).hexdigest()[:16] + ".json"
        kpath = KB_DIR / fname
        
        with open(kpath, 'w', encoding='utf-8') as f:
            json.dump(info, f, indent=2, ensure_ascii=False)
        
        self.mark_learned(info["path"], fhash)
        self.learned += 1
        
        return True
    
    def scan_step_files(self, limit=20):
        """扫描STEP文件"""
        files = []
        for src_dir in LEARN_SOURCES:
            if not src_dir.exists():
                continue
            try:
                for root, dirs, filenames in os.walk(src_dir):
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for fn in filenames:
                        if fn.lower().endswith(('.step', '.stp')):
                            fpath = Path(root) / fn
                            if not self.is_learned(fpath):
                                files.append(fpath)
                                if len(files) >= limit:
                                    return files
            except Exception as e:
                self.log(f"⚠️ 扫描失败 {src_dir}: {e}")
        return files
    
    def get_cpu_temp(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000
        except:
            return 0
    
    def get_gpu_temp(self):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits", "-i=0"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except:
            pass
        return 0
    
    def temperature_guard(self):
        """温度保护"""
        cpu_t = self.get_cpu_temp()
        gpu_t = self.get_gpu_temp()
        
        if cpu_t >= 85 or gpu_t >= 90:
            self.log(f"🚨 温度临界 CPU:{cpu_t}℃ GPU:{gpu_t}℃ 暂停5分钟")
            time.sleep(300)
            return False
        if cpu_t >= 80 or gpu_t >= 85:
            self.log(f"⚠️ 温度偏高 CPU:{cpu_t}℃ GPU:{gpu_t}℃")
            time.sleep(10)
        return True
    
    def run_batch(self, batch_size=10):
        """执行一批学习"""
        self.batch_num += 1
        
        files = self.scan_step_files(limit=batch_size)
        if not files:
            self.log("✅ 全部STEP文件已学习完毕")
            return False
        
        self.log(f"\n--- Batch#{self.batch_num} | 发现{len(files)}个新文件 ---")
        
        for fpath in files:
            if not RUNNING:
                break
            
            # 温度检查
            self.temperature_guard()
            
            fname = fpath.name
            self.log(f"  🧠 [{self.model_index%2+1}/{len(MODELS)}] {fname[:45]}...")
            
            info = self.ollama_learn(fpath)
            if info:
                self.save_knowledge(info)
                dims = info.get("dimensions", {})
                summary = f"{info.get('part_type','?')} {dims}" if dims else info.get('part_type', '?')
                self.log(f"  ✅ {summary} ({info.get('learn_duration',0)}s)")
            else:
                # 重试一次
                self.log(f"  🔄 重试: {fname}")
                info = self.ollama_learn(fpath, retry=True)
                if info:
                    self.save_knowledge(info)
                    self.log(f"  ✅ 重试成功")
                else:
                    self.log(f"  ❌ 跳过: {fname}")
                    self.failed += 1
        
        self.save_stats()
        
        elapsed = (datetime.now() - self.session_start).total_seconds() / 60
        self.log(f"📊 Batch#{self.batch_num} 完成 | 本批{self.learned}个 | 累计{self.stats['total_learned']}个 | 失败{self.failed}个 | 耗时{elapsed:.1f}分钟")
        
        return True
    
    def run(self, total_batches=0):
        """运行学习"""
        self.log("=" * 60)
        self.log(f"CAD STEP RAG Learning | Prompt: {self.prompt_type}")
        self.log(f"开始: {self.session_start}")
        self.log(f"模型: {MODELS}")
        self.log("=" * 60)
        
        batch = 0
        while RUNNING and (total_batches == 0 or batch < total_batches):
            batch += 1
            if not self.run_batch():
                self.log("学习完成或无新文件")
                break
        
        # 总结
        elapsed = (datetime.now() - self.session_start).total_seconds() / 60
        self.log("\n" + "=" * 60)
        self.log("📊 学习总结:")
        self.log(f"   本次学习: {self.learned} 个")
        self.log(f"   累计学习: {self.stats['total_learned']} 个")
        self.log(f"   失败: {self.failed} 个")
        self.log(f"   重试: {self.retry_count} 次")
        self.log(f"   运行时长: {elapsed:.1f} 分钟")
        self.log("=" * 60)
        
        return self.learned

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="core", choices=["core", "mini", "quote", "batch", "simple"])
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--batches", type=int, default=0, help="0=无限")
    parser.add_argument("--loop", type=int, default=0, help="循环间隔分钟")
    args = parser.parse_args()
    
    learner = CADStepRAG(prompt_type=args.prompt)
    
    if args.loop > 0:
        while RUNNING:
            learner.run(total_batches=args.batches or 999)
            if RUNNING:
                learner.log(f"💤 等待{args.loop}分钟后继续...")
                time.sleep(args.loop * 60)
    else:
        learner.run(total_batches=args.batches or 0)

if __name__ == "__main__":
    main()