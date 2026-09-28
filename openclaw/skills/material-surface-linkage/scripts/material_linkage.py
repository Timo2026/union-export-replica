#!/home/Developer/miniconda3/envs/lk-skills/bin/python
"""
material_linkage.py - 材料-表面处理联动规则库
智能匹配兼容工艺，禁止冲突选择
"""
import json
import argparse
from typing import Dict, List, Optional


class MaterialSurfaceLinkage:
    """材料-表面处理联动器"""
    
    # 材料分类映射
    MATERIAL_CATEGORIES = {
        # 铝合金
        '铝合金': ['6061', '7075', '5052', '6063', '2A12', '铝', 'Al'],
        # 不锈钢
        '不锈钢': ['304', '316', '不锈钢', 'stainless', 'SS'],
        # 碳钢
        '碳钢': ['碳钢', '45#', '45钢', 'Q235', '钢', '铁', 'steel'],
        # 铜合金
        '铜合金': ['铜', '黄铜', 'H59', 'H62', '青铜', 'copper', 'brass'],
        # 铸铁
        '铸铁': ['铸铁', '灰铁', 'cast iron'],
        # 工程塑料
        '塑料': ['POM', 'PA66', 'ABS', 'PVC', '塑料', 'nylon']
    }
    
    # 材料-表面处理兼容表
    COMPATIBILITY = {
        '铝合金': {
            'treatments': ['阳极氧化', '导电氧化', '喷塑', '喷漆'],
            'default': '阳极氧化',
            'forbidden': ['发黑', '发蓝', '镀锌', '镀镍']
        },
        '不锈钢': {
            'treatments': ['钝化', '镀镍', '喷塑', '喷漆'],
            'default': '钝化',
            'forbidden': ['发黑', '发蓝', '镀锌']
        },
        '碳钢': {
            'treatments': ['发黑', '发蓝', '镀锌', '镀镍', '喷塑', '喷漆'],
            'default': '发黑',
            'forbidden': ['阳极氧化', '导电氧化', '钝化']
        },
        '铜合金': {
            'treatments': ['镀镍', '镀锌', '喷塑', '喷漆'],
            'default': '镀镍',
            'forbidden': ['阳极氧化', '发黑', '发蓝', '钝化']
        },
        '铸铁': {
            'treatments': ['发黑', '喷塑', '喷漆'],
            'default': '发黑',
            'forbidden': ['阳极氧化', '镀锌', '镀镍']
        },
        '塑料': {
            'treatments': ['喷塑', '喷漆'],
            'default': '喷塑',
            'forbidden': ['发黑', '发蓝', '镀锌', '镀镍', '阳极氧化', '钝化']
        }
    }
    
    # 牌号-材料类别映射
    GRADE_TO_CATEGORY = {}
    for category, grades in MATERIAL_CATEGORIES.items():
        for grade in grades:
            GRADE_TO_CATEGORY[grade.lower()] = category
    
    def __init__(self):
        pass
    
    def detect_category(self, material: str) -> Optional[str]:
        """
        检测材料类别
        
        Args:
            material: 材料名称或牌号
        
        Returns:
            材料类别或None
        """
        material_lower = material.lower()
        
        for category, keywords in self.MATERIAL_CATEGORIES.items():
            if any(kw.lower() in material_lower for kw in keywords):
                return category
        
        return None
    
    def get_compatible_treatments(self, material: str) -> List[str]:
        """
        获取兼容的表面处理列表
        
        Args:
            material: 材料名称或牌号
        
        Returns:
            兼容的表面处理列表
        """
        category = self.detect_category(material)
        
        if category is None:
            # 未知材料，返回通用选项
            return ['喷塑', '喷漆']
        
        return self.COMPATIBILITY.get(category, {}).get('treatments', ['喷塑', '喷漆'])
    
    def get_default_treatment(self, material: str) -> str:
        """
        获取默认表面处理
        
        Args:
            material: 材料名称或牌号
        
        Returns:
            默认表面处理
        """
        category = self.detect_category(material)
        
        if category is None:
            return '喷塑'
        
        return self.COMPATIBILITY.get(category, {}).get('default', '喷塑')
    
    def get_forbidden_treatments(self, material: str) -> List[str]:
        """
        获取禁止的表面处理列表
        
        Args:
            material: 材料名称或牌号
        
        Returns:
            禁止的表面处理列表
        """
        category = self.detect_category(material)
        
        if category is None:
            return []
        
        return self.COMPATIBILITY.get(category, {}).get('forbidden', [])
    
    def is_compatible(self, material: str, treatment: str) -> bool:
        """
        检查材料-表面处理是否兼容
        
        Args:
            material: 材料名称
            treatment: 表面处理名称
        
        Returns:
            True if compatible, False if forbidden
        """
        forbidden = self.get_forbidden_treatments(material)
        return treatment not in forbidden
    
    def filter_treatments(self, material: str, treatments: List[str]) -> List[str]:
        """
        过滤出兼容的表面处理
        
        Args:
            material: 材料名称
            treatments: 表面处理列表
        
        Returns:
            兼容的表面处理列表
        """
        forbidden = set(self.get_forbidden_treatments(material))
        return [t for t in treatments if t not in forbidden]
    
    def get_info(self, material: str) -> dict:
        """
        获取完整的材料-表面处理信息
        
        Args:
            material: 材料名称或牌号
        
        Returns:
            完整信息字典
        """
        category = self.detect_category(material)
        compatible = self.get_compatible_treatments(material)
        default = self.get_default_treatment(material)
        forbidden = self.get_forbidden_treatments(material)
        
        return {
            'material': material,
            'category': category,
            'compatible_treatments': compatible,
            'default_treatment': default,
            'forbidden_treatments': forbidden
        }


def main():
    parser = argparse.ArgumentParser(description='材料-表面处理联动规则')
    parser.add_argument('--material', required=True, help='材料名称或牌号')
    parser.add_argument('--action', default='info', choices=['info', 'compatible', 'default', 'check'],
                        help='操作类型')
    parser.add_argument('--treatment', help='表面处理名称(用于check)')
    args = parser.parse_args()
    
    linkage = MaterialSurfaceLinkage()
    
    if args.action == 'info':
        result = linkage.get_info(args.material)
    elif args.action == 'compatible':
        result = linkage.get_compatible_treatments(args.material)
    elif args.action == 'default':
        result = linkage.get_default_treatment(args.material)
    elif args.action == 'check':
        if args.treatment:
            result = {
                'material': args.material,
                'treatment': args.treatment,
                'compatible': linkage.is_compatible(args.material, args.treatment)
            }
        else:
            result = {'error': '--treatment required for check action'}
    
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
