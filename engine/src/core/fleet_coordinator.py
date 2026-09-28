# -*- coding: utf-8 -*-
"""Agent 舰队协调器 — 融合自 skill.zip/agent-fleet-coordinator 的 Pipeline 架构。

将 zip skill 的多 Agent 编排模式适配到本项目模块，不依赖外部 libs/agent_base，
直接包装项目自身的 generate_part / QuoteAdapter / ConflictChecker / create_bundle / rag_engine。

Pipeline: TaskDecomposer → AgentRegistry → FleetScheduler → ResultAggregator

使用:
    from src.core.fleet_coordinator import FleetCoordinator
    fc = FleetCoordinator()
    result = fc.orchestrate("6061法兰 完整方案 外径100内径50厚20 50件 阳极氧化")
"""
import time, re, threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


# ─── 数据模型 ───

class ExecutionMode(Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"


@dataclass
class TaskStep:
    """任务步骤"""
    id: str
    name: str
    action: str                          # draw | conflict | quote | bundle | rag
    agent_name: str
    input_params: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"              # pending | running | done | failed
    output: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {"id": self.id, "name": self.name, "action": self.action,
                "agent_name": self.agent_name, "dependencies": self.dependencies,
                "status": self.status}


@dataclass
class FleetResult:
    """舰队执行结果"""
    task_id: str
    steps: List[TaskStep]
    total_steps: int
    completed: int
    failed: int
    mode: ExecutionMode
    elapsed_ms: float
    outputs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {"task_id": self.task_id, "steps": [s.to_dict() for s in self.steps],
                "total_steps": self.total_steps, "completed": self.completed,
                "failed": self.failed, "mode": self.mode.value,
                "elapsed_ms": round(self.elapsed_ms, 2),
                "outputs": {k: v for k, v in self.outputs.items()}}


# ─── Agent 基类与项目模块包装 ───

class AgentBase:
    """轻量 Agent 基类（不依赖外部 libs/agent_base）"""
    def __init__(self, name: str):
        self.name = name

    def run(self, task: Dict) -> Dict:
        try:
            output = self.execute(task)
            return {"success": True, "action": task.get("action", ""), "output": output}
        except Exception as e:
            return {"success": False, "action": task.get("action", ""), "error": str(e)}

    def execute(self, task: Dict) -> Dict:
        raise NotImplementedError


class DrawAgent(AgentBase):
    """画图 Agent — 包装 step_generator_dual.generate_part"""
    def __init__(self):
        super().__init__("step-factory")

    def execute(self, task: Dict) -> Dict:
        from src.runtime.step_generator_dual import generate_part
        pt = task.get("part_type") or self._guess_part_type(task.get("task_description", ""))
        params = {}
        for k in ("od", "id", "thickness", "length", "w", "h", "t", "d", "material"):
            if task.get(k) is not None:
                params[k] = task[k]
        # 从描述提取尺寸
        desc = task.get("task_description", "")
        for pat, key in [(r"外径\s*(\d+)", "od"), (r"内径\s*(\d+)", "id"),
                         (r"厚\s*(\d+)", "thickness"), (r"直径\s*(\d+)", "d"),
                         (r"长\s*(\d+)", "length"), (r"宽\s*(\d+)", "w"), (r"高\s*(\d+)", "h")]:
            m = re.search(pat, desc)
            if m and key not in params:
                params[key] = int(m.group(1))
        if "material" not in params:
            params["material"] = task.get("material", "6061")
        result = generate_part(pt, params)
        return {"part_type": pt, "step_file": result.get("step_file"),
                "stl_file": result.get("stl_file"), "stl_url": result.get("stl_url"),
                "bounding_box_mm": result.get("bounding_box_mm"),
                "volume_cm3": result.get("volume_cm3"),
                "estimated_weight_g": result.get("estimated_weight_g")}

    def _guess_part_type(self, desc: str) -> str:
        for cn, en in [("法兰", "flange"), ("轴套", "sleeve"), ("衬套", "sleeve"),
                       ("轴", "shaft"), ("板", "plate"), ("箱体", "box"),
                       ("支架", "bracket"), ("方块", "box")]:
            if cn in desc:
                return en
        return "flange"


class ConflictAgent(AgentBase):
    """冲突检测 Agent — 包装 ConflictChecker.check"""
    def __init__(self):
        super().__init__("conflict-checker")

    def execute(self, task: Dict) -> Dict:
        from src.neuro_core.conflict_check import ConflictChecker
        material = task.get("material", "6061")
        surface = task.get("surface_treatment") or task.get("surface", "无")
        r = ConflictChecker().check({"material": material, "surface_treatment": surface})
        return {"valid": r["valid"], "conflicts": r["conflicts"],
                "warnings": r["warnings"], "total_issues": r["total_issues"]}


class QuoteAgent(AgentBase):
    """报价 Agent — 包装 QuoteAdapter.quote"""
    def __init__(self):
        super().__init__("quote-engine")

    def execute(self, task: Dict) -> Dict:
        from src.runtime.quote_adapter import QuoteAdapter
        material = task.get("material", "6061")
        quantity = task.get("quantity", 10)
        surface = task.get("surface_treatment") or task.get("surface", "无")
        # 从画图步骤获取重量
        weight_kg = None
        if task.get("estimated_weight_g"):
            weight_kg = task["estimated_weight_g"] / 1000.0
        params = {"material": material, "quantity": quantity,
                  "surface_treatment": surface}
        if weight_kg and weight_kg > 0:
            params["weight_kg"] = weight_kg
        r = QuoteAdapter().quote(params)
        return {"final_price": r["final_price"], "unit_price": r["unit_price"],
                "total_price": r["total_price"], "material": r["material"],
                "quantity": r["quantity"], "weight_kg": r["weight_kg"]}


class BundleAgent(AgentBase):
    """打包 Agent — 包装 export_bundler.create_bundle"""
    def __init__(self):
        super().__init__("output-bundler")

    def execute(self, task: Dict) -> Dict:
        from src.runtime.export_bundler import create_bundle
        import os
        files = []
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if task.get("stl_file"):
            files.append(os.path.join(root, "data", "step", task["stl_file"]))
        if task.get("step_file"):
            files.append(os.path.join(root, "data", "step", task["step_file"]))
        quote_data = {k: v for k, v in task.items()
                      if k in ("final_price", "unit_price", "total_price", "material", "quantity")}
        r = create_bundle("fleet", files, quote_data, {"source": "fleet-coordinator"})
        return {"zip_url": r["zip_url"], "zip_file": r["zip_file"], "files": r["files"]}


class RagAgent(AgentBase):
    """知识检索 Agent — 包装 rag_engine.search"""
    def __init__(self):
        super().__init__("rag-searcher")

    def execute(self, task: Dict) -> Dict:
        from src.data.rag_engine import search
        kw = task.get("material", "") + " " + task.get("task_description", "")
        results = search(kw, top_k=3)
        return {"matches": len(results), "results": results}


# ─── Agent 注册表 ───

class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, AgentBase] = {}

    def register(self, name: str, agent: AgentBase):
        self._agents[name] = agent

    def get(self, name: str) -> Optional[AgentBase]:
        return self._agents.get(name)

    def list_agents(self) -> List[str]:
        return list(self._agents.keys())


