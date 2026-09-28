#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fleet_coordinator_v4 — 混合执行版 Agent 舰队协调器

v3 → v4 核心升级:
  1. ⭐ Python计算引擎: 几何体积/重量/费用全部精确计算，彻底告别模型算术错误
  2. 专家纯推理分工: LLM只做领域分析，不做乘法，不犯低级错误
  3. 精确参数注入: 计算出的数值直接给LLM做知识锚点
  4. 保留 Loop 自迭代 + 知识库增强 + 质量评分

架构图:
  用户输入 → 分解任务 → Python 几何计算(精确) → 专家推理(LLM，基于精确数值) → Orchestrator综合 → 质量评分 → (loop)
"""

import sys, os, json, time, argparse, urllib.request, math
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import dataclass, field

# ─── Config ───

OLLAMA_API = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:1.5b"
OLLAMA_TIMEOUT = 90
NUM_PREDICT = 500
QUALITY_THRESHOLD = 60

KB_PATH = Path.home() / ".openclaw/knowledge/force_deep_rag/learned_knowledge.json"

# ─── 材料库 (精确参数) ───
# 由Python维护，不依赖LLM记忆

MATERIAL_DB = {
    '6061': {
        'name': '6061铝合金',
        'density_g_cm3': 2.70,
        'price_kg': 25,
        'yield_mpa': 275,
        'tensile_mpa': 390,
        'elongation_pct': 8,
        'hardness_hb': 95,
        'anodizing_ok': True,
    },
    '7075': {
        'name': '7075铝合金',
        'density_g_cm3': 2.81,
        'price_kg': 45,
        'yield_mpa': 503,
        'tensile_mpa': 572,
        'elongation_pct': 11,
        'hardness_hb': 150,
        'anodizing_ok': False,
    },
    '304': {
        'name': '304不锈钢',
        'density_g_cm3': 7.93,
        'price_kg': 35,
        'yield_mpa': 205,
        'tensile_mpa': 515,
        'anodizing_ok': False,
    },
    'carbon_steel': {
        'name': '碳钢',
        'density_g_cm3': 7.85,
        'price_kg': 8,
        'yield_mpa': 235,
        'tensile_mpa': 400,
        'anodizing_ok': False,
    },
}

# 表面处理价格 (元/m²)
SURFACE_PRICE = {
    'none': 0,
    'anodizing': 120,   # 黑色阳极氧化
    'pvd': 350,         # PVD涂层
    'spray': 80,        # 喷涂
    'electroplating': 100, # 电镀
}

# CNC加工费率
MACHINING_RATE = 80  # 元/小时

# 毛利率默认
GROSS_MARGIN = 0.20  # 20%

# ─── 精确几何计算引擎 (Python) ───

class CalculationEngine:
    """精确计算引擎 —— 处理所有几何/重量/费用计算，彻底避免模型算术错"""
    
    @staticmethod
    def cylinder_volume_outer_inner_mm(outer_d: float, inner_d: float, length: float) -> float:
        """计算空心圆柱体积（法兰/轴套），单位：mm → cm³"""
        # mm → cm
        od_cm = outer_d / 10.0
        id_cm = inner_d / 10.0
        l_cm = length / 10.0
        # V = π(R² - r²) × length
        volume_cm3 = math.pi * ((od_cm/2)**2 - (id_cm/2)**2) * l_cm
        return volume_cm3
    
    @staticmethod
    def solid_cylinder_volume_mm(d: float, length: float) -> float:
        """计算实心圆柱体积，mm → cm³"""
        d_cm = d / 10.0
        l_cm = length / 10.0
        return math.pi * (d_cm/2)**2 * l_cm
    
    @staticmethod
    def rectangular_block_volume_mm(w: float, h: float, t: float) -> float:
        """长方体体积，mm → cm³"""
        return (w/10) * (h/10) * (t/10)
    
    @staticmethod
    def weight_kg(volume_cm3: float, density_g_cm3: float) -> float:
        """重量计算，kg"""
        return (volume_cm3 * density_g_cm3) / 1000.0
    
    @staticmethod
    def surface_area_cylinder_outer_mm(outer_d: float, length: float) -> float:
        """圆柱外表面积，m²"""
        od_cm = outer_d / 10.0
        l_cm = length / 10.0
        area_cm2 = math.pi * od_cm * l_cm + 2 * math.pi * (od_cm/2)**2  # 侧面积 + 两个底面
        return area_cm2 / 10000  # cm² → m²
    
    @staticmethod
    def calculate_quote(material: str, shape: str, dimensions: Dict,
                       quantity: int, surface: str = 'none') -> Dict:
        """完整报价计算"""
        # 获取材料参数
        mat = MATERIAL_DB.get(material, MATERIAL_DB['6061'])
        
        # 计算体积
        if shape == 'flange':
            volume_cm3 = CalculationEngine.cylinder_volume_outer_inner_mm(
                dimensions['outer_d'], dimensions['inner_d'], dimensions['thickness']
            )
            surface_area_m2 = CalculationEngine.surface_area_cylinder_outer_mm(
                dimensions['outer_d'], dimensions['thickness']
            )
        elif shape == 'bushing':
            volume_cm3 = CalculationEngine.cylinder_volume_outer_inner_mm(
                dimensions['outer_d'], dimensions['inner_d'], dimensions['length']
            )
            surface_area_m2 = CalculationEngine.surface_area_cylinder_outer_mm(
                dimensions['outer_d'], dimensions['length']
            )
        elif shape == 'block':
            volume_cm3 = CalculationEngine.rectangular_block_volume_mm(
                dimensions['width'], dimensions['height'], dimensions['thickness']
            )
            # 表面积近似
            w = dimensions['width']/10
            h = dimensions['height']/10
            t = dimensions['thickness']/10
            area_cm2 = 2 * (w*h + w*t + h*t)
            surface_area_m2 = area_cm2 / 10000
        else:
            # 默认估算
            volume_cm3 = 100.0
            surface_area_m2 = 0.01
        
        # 重量（单件）
        weight_kg_single = CalculationEngine.weight_kg(volume_cm3, mat['density_g_cm3'])
        
        # 工时估算（简化）
        # 粗略：重量×0.5h/kg + 螺纹数×0.1h/孔
        holes = dimensions.get('holes', 0)
        machining_hours = (weight_kg_single * 0.5) + (holes * 0.1)
        if machining_hours < 0.5:
            machining_hours = 0.5
        
        # 费用分项
        material_cost_single = weight_kg_single * mat['price_kg'] * 1.15  # 15%损耗
        machining_cost_single = machining_hours * MACHINING_RATE
        surface_cost_single = surface_area_m2 * SURFACE_PRICE.get(surface, 0)
        total_cost_single = material_cost_single + machining_cost_single + surface_cost_single
        total_cost_single_with_margin = total_cost_single * (1 + GROSS_MARGIN)
        
        # 批量总价
        total_cost_batch = total_cost_single_with_margin * quantity
        
        return {
            'shape': shape,
            'material': material,
            'material_name': mat['name'],
            'volume_cm3': round(volume_cm3, 2),
            'weight_kg_single': round(weight_kg_single, 3),
            'machining_hours_single': round(machining_hours, 2),
            'surface_area_m2': round(surface_area_m2, 3),
            'material_cost_single': round(material_cost_single, 2),
            'machining_cost_single': round(machining_cost_single, 2),
            'surface_cost_single': round(surface_cost_single, 2),
            'total_single': round(total_cost_single_with_margin, 2),
            'total_batch': round(total_cost_batch, 2),
            'quantity': quantity,
            'surface': surface,
        }


# ─── Expert System Prompts ───

EXPERT_PROMPTS = {
    "material_expert": """你是材料工程专家，精通工业材料选型。

