#!/usr/bin/env python3
"""
cnc_synthesis_pipeline.py - CNC合成工作台完整链路
整合5个新SKILL: rag-enhancer → lite-orchestrator → material-surface-linkage → confidence-calculator → output-bundler
"""
import sys
import json
import importlib.util
from pathlib import Path
from datetime import datetime


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CNCSynthesisPipeline:
    """CNC合成工作台"""
    
    def __init__(self):
        self.skills_dir = Path.home() / '.openclaw/skills'
        self.output_dir = Path.home() / '.openclaw/output'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载SKILL模块
        self.enhancer = load_module('rag_enhancer', f'{self.skills_dir}/rag-enhancer/scripts/rag_enhancer.py').RAGEnhancer()
        self.orchestrator = load_module('lite_orchestrator', f'{self.skills_dir}/lite-orchestrator/scripts/lite_orchestrator.py').LiteOrchestrator()
        self.linkage = load_module('material_linkage', f'{self.skills_dir}/material-surface-linkage/scripts/material_linkage.py').MaterialSurfaceLinkage()
        self.calculator = load_module('confidence_calculator', f'{self.skills_dir}/confidence-calculator/scripts/confidence_calculator.py').ConfidenceCalculator()
        self.bundler = load_module('output_bundler', f'{self.skills_dir}/output-bundler/scripts/output_bundler.py').OutputBundler(str(self.output_dir))
    
    def process(self, user_input: str) -> dict:
        """
        处理用户输入
        
        Args:
            user_input: 自然语言描述
        
        Returns:
            处理结果
        """
        print(f"[Pipeline] 输入: {user_input}")
        
        # Step 1: 轻量编排 - 意图解析
        print("[Step 1] 轻量编排...")
        parsed = self.orchestrator.parse(user_input)
        params = parsed['params']
        print(f"  → 意图: {parsed['intent']}, 零件: {parsed['part_type']}")
        
        # Step 2: RAG增强 - 相似案例检索
        print("[Step 2] RAG增强...")
        rag_result = self.enhancer.enhance(user_input, top_k=3)
        rag_confidence = rag_result['rag_confidence']
        print(f"  → RAG置信度: {rag_confidence}")
        
        # 合并RAG推断参数
        if rag_result.get('suggested_params'):
            for k, v in rag_result['suggested_params'].items():
                if k not in params or params[k] is None:
                    params[k] = v
                    print(f"  → RAG补全: {k}={v}")
        
        # Step 3: 材料-表面联动
        print("[Step 3] 材料-表面联动...")
        material = params.get('material', '')
        if material:
            surface_info = self.linkage.get_info(material)
            default_treatment = surface_info.get('default_treatment', '喷塑')
            if 'surface' not in params or not params['surface']:
                params['surface'] = default_treatment
                print(f"  → 默认表面处理: {default_treatment}")
            else:
                # 检查兼容性
                user_surface = params['surface']
                if not self.linkage.is_compatible(material, user_surface):
                    print(f"  ⚠️ 冲突: {material} + {user_surface} → 强制改为 {default_treatment}")
                    params['surface'] = default_treatment
        
        # Step 4: 置信度计算
        print("[Step 4] 置信度计算...")
        filled_l1 = [k for k, v in params.items() if v is not None]
        confidence_result = self.calculator.calculate({
            'filled_l1': filled_l1,
            'rag_confidence': rag_confidence,
            'rules_valid': True,
            'history_match': 0.3
        })
        total_confidence = confidence_result['total_confidence']
        print(f"  → 总置信度: {total_confidence}")
        print(f"  → 分项: {confidence_result['breakdown']}")
        
        # Step 5: 生成输出（模拟）
        print("[Step 5] 生成输出...")
        output_files = {
            'step': None,  # 由step-factory生成
            'dxf': None,   # 由step-factory生成
            'pdf': None,   # 由converter生成
            'xlsx': None   # 由quote-ptuning生成
        }
        
        # 生成metadata
        metadata = {
            'pipeline_version': '1.0',
            'timestamp': datetime.now().isoformat(),
            'input': user_input,
            'parsed_intent': parsed['intent'],
            'part_type': parsed['part_type'],
            'params': params,
            'confidence': total_confidence,
            'rag_similar_count': len(rag_result.get('similar_cases', []))
        }
        
        print(f"[Pipeline] 完成!")
        print(f"  置信度: {total_confidence}")
        print(f"  参数: {params}")
        
        return {
            'status': 'success',
            'confidence': total_confidence,
            'params': params,
            'output_files': output_files,
            'metadata': metadata
        }


def main():
    if len(sys.argv) < 2:
        print("用法: python3 cnc_synthesis_pipeline.py '<用户输入>'")
        print("示例: python3 cnc_synthesis_pipeline.py '轴承，直径125mm，中心孔30mm，304不锈钢，10件'")
        sys.exit(1)
    
    user_input = sys.argv[1]
    
    pipeline = CNCSynthesisPipeline()
    result = pipeline.process(user_input)
    
    print("\n" + "=" * 50)
    print("最终结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