# ─── 任务分解器 ───

class TaskDecomposer:
    """将自然语言任务分解为 Pipeline 步骤"""

    WORKFLOW_TEMPLATES = {
        "full": [  # 完整方案: 画图→冲突→报价→打包
            ("draw", "step-factory", "生成STEP三维模型"),
            ("conflict", "conflict-checker", "DFM工艺冲突检测"),
            ("quote", "quote-engine", "CNC加工报价计算"),
            ("bundle", "output-bundler", "打包交付"),
        ],
        "draw_quote": [
            ("draw", "step-factory", "生成STEP三维模型"),
            ("quote", "quote-engine", "CNC加工报价计算"),
        ],
        "knowledge_quote": [
            ("rag", "rag-searcher", "知识库检索"),
            ("quote", "quote-engine", "基于知识报价"),
        ],
    }

    def decompose(self, task_description: str, user_params: Dict = None) -> List[TaskStep]:
        params = dict(user_params or {})
        # 修复Bug #15: 传递原始描述供 DrawAgent 正则提取尺寸参数（od/id/thickness等）
        params["task_description"] = task_description
        # 意图判断
        has_draw = any(k in task_description for k in ["画", "生成", "创建", "建模", "法兰", "轴套", "支架"])
        has_quote = any(k in task_description for k in ["报价", "价格", "多少钱", "成本"])
        has_full = any(k in task_description for k in ["完整方案", "全流程", "端到端", "一条龙"])

        if has_full or (has_draw and has_quote):
            template_key = "full"
        elif has_draw:
            template_key = "draw_quote"
        elif has_quote:
            template_key = "knowledge_quote"
        else:
            template_key = "draw_quote"

        # 从描述提取参数
        self._extract_params(task_description, params)

        template = self.WORKFLOW_TEMPLATES[template_key]
        steps = []
        for i, (action, agent_name, desc) in enumerate(template):
            step = TaskStep(
                id=f"step_{i+1}", name=desc, action=action, agent_name=agent_name,
                input_params=dict(params), dependencies=[steps[-1].id] if steps else [],
            )
            steps.append(step)
        return steps

    def _extract_params(self, desc: str, params: Dict):
        if "material" not in params:
            for mat in ["6061", "7075", "304", "316L", "316l", "45钢", "Q235", "q235", "TC4", "tc4", "黄铜"]:
                if mat.lower() in desc.lower():
                    params["material"] = mat
                    break
        if "quantity" not in params:
            m = re.search(r"(\d+)\s*[件个套]", desc)
            if m:
                params["quantity"] = int(m.group(1))
        if "surface_treatment" not in params:
            for s in ["阳极氧化", "发黑", "镀锌", "镀铬", "镀镍", "磷化", "喷漆", "喷砂"]:
                if s in desc:
                    params["surface_treatment"] = s
                    break