给定的几何计算结果和需求已经由Python引擎精确算出，你只需要分析和建议，不需要重新计算。

你的职责:
- 确认材料选型是否合适
- 给出材料性能参数验证
- 指出与表面处理的匹配性
- 有没有更好的替代材料

回答要求: 基于给定的计算数值，给出专业建议，简洁。""",

    "quote_expert": """你是CNC加工报价专家，15年经验。

精确的分项费用已经由Python计算引擎算出，你只需要解释计算逻辑，分析合理性，给出最终报价说明，不需要重新计算。

你的职责:
- 解释分项费用（材料/加工/表面处理）
- 判断工时估算是否合理
- 批量价格分析（批量越大单件越便宜）
- 总体报价合理性评估

回答要求: 基于给定的精确数值，清晰解释报价构成。""",

    "dfm_expert": """你是DFM(面向制造的设计)分析专家。

精确几何尺寸已经由Python算出，你只需要基于给定尺寸分析可制造性，不需要重新计算。

分析维度:
- 最小壁厚: 铝合金CNC≥1.5mm
- 深孔加工: 长径比>5需特殊刀具
- 螺纹要求: M8标准底孔φ6.8mm，深度≥12mm
- 装夹可行性: 薄壁零件是否易变形

回答要求: 区分"真实风险"和"低概率风险"，给出明确改进建议。""",

    "orchestrator": """你是工业制造任务总协调员。

