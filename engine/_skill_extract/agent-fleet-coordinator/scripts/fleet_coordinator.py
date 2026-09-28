#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent-fleet-coordinator — 多Agent舰队协调器

基于 libs/agent_base.py (OO架构)
参考 cad-agent-qa 的 Pipeline + Config-Driven 模式

核心流程:
  TaskDecomposer → AgentRegistry → FleetScheduler → ResultAggregator

使用:
  python3 fleet_coordinator.py --task "完整法兰报价方案" --material 6061 --part 法兰
"""

import sys
import os
import json
import time
import argparse
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

# libs/ 路径
LIBS_PATH = os.path.expanduser("~/.openclaw/libs")
sys.path.insert(0, LIBS_PATH)

from agent_base import AgentBase, AgentConfig, AgentStatus
from intent_router import IntentRouter


# ─── Data Schemas (dataclass pattern from cad-agent-qa) ───

class ExecutionMode(Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"
    DEPENDENCY_GRAPH = "dependency_graph"


@dataclass
class TaskStep:
    """任务步骤 dataclass"""
    id: str
    name: str
    action: str                          # draw | quote | doc | analysis
    agent_name: str                      # 目标Agent名称
    input_params: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # 依赖的步骤ID
    status: str = "pending"              # pending | running | done | failed
    output: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'name': self.name,
            'action': self.action,
            'agent_name': self.agent_name,
            'dependencies': self.dependencies,
            'status': self.status,
        }


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
        return {
            'task_id': self.task_id,
            'steps': [s.to_dict() for s in self.steps],
            'total_steps': self.total_steps,
            'completed': self.completed,
            'failed': self.failed,
            'mode': self.mode.value,
            'elapsed_ms': self.elapsed_ms,
            'outputs': {k: str(v)[:100] for k, v in self.outputs.items()},
        }


# ─── Agent Registry ───

class AgentRegistry:
    """Agent注册表 — 注册所有可用的Skill Agent"""
    
    def __init__(self):
        self._agents: Dict[str, AgentBase] = {}
    
    def register(self, name: str, agent: AgentBase):
        """注册Agent"""
        self._agents[name] = agent
    
    def get(self, name: str) -> Optional[AgentBase]:
        """获取Agent"""
        return self._agents.get(name)
    
    def list_agents(self) -> List[str]:
        """列出所有Agent"""
        return list(self._agents.keys())
    
    def health_check_all(self) -> Dict[str, Dict]:
        """全部健康检查"""
        return {name: agent.health_check() for name, agent in self._agents.items()}


# ─── Task Decomposer ───

class TaskDecomposer:
    """
    任务分解器 — 将复杂任务拆成子步骤
    
    参考 cad-agent-qa 的 QuestionParser → IntentClassifier 链
    """
    
    # 预定义工作流模板
    WORKFLOW_TEMPLATES = {
        'full_quote': [
            ('draw', 'step-factory', '生成STEP三维模型'),
            ('quote', 'quote-ptuning', 'CNC加工报价计算'),
            ('doc', 'doc-gen', '生成报价文档'),
            ('bundle', 'output-bundler', '打包交付'),
        ],
        'draw_quote': [
            ('draw', 'step-factory', '生成STEP三维模型'),
            ('quote', 'quote-ptuning', 'CNC加工报价计算'),
        ],
        'analysis_quote': [
            ('analysis', 'knowledge-querier', '查询材料/工艺知识'),
            ('quote', 'quote-ptuning', '基于知识的报价计算'),
        ],
        'batch_process': [
            ('parse', 'bom-parser', '解析BOM清单'),
            ('batch', 'batch-quote', '批量报价计算'),
            ('export', 'excel-exporter', '导出Excel汇总'),
        ],
    }
    
    def decompose(self, task_description: str, user_params: Dict = None) -> List[TaskStep]:
        """
        分解任务为步骤列表
        
        Args:
            task_description: 任务描述
            user_params: 用户提供的参数 (material, part_type, quantity等)
        
        Returns:
            TaskStep列表
        """
        router = IntentRouter()
        intent = router.classify(task_description)
        params = {**(user_params or {}), **intent.parameters}
        
        # 根据意图选择工作流模板
        template_key = 'draw_quote'  # 默认
        
        if intent.name == 'orchestrate':
            template_key = 'full_quote'
        elif intent.name == 'batch':
            template_key = 'batch_process'
        elif intent.name == 'draw' and '报价' in task_description:
            template_key = 'draw_quote'
        elif intent.name == 'knowledge' and '报价' in task_description:
            template_key = 'analysis_quote'
        
        # 构建步骤
        template = self.WORKFLOW_TEMPLATES.get(template_key, self.WORKFLOW_TEMPLATES['draw_quote'])
        steps = []
        
        for i, (action, agent_name, desc) in enumerate(template):
            step = TaskStep(
                id=f"step_{i+1}",
                name=desc,
                action=action,
                agent_name=agent_name,
                input_params=params,
                dependencies=[steps[-1].id] if steps else [],
            )
            steps.append(step)
        
        return steps


# ─── Fleet Scheduler ───

class FleetScheduler:
    """
    调度器 — 串行/并行执行步骤
    
    参考 cad-agent-qa 的 CADAgentPipeline.execute() 模式
    """
    
    def __init__(self, registry: AgentRegistry, mode: ExecutionMode = ExecutionMode.SERIAL):
        self.registry = registry
        self.mode = mode
    
    def execute(self, steps: List[TaskStep]) -> FleetResult:
        """执行步骤列表"""
        task_id = f"fleet_{int(time.time())}"
        start = time.time()
        
        if self.mode == ExecutionMode.PARALLEL and self._can_parallelize(steps):
            self._execute_parallel(steps)
        else:
            self._execute_serial(steps)
        
        elapsed = (time.time() - start) * 1000
        outputs = {s.id: s.output for s in steps if s.output}
        
        return FleetResult(
            task_id=task_id,
            steps=steps,
            total_steps=len(steps),
            completed=sum(1 for s in steps if s.status == 'done'),
            failed=sum(1 for s in steps if s.status == 'failed'),
            mode=self.mode,
            elapsed_ms=elapsed,
            outputs=outputs,
        )
    
    def _execute_serial(self, steps: List[TaskStep]):
        """串行执行 — 按依赖顺序"""
        for step in steps:
            step.status = 'running'
            agent = self.registry.get(step.agent_name)
            
            if agent is None:
                step.status = 'failed'
                step.output = {'error': f'Agent not found: {step.agent_name}'}
                continue
            
            # 模拟执行（实际场景中agent.run会调用真实Skill）
            try:
                result = agent.run({
                    'action': step.action,
                    **step.input_params,
                })
                if result.get('success'):
                    step.status = 'done'
                    step.output = result
                    # 将输出传给下一步（Pipeline模式）
                    for next_step in steps:
                        if step.id in next_step.dependencies:
                            next_step.input_params.update(result.get('output', {}))
                else:
                    step.status = 'failed'
                    step.output = result
            except Exception as e:
                step.status = 'failed'
                step.output = {'error': str(e)}
    
    def _execute_parallel(self, steps: List[TaskStep]):
        """并行执行 — 无依赖冲突时"""
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            for step in steps:
                agent = self.registry.get(step.agent_name)
                if agent:
                    future = executor.submit(agent.run, {
                        'action': step.action,
                        **step.input_params,
                    })
                    futures[future] = step
                    step.status = 'running'
            
            for future in as_completed(futures):
                step = futures[future]
                try:
                    result = future.result()
                    step.status = 'done' if result.get('success') else 'failed'
                    step.output = result
                except Exception as e:
                    step.status = 'failed'
                    step.output = {'error': str(e)}
    
    def _can_parallelize(self, steps: List[TaskStep]) -> bool:
        """检查是否可以并行化（无依赖冲突）"""
        has_deps = any(s.dependencies for s in steps)
        return not has_deps


# ─── Result Aggregator ───

class ResultAggregator:
    """结果聚合器 — 合并多步骤输出"""
    
    def aggregate(self, fleet_result: FleetResult) -> Dict[str, Any]:
        return {
            'summary': f"完成 {fleet_result.completed}/{fleet_result.total_steps} 步骤, 失败 {fleet_result.failed}",
            'elapsed_ms': fleet_result.elapsed_ms,
            'mode': fleet_result.mode.value,
            'steps_detail': [
                {
                    'step': s.name,
                    'status': s.status,
                    'agent': s.agent_name,
                    'output_keys': list(s.output.keys()) if s.output else [],
                }
                for s in fleet_result.steps
            ],
        }


# ─── Fleet Coordinator (主类) ───

class FleetCoordinator(AgentBase):
    """
    Agent舰队协调器 — 继承 AgentBase 获得熔断/重试/统计
    
    架构: Pipeline模式（学自cad-agent-qa）
    """
    
    def __init__(self, config_path: str = None):
        config = None
        if config_path:
            config = AgentConfig.from_json(config_path)
        else:
            config = AgentConfig(
                name="agent-fleet-coordinator",
                version="1.0.0",
                description="多Agent舰队协调器",
                timeout_seconds=300,
                max_retries=2,
            )
        super().__init__(config=config)
        
        # 初始化子模块（Pipeline模式）
        self.registry = AgentRegistry()
        self.decomposer = TaskDecomposer()
        self.aggregator = ResultAggregator()
        
        # 注册默认Agent
        self._register_default_agents()
    
    def _register_default_agents(self):
        """注册内建Agent"""
        # Quote Agent
        class QuoteAgent(AgentBase):
            def execute(self, task):
                return {
                    'success': True,
                    'action': 'quote',
                    'output': {
                        'unit_price': 185.50,
                        'total_price': 1855.00,
                        'material': task.get('material', '6061'),
                        'quantity': task.get('quantity', 10),
                    }
                }
        
        # Draw Agent
        class DrawAgent(AgentBase):
            def execute(self, task):
                return {
                    'success': True,
                    'action': 'draw',
                    'output': {
                        'step_file': f"{task.get('part_type', 'part')}.step",
                        'dimensions': task.get('dimensions', 'φ100x20'),
                    }
                }
        
        # Doc Agent
        class DocAgent(AgentBase):
            def execute(self, task):
                return {
                    'success': True,
                    'action': 'doc',
                    'output': {
                        'pdf_file': 'quote_report.pdf',
                        'excel_file': 'quote_detail.xlsx',
                    }
                }
        
        # Bundle Agent
        class BundleAgent(AgentBase):
            def execute(self, task):
                return {
                    'success': True,
                    'action': 'bundle',
                    'output': {'zip_file': 'delivery_package.zip'}
                }
        
        # Knowledge Agent
        class KnowledgeAgent(AgentBase):
            def execute(self, task):
                return {
                    'success': True,
                    'action': 'knowledge',
                    'output': {'knowledge_entries': 5, 'material_found': True}
                }
        
        self.registry.register('step-factory', DrawAgent(AgentConfig(name='step-factory')))
        self.registry.register('quote-ptuning', QuoteAgent(AgentConfig(name='quote-ptuning')))
        self.registry.register('doc-gen', DocAgent(AgentConfig(name='doc-gen')))
        self.registry.register('output-bundler', BundleAgent(AgentConfig(name='output-bundler')))
        self.registry.register('knowledge-querier', KnowledgeAgent(AgentConfig(name='knowledge-querier')))
        
        self.logger.info(f"Registered {len(self.registry.list_agents())} agents")
    
    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行舰队任务（覆写AgentBase.execute）
        
        Args:
            task: {'task_description': str, 'material': str, 'part_type': str, ...}
        """
        desc = task.get('task_description', '')
        if not desc:
            return {'success': False, 'error': 'Missing task_description'}
        
        # 1. 分解任务
        steps = self.decomposer.decompose(desc, task)
        self.logger.info(f"Decomposed into {len(steps)} steps: {[s.name for s in steps]}")
        
        # 2. 调度执行
        mode = ExecutionMode.PARALLEL if task.get('parallel') else ExecutionMode.SERIAL
        scheduler = FleetScheduler(self.registry, mode)
        fleet_result = scheduler.execute(steps)
        
        # 3. 聚合结果
        summary = self.aggregator.aggregate(fleet_result)
        
        return {
            'success': fleet_result.failed == 0,
            'result': fleet_result.to_dict(),
            'summary': summary,
        }
    
    def register_agent(self, name: str, agent: AgentBase):
        """注册外部Agent"""
        self.registry.register(name, agent)
        self.logger.info(f"Registered external agent: {name}")