# ─── 调度器 ───

class FleetScheduler:
    def __init__(self, registry: AgentRegistry, mode: ExecutionMode = ExecutionMode.SERIAL):
        self.registry = registry
        self.mode = mode

    def execute(self, steps: List[TaskStep]) -> FleetResult:
        task_id = f"fleet_{int(time.time() * 1000)}"
        start = time.time()
        self._execute_serial(steps)
        elapsed = (time.time() - start) * 1000
        outputs = {s.id: s.output for s in steps if s.output}
        return FleetResult(task_id=task_id, steps=steps, total_steps=len(steps),
                           completed=sum(1 for s in steps if s.status == "done"),
                           failed=sum(1 for s in steps if s.status == "failed"),
                           mode=self.mode, elapsed_ms=elapsed, outputs=outputs)

    def _execute_serial(self, steps: List[TaskStep]):
        for step in steps:
            step.status = "running"
            agent = self.registry.get(step.agent_name)
            if agent is None:
                step.status = "failed"
                step.output = {"error": f"Agent not found: {step.agent_name}"}
                continue
            try:
                result = agent.run({"action": step.action, **step.input_params})
                if result.get("success"):
                    step.status = "done"
                    step.output = result.get("output", {})
                    # Pipeline: 将输出注入下一步输入
                    for nxt in steps:
                        if step.id in nxt.dependencies:
                            nxt.input_params.update(step.output)
                else:
                    step.status = "failed"
                    step.output = result
            except Exception as e:
                step.status = "failed"
                step.output = {"error": str(e)}


# ─── 结果聚合器 ───

class ResultAggregator:
    def aggregate(self, fleet_result: FleetResult) -> Dict[str, Any]:
        return {"summary": f"完成 {fleet_result.completed}/{fleet_result.total_steps} 步骤, 失败 {fleet_result.failed}",
                "elapsed_ms": round(fleet_result.elapsed_ms, 2),
                "mode": fleet_result.mode.value,
                "steps_detail": [{"step": s.name, "status": s.status, "agent": s.agent_name}
                                  for s in fleet_result.steps]}


# ─── FleetCoordinator 主类 ───

class FleetCoordinator:
    """Agent 舰队协调器 — 端到端编排: 画图→冲突→报价→打包"""

    def __init__(self):
        self.registry = AgentRegistry()
        self.decomposer = TaskDecomposer()
        self.aggregator = ResultAggregator()
        self._register_default_agents()

    def _register_default_agents(self):
        self.registry.register("step-factory", DrawAgent())
        self.registry.register("conflict-checker", ConflictAgent())
        self.registry.register("quote-engine", QuoteAgent())
        self.registry.register("output-bundler", BundleAgent())
        self.registry.register("rag-searcher", RagAgent())

    def orchestrate(self, task_description: str, **params) -> Dict[str, Any]:
        """编排执行完整任务。

        Args:
            task_description: 自然语言任务描述
            **params: material, quantity, surface_treatment, part_type 等参数

        Returns:
            {success, task_id, summary, steps, outputs}
        """
        steps = self.decomposer.decompose(task_description, params)
        scheduler = FleetScheduler(self.registry, ExecutionMode.SERIAL)
        fleet_result = scheduler.execute(steps)
        summary = self.aggregator.aggregate(fleet_result)
        return {"success": fleet_result.failed == 0,
                "task_id": fleet_result.task_id,
                "summary": summary,
                "result": fleet_result.to_dict()}

    def list_agents(self) -> List[str]:
        return self.registry.list_agents()