职责:
1. 基于精确计算结果 + 各专家意见，给出综合结论
2. 检测矛盾：如果专家意见不一致，标出
3. 给出最终报价和下一步建议

输出格式:
## 计算验证
[确认计算数值的正确性]

## 矛盾检测
[指出分歧，如无则写"无"]

## 最终报价
[给出单件/批量总价]

## 总结建议
[你的结论]""",

    "critic": """你是质量审核员，给回答打分(满分100):
- 准确性(40): 是否基于给定计算数值
- 完整性(30): 是否覆盖所有问题
- 实用性(20): 建议是否可落地
- 简洁性(10): 不啰嗦

输出格式:
评分: XX/100
扣分项: [具体问题]
需要补充: [还缺什么]""",
}


# ─── 通用工具 ───

def lookup_knowledge(query: str, top_k: int = 3) -> List[str]:
    """查询本地知识库"""
    if not KB_PATH.exists():
        return []

    try:
        with open(KB_PATH, 'r', encoding='utf-8') as f:
            kb = json.load(f)
        entries = kb.get('entries', kb.get('knowledge', []))
    except Exception:
        return []

    results = []
    keywords = query.lower().split()
    for e in entries:
        txt = str(e).lower()
        score = sum(1 for kw in keywords if kw in txt)
        if score > 0:
            content = e.get('content', str(e)) if isinstance(e, dict) else str(e)
            results.append((score, content[:180]))
    
    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:top_k]]


def call_ollama(model: str, system_prompt: str, user_prompt: str,
                temperature: float = 0.3, num_predict: int = NUM_PREDICT) -> Dict:
    """调用 Ollama API"""
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    payload = json.dumps({
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
            "top_k": 20,
            "num_gpu": 99,
        }
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(OLLAMA_API, data=payload,
                                        headers={"Content-Type": "application/json"})
            start = time.time()
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                result = json.loads(resp.read())
            
            elapsed_ms = (time.time() - start) * 1000
            response_text = result.get("response", "").strip()
            
            if not response_text and attempt < 2:
                time.sleep(2)
                continue
            
            return {
                "success": True,
                "response": response_text,
                "elapsed_ms": elapsed_ms,
                "tokens_in": result.get("prompt_eval_count", 0),
                "tokens_out": result.get("eval_count", 0),
            }
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return {
                    "success": False, "response": "", "elapsed_ms": 0,
                    "tokens_in": 0, "tokens_out": 0, "error": str(e),
                }


# ─── Data Structures ───

@dataclass
class AgentResult:
    agent_name: str
    prompt: str
    response: str
    elapsed_ms: float
    tokens_in: int
    tokens_out: int
    success: bool
    kb_context: str = ""
    critique: Optional[Dict] = None
    round_num: int = 1
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'agent_name': self.agent_name,
            'response_preview': self.response[:150],
            'elapsed_ms': self.elapsed_ms,
            'tokens_out': self.tokens_out,
            'success': self.success,
            'round': self.round_num,
        }


@dataclass
class LoopRound:
    round_num: int
    results: Dict[str, AgentResult]
    synthesis: str = ""
    quality_score: int = 0
    critique: str = ""
    gaps: List[str] = field(default_factory=list)
    elapsed_ms: float = 0
    calculation: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            'round': self.round_num,
            'agents': [k for k in self.results],
            'synthesis_preview': self.synthesis[:150] if self.synthesis else '',
            'quality_score': self.quality_score,
            'gaps': self.gaps,
            'elapsed_ms': self.elapsed_ms,
        }


# ─── Expert Agent ───

class ExpertAgentV4:
    """专家Agent v4 — 推理专用，算术交给Python"""
    
    def __init__(self, name: str, domain_key: str, model: str = DEFAULT_MODEL):
        self.name = name
        self.system_prompt = EXPERT_PROMPTS.get(domain_key, "")
        self.domain_key = domain_key
        self.model = model
        self.stats = {'calls': 0, 'total_ms': 0, 'total_tokens': 0}
    
    def ask(self, user_prompt: str, calculation_context: str,
            kb_enhanced: bool = True, critique_context: str = "",
            round_num: int = 1) -> AgentResult:
        """提问：注入精确计算上下文"""
        self.stats['calls'] += 1
        
        # 知识库增强
        kb_text = ""
        if kb_enhanced:
            kb_entries = lookup_knowledge(f"{self.domain_key} {user_prompt}", top_k=3)
            if kb_entries:
                kb_text = "【参考知识库】\n" + "\n".join(f"• {k}" for k in kb_entries) + "\n\n"
        
        # 批评反馈
        critique_text = ""
        if critique_context:
            critique_text = f"【上轮反馈】\n{critique_context}\n请改进回答。\n\n"
        
        # 注入精确计算
        full_prompt = f"""{kb_text}{critique_text}