# ─── CLI Entry Point ───

def main():
    parser = argparse.ArgumentParser(description='agent-fleet-coordinator — 多Agent舰队协调器')
    parser.add_argument('--task', '-t', type=str, default='完整法兰报价方案',
                        help='任务描述')
    parser.add_argument('--material', '-m', type=str, default='6061',
                        help='材料')
    parser.add_argument('--part', '-p', type=str, default='法兰',
                        help='零件类型')
    parser.add_argument('--quantity', '-q', type=int, default=10,
                        help='数量')
    parser.add_argument('--parallel', action='store_true',
                        help='并行执行')
    parser.add_argument('--json', action='store_true',
                        help='JSON输出')
    
    args = parser.parse_args()
    
    coordinator = FleetCoordinator()
    
    task = {
        'task_description': args.task,
        'material': args.material,
        'part_type': args.part,
        'quantity': args.quantity,
        'parallel': args.parallel,
    }
    
    result = coordinator.run(task)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"🚀 Agent舰队协调器 v1.0.0")
        print(f"{'='*60}")
        print(f"任务: {args.task}")
        print(f"参数: {args.material} {args.part} ×{args.quantity}")
        print(f"成功: {'✅' if result['success'] else '❌'}")
        
        if result.get('result'):
            fr = result['result']
            print(f"\n步骤明细:")
            for s in fr.get('steps', []):
                icon = '✅' if s['status'] == 'done' else '❌'
                print(f"  {icon} {s['name']} → {s['agent_name']}")
            print(f"\n总计: {fr['completed']}/{fr['total_steps']} 完成, {fr['elapsed_ms']:.0f}ms")
        
        print(f"\n健康检查:")
        for name, status in coordinator.registry.health_check_all().items():
            print(f"  {name}: {'🟢' if status['healthy'] else '🔴'} "
                  f"执行{status['total_executions']}次 "
                  f"失败{status['total_failures']}次")


if __name__ == "__main__":
    main()
