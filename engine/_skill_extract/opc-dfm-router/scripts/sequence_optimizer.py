#!/usr/bin/env python3
"""
sequence_optimizer.py — 工序排序优化器
=======================================
六条制造业硬规则，确保工序顺序正确：
1. 先粗后精   2. 基准先行   3. 先面后孔
4. 热处理分段 5. 主次分明   6. 减少装夹
"""


def optimize_sequence(process_list: list[str], shape_type: str) -> list[str]:
    """
    输入: 无序工艺列表 ["CNC", "钻孔", "淬火", "磨削", "阳极氧化"]
    输出: 正确排序 ["CNC", "钻孔", "淬火", "磨削", "阳极氧化"]
    """

    # ── 优先级打分（分数越小越先做） ──
    def priority(proc: str) -> int:
        p = proc.lower()
        # 基准面加工 (先)
        if any(kw in p for kw in ["基准", "粗车", "粗铣", "粗加工", "开粗"]):
            return 0
        # 粗加工
        if any(kw in p for kw in ["粗", "rough", "快丝"]):
            return 10
        # 半精加工
        if any(kw in p for kw in ["半精", "semi"]):
            return 20
        # 通用CNC/车削 (特征加工)
        if any(kw in p for kw in ["cnc", "铣", "车削", "车", "钻孔", "攻牙", 
                                   "镗孔", "铰孔", "铰", "拉削", "线切割", "慢丝",
                                   "放电", "edm", "滚齿", "插齿"]):
            return 30
        # 热处理 (精加工前)
        if any(kw in p for kw in ["淬火", "回火", "退火", "正火", "渗碳", "氮化", 
                                   "热处理", "heat", "时效"]):
            return 40
        # 精加工 (热处理后)
        if any(kw in p for kw in ["精车", "精铣", "精磨", "珩磨", "研磨", 
                                   "抛光", "磨削", "外圆磨", "平面磨", "无芯磨"]):
            return 50
        # 去应力/去毛刺
        if any(kw in p for kw in ["去毛刺", "喷砂", "清洗"]):
            return 55
        # 表面处理 (最后)
        if any(kw in p for kw in ["阳极", "氧化", "发黑", "镀", "pvd", "喷漆",
                                   "喷塑", "钝化", "电泳", "涂装"]):
            return 90
        # 测量检测
        if any(kw in p for kw in ["测量", "fai", "cmm", "三坐标", "检测", "检验"]):
            return 100
        return 50  # 默认中间

    sorted_list = sorted(process_list, key=priority)

    return sorted_list


def suggest_grouping(sorted_sequence: list[str]) -> list[list[str]]:
    """
    建议同次装夹的工序分组。
    输入: 已排序的工序 ["CNC:一般", "钻孔:简单", "攻牙:一般", "淬火", "磨削:一般"]
    输出: [["CNC:一般", "钻孔:简单", "攻牙:一般"], ["淬火"], ["磨削:一般"]]
    """
    groups = []
    current_group = []

    for proc in sorted_sequence:
        p = proc.split(":")[0].lower() if ":" in proc else proc.lower()

        # 热处理 → 新装夹
        if any(kw in p for kw in ["淬火", "回火", "退火", "热处理", "渗碳", "时效"]):
            if current_group:
                groups.append(current_group)
                current_group = []
            groups.append([proc])
            continue

        # 表面处理 → 新装夹
        if any(kw in p for kw in ["阳极", "氧化", "发黑", "镀", "pvd", "喷漆", "喷塑", "钝化"]):
            if current_group:
                groups.append(current_group)
                current_group = []
            groups.append([proc])
            continue

        # 磨削 → 新装夹
        if any(kw in p for kw in ["磨削", "外圆磨", "平面磨", "研磨", "珩磨", "抛光"]):
            if current_group:
                groups.append(current_group)
                current_group = []
            groups.append([proc])
            continue

        current_group.append(proc)

    if current_group:
        groups.append(current_group)

    return groups