【精确计算结果（无需重算）】
{calculation_context}

用户问题: {user_prompt}"""
        
        result = call_ollama(self.model, self.system_prompt, full_prompt)
        
        self.stats['total_ms'] += result.get("elapsed_ms", 0)
        self.stats['total_tokens'] += result.get("tokens_out", 0)
        
        return AgentResult(
            agent_name=self.name,
            prompt=user_prompt,
            response=result.get("response", ""),
            elapsed_ms=result.get("elapsed_ms", 0),
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            success=result.get("success", False),
            kb_context=kb_text,
            critique=critique_context,
            round_num=round_num,
            error=result.get("error"),
        )


# ─── Task Decomposer v4 ───

class TaskDecomposerV4:
    """任务分解 + 几何参数提取"""
    
    DOMAIN_KEYWORDS = {
        'material_expert': ['材料', '铝合金', '6061', '7075', '304', '不锈钢',
                           '钛合金', '碳钢', '硬度', '热处理', '阳极', '密度', '强度'],
        'quote_expert': ['报价', '价格', '多少钱', '成本', 'CNC', '加工费', '批量', '总价'],
        'dfm_expert': ['加工', '公差', '精度', '壁厚', '孔', '螺纹', '装夹', '变形',
                      'DFM', '可制造', '工艺'],
    }
    
    def decompose(self, user_input: str) -> List[str]:
        active = []
        for key, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in user_input for kw in keywords):
                active.append(key)
        return active if active else ['material_expert', 'quote_expert', 'dfm_expert']
    
    def extract_geometry(self, user_input: str) -> Tuple[str, Dict, str, str, int]:
        """从用户输入提取几何参数（简单正则提取）"""
        import re
        
        # 检测形状
        shape = 'flange' if '法兰' in user_input else 'bushing' if '轴套' in user_input else 'block'
        
        # 提取尺寸
        dimensions = {}
        
        # 外径
        match = re.search(r'外径[^\d]*(\d+)', user_input)
        if match:
            dimensions['outer_d'] = float(match.group(1))
        # 内径
        match = re.search(r'内径[^\d]*(\d+)', user_input)
        if match:
            dimensions['inner_d'] = float(match.group(1))
        # 厚度/长度
        if '厚度' in user_input:
            match = re.search(r'厚度[^\d]*(\d+)', user_input)
            if match:
                dimensions['thickness'] = float(match.group(1))
        if '长度' in user_input:
            match = re.search(r'长度[^\d]*(\d+)', user_input)
            if match:
                dimensions['length'] = float(match.group(1))
        # 孔数
        match = re.search(r'(\d+)个.*孔', user_input) or re.search(r'(\d+)个.*螺纹', user_input)
        if match:
            dimensions['holes'] = int(match.group(1))
        
        # 提取材料
        material = '6061'
        for m in ['6061', '7075', '304', '碳钢']:
            if m in user_input:
                material = m
                break
        
        # 提取表面处理
        surface = 'none'
        if '阳极' in user_input:
            surface = 'anodizing'
        elif 'PVD' in user_input:
            surface = 'pvd'
        
        # 提取数量
        quantity = 1
        match = re.search(r'(\d+)件', user_input)
        if match:
            quantity = int(match.group(1))
        
        return shape, dimensions, material, surface, quantity


# ─── Orchestrator & Critic ───

class OrchestratorV4:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
    
    def synthesize(self, results: Dict[str, AgentResult], calc: Dict, user_input: str) -> Dict:
        summaries = []
        for key, r in results.items():
            if r.success and r.response:
                summaries.append(f"【{r.agent_name}】\n{r.response}")
        
        calc_text = "\n".join([
            f"- {k}: {v}" for k, v in calc.items()
            if k in ['material_name', 'volume_cm3', 'weight_kg_single', 'total_single', 'total_batch']
        ])
        
        prompt = f"""用户需求: {user_input}

【精确计算结果】
{calc_text}

以下是各专家分析:

{chr(10).join(summaries)}

请:
1. 验证计算是否正确
2. 检测矛盾
3. 给出最终结论

按格式输出。"""
        
        result = call_ollama(self.model, EXPERT_PROMPTS['orchestrator'], prompt,
                            temperature=0.2, num_predict=400)
        
        return {
            "synthesis": result.get("response", ""),
            "elapsed_ms": result.get("elapsed_ms", 0),
            "success": result.get("success", False),
        }


class QualityCritic:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
    
    def evaluate(self, results: Dict[str, AgentResult], synthesis: str, calc: Dict) -> Dict:
        expert_outputs = []
        for key, r in results.items():
            if r.success and r.response:
                expert_outputs.append(f"[{r.agent_name}]\n{r.response[:250]}")
        
        calc_summary = f"体积{calc['volume_cm3']}cm³，单件{calc['weight_kg_single']}kg，单件总价{calc['total_single']}"
        
        eval_prompt = f"""计算数据: {calc_summary}

专家回答:
{chr(10).join(expert_outputs)}

综合结论:
{synthesis[:300]}

请评分，满分100。"""
        
        result = call_ollama(self.model, EXPERT_PROMPTS['critic'], eval_prompt,
                            temperature=0.1, num_predict=150)
        
        critique_text = result.get("response", "")
        
        # 解析分数
        score = 60  # 默认
        import re
        match = re.search(r'评分[:\s]*(\d+)', critique_text)
        if match:
            score = int(match.group(1))
        
        # 识别薄弱专家
        weak = []
        for name in results.keys():
            if name.lower() in critique_text.lower():
                weak.append(name)
        
        return {
            "score": min(score, 100),
            "critique": critique_text,
            "weak_agents": weak,
            "need_retry": score < QUALITY_THRESHOLD,
        }


# ─── Fleet Coordinator v4 (主类) ───

class FleetCoordinatorV4:
    """混合执行版: Python算 + LLM推理"""
    
    def __init__(self, model: str = DEFAULT_MODEL, max_loops: int = 2):
        self.model = model
        self.max_loops = max_loops
        self.decomposer = TaskDecomposerV4()
        self.calculator = CalculationEngine()
        self.orchestrator = OrchestratorV4(model)
        self.critic = QualityCritic(model)
        
        # 专家池
        self.agents: Dict[str, ExpertAgentV4] = {}
        for key in ['material_expert', 'quote_expert', 'dfm_expert']:
            self.agents[key] = ExpertAgentV4(
                name=key.replace('_', ' ').title(),
                domain_key=key,
                model=model,
            )
        
        print(f"🚀 FleetCoordinator v4.0 — 混合执行版")
        print(f"   模型: {model} | 最大轮次: {max_loops} | 质量阈值: {QUALITY_THRESHOLD}")
        print(f"   核心改进: Python算算术 + LLM做推理")
        print(f"   已注册: {len(self.agents)}专家 + 计算引擎 + Orchestrator")
    
    def execute(self, user_input: str, verbose: bool = True) -> Dict:
        total_start = time.time()
        rounds = []
        final_synthesis = ""
        
        # 1. 提取参数 → Python计算（第一步就算出精确值）
        shape, dimensions, material, surface, quantity = self.decomposer.extract_geometry(user_input)
        
        if not all(k in dimensions for k in (
            ['outer_d', 'inner_d', 'thickness'] if shape == 'flange' else
            ['outer_d', 'inner_d', 'length'] if shape == 'bushing' else
            ['width', 'height', 'thickness']
        )):
            print(f"⚠️  参数提取不完整，将尽力继续")
        
        calc = self.calculator.calculate_quote(
            material=material,
            shape=shape,
            dimensions=dimensions,
            quantity=quantity,
            surface=surface,
        )
        
        # 格式化计算结果给专家看
        calc_context = "\n".join([
            f"- 形状: {calc['shape']}",
            f"- 材料: {calc['material_name']}",
            f"- 体积: {calc['volume_cm3']} cm³",
            f"- 单件重量: {calc['weight_kg_single']} kg",
            f"- 单件工时: {calc['machining_hours_single']} h",
            f"- 表面积: {calc['surface_area_m2']} m²",
            f"- 材料费: ¥{calc['material_cost_single']}",
            f"- 加工费: ¥{calc['machining_cost_single']}",
            f"- 表面处理费: ¥{calc['surface_cost_single']}",
            f"- 单件总价(含20%毛利): ¥{calc['total_single']}",
            f"- {calc['quantity']}件总价: ¥{calc['total_batch']}",
        ])
        
        if verbose:
            print(f"\n{'='*60}")
            print(f"📋 任务: {user_input}")
            print(f"🔢 Python计算结果:")
            print(calc_context)
        
        # 分解任务（专家）
        active_experts = self.decomposer.decompose(user_input)
        
        if verbose:
            print(f"\n🧠 激活专家: {', '.join(active_experts)}")
        
        # ─── Loop迭代 ───
        for round_num in range(1, self.max_loops + 1):
            round_start = time.time()
            
            if verbose:
                print(f"\n{'─'*60}")
                print(f"🔄 Round {round_num}/{self.max_loops}")
                print(f"{'─'*60}")
            
            # 上轮批评
            critique_by_agent = {}
            if rounds:
                last = rounds[-1]
                if last.critique:
                    for name in active_experts:
                        agent_name = self.agents[name].name
                        if agent_name.lower() in last.critique.lower():
                            critique_by_agent[name] = last.critique
            
            # 并行查询专家
            results: Dict[str, AgentResult] = {}
            active = [k for k in active_experts if k in self.agents]
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {}
                for key in active:
                    agent = self.agents[key]
                    crit = critique_by_agent.get(key, "")
                    future = executor.submit(
                        agent.ask, user_input,
                        calculation_context=calc_context,
                        kb_enhanced=(round_num == 1),
                        critique_context=crit,
                        round_num=round_num,
                    )
                    futures[future] = key
                
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        result = future.result(timeout=OLLAMA_TIMEOUT)
                        results[key] = result
                        if verbose:
                            icon = '✅' if result.success else '❌'
                            print(f"  {icon} {result.agent_name:20s} | {result.elapsed_ms:5.0f}ms | {result.tokens_out:3d}t")
                    except Exception as e:
                        results[key] = AgentResult(
                            agent_name=key, prompt="", response="",
                            elapsed_ms=0, tokens_in=0, tokens_out=0,
                            success=False, round_num=round_num, error=str(e),
                        )
            
            # Orchestrator综合
            synth = self.orchestrator.synthesize(results, calc, user_input)
            synthesis = synth.get("synthesis", "")
            
            # 质量评分
            quality = self.critic.evaluate(results, synthesis, calc)
            score = quality.get("score", 60)
            
            round_elapsed = (time.time() - round_start) * 1000
            
            loop_round = LoopRound(
                round_num=round_num,
                results={k: v for k, v in results.items() if v.success},
                synthesis=synthesis,
                quality_score=score,
                critique=quality.get("critique", ""),
                gaps=quality.get("weak_agents", []),
                elapsed_ms=round_elapsed,
                calculation=calc,
            )
            rounds.append(loop_round)
            
            if verbose:
                print(f"  🎯 评分: {score}/100 | 耗时: {round_elapsed:.0f}ms")
                if quality.get("need_retry"):
                    print(f"  ⚠️ 质量不足，需重试")
            
            # 质量门控
            if not quality.get("need_retry") or round_num >= self.max_loops:
                final_synthesis = synthesis
                break
        
        total_elapsed = (time.time() - total_start) * 1000
        
        return {
            'success': any(r.success for r in rounds[-1].results.values()),
            'user_input': user_input,
            'total_rounds': len(rounds),
            'final_quality_score': rounds[-1].quality_score if rounds else 0,
            'final_synthesis': final_synthesis,
            'calculation': calc,
            'expert_details': {k: v.response for k, v in rounds[-1].results.items()},
            'rounds': [r.to_dict() for r in rounds],
            'total_elapsed_ms': round(total_elapsed),
            'model': self.model,
            'architecture': 'Python calculation + LLM reasoning',
        }


# ─── Display ───

def print_report(result: Dict, verbose: bool = False):
    calc = result['calculation']
    print(f"\n{'='*60}")
    print(f"📊 FleetCoordinator v4 执行报告")
    print(f"{'='*60}")
    print(f"任务:    {result['user_input']}")
    print(f"架构:    {result['architecture']}")
    print(f"轮次:    {result['total_rounds']}")
    print(f"评分:    {result['final_quality_score']}/100")
    print(f"总耗时:  {result['total_elapsed_ms']}ms ({result['total_elapsed_ms']/1000:.1f}s)")
    print()
    print(f"📐 精确计算结果:")
    print(f"   形状: {calc['shape']} | 材料: {calc['material_name']}")
    print(f"   体积: {calc['volume_cm3']} cm³ | 重量: {calc['weight_kg_single']} kg")
    print(f"   单件总价: ¥{calc['total_single']} | {calc['quantity']}件总价: ¥{calc['total_batch']}")
    
    if verbose and result.get('expert_details'):
        for key, text in result['expert_details'].items():
            print(f"\n{'─'*60}")
            print(f"💬 {key}:")
            print(f"{'─'*60}")
            print(text[:500])
    
    if result.get('final_synthesis'):
        print(f"\n{'─'*60}")
        print(f"🎯 最终结论:")
        print(f"{'─'*60}")
        print(result['final_synthesis'])


# ─── CLI ───

def main():
    parser = argparse.ArgumentParser(description='FleetCoordinator v4 — 混合执行版')
    parser.add_argument('--task', '-t', type=str, required=True, help='任务描述')
    parser.add_argument('--model', '-m', type=str, default=DEFAULT_MODEL, help='Ollama模型')
    parser.add_argument('--loops', '-l', type=int, default=2, help='最大迭代轮次')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示专家完整回答')
    parser.add_argument('--json', '-j', action='store_true', help='JSON输出')
    
    args = parser.parse_args()
    
    # 检查Ollama
    try:
        urllib.request.urlopen(
            urllib.request.Request("http://localhost:11434/api/tags"), timeout=5)
    except Exception:
        print("❌ Ollama 未响应，请先启动: ollama serve")
        sys.exit(1)
    
    coordinator = FleetCoordinatorV4(
        model=args.model,
        max_loops=args.loops,
    )
    
    result = coordinator.execute(user_input=args.task, verbose=True)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result, verbose=args.verbose)


if __name__ == "__main__":
    main